"""Persistent outbox and bounded, idempotent background task execution."""
import asyncio
import contextlib
import logging
from datetime import datetime, timedelta, timezone
from celery import Celery
from sqlalchemy import select, case, and_, or_
from app.config import settings
from app.db import SessionLocal
from app.models import ProcessingTask, Outbox, Session, SegmentRevision, Translation, AudioAsset, RecognitionStream, User, now
from app.services.events import emit, save_translation, save_final, enqueue, latest_segments
from app.services.translation_timing import TranslationTiming, wall_queue_ms
from app.services.retired_tasks import RETIRED_TASK_KIND, cancel_retired_task, cancel_retired_tasks

logger=logging.getLogger('classbridge.tasks')
celery_app=Celery('classbridge',broker=settings.redis_url,backend=settings.redis_url)
celery_app.conf.update(task_serializer='json',accept_content=['json'],result_serializer='json',
    task_acks_late=True,worker_prefetch_multiplier=1,task_reject_on_worker_lost=True,
    task_soft_time_limit=720,task_time_limit=750,broker_connection_retry_on_startup=True,
    broker_transport_options={'queue_order_strategy':'priority','priority_steps':[0,3,6,9]},
    beat_schedule={'outbox':{'task':'classbridge.dispatch','schedule':.5 if settings.incremental_translation_enabled else 3.0},'expire-audio':{'task':'classbridge.expire_audio','schedule':3600.0},
                   'recover-abandoned':{'task':'classbridge.recover_abandoned','schedule':60.0}})


class PendingRemoteTask(Exception):pass


async def translate(db,task):
    from app.providers.aliyun import AliyunProvider
    row=db.get(SegmentRevision,task.payload['segment_id'])
    if not row:return {'skipped':'source_deleted'}
    latest=db.query(SegmentRevision).filter_by(session_id=row.session_id,sentence_id=row.sentence_id).order_by(SegmentRevision.source_revision.desc()).first()
    if latest.id!=row.id or latest.status!='final':return {'skipped':'superseded_source'}
    if db.query(Translation).filter_by(segment_id=row.id).first():return {'skipped':'translation_already_saved'}
    session=db.get(Session,row.session_id)
    if session.mode=='demo':return {'skipped':'demo_translation_committed_atomically'}
    user=db.get(User,session.user_id)
    terms=(user.settings or {}).get('terms',[])
    reused=None
    if settings.incremental_translation_enabled:
        from app.services.incremental_translation import translation_spec,validated_reuse
        reused=validated_reuse(task.payload.get('preview_candidate'),row,translation_spec(settings,terms),now())
    import time
    translated='';first=None;last_emit=0
    source_id=row.id;source_created=row.created_at.replace(tzinfo=timezone.utc) if row.created_at.tzinfo is None else row.created_at
    execution_time=now()
    queue_wait,clock_skew=wall_queue_ms(task.created_at,execution_time)
    source_wait,_=wall_queue_ms(source_created,execution_time)
    db.commit()
    timing=TranslationTiming()
    async def output():
        if reused is not None:
            yield reused
        else:
            kwargs={'terms':terms}
            if settings.incremental_translation_enabled:kwargs['require_complete']=True
            async for delta in AliyunProvider().translate_stream(row.text,**kwargs):yield delta
    async for delta in output():
        if not delta:continue
        timing.token();first=0 if reused is not None else timing.first
        translated+=delta
        if reused is None and time.monotonic()-last_emit>=(settings.translation_emit_seconds if settings.incremental_translation_enabled else .15):
            db.expire_all();source=db.get(SegmentRevision,source_id)
            if not source:return {'skipped':'source_deleted'}
            current=db.query(SegmentRevision).filter_by(session_id=source.session_id,sentence_id=source.sentence_id).order_by(SegmentRevision.source_revision.desc()).first()
            if current.id!=source.id or current.status!='final':return {'skipped':'superseded_source'}
            session=db.get(Session,source.session_id)
            emit(db,session,'translation.partial',stream_id=source.stream_id,sentence_id=source.sentence_id,
                 source_revision=source.source_revision,translation_revision=1,start_ms=source.start_ms,end_ms=source.end_ms,
                 translation=translated,status='partial',source_status='final')
            db.commit();last_emit=time.monotonic()
    db.expire_all()
    row=db.get(SegmentRevision,row.id)
    if not row:return {'skipped':'source_deleted'}
    if not translated.strip():
        from app.providers.aliyun import ProviderError
        raise ProviderError('format_error','翻译服务未返回文本，原文已保留。')
    model_timing=timing.finish() if reused is None else {'translation_model_first_ms':0,'translation_model_final_ms':0}
    elapsed=model_timing['translation_model_final_ms']
    source_delay=max(0,int(row.latency.get('source_final_ms',0)))
    row.latency={**row.latency,'translation_first_ms':source_delay+source_wait+(first or 0),
      'translation_final_ms':source_delay+source_wait+elapsed,'translation_queue_ms':queue_wait,
      **model_timing,'translation_reused':reused is not None,'translation_clock':'server_estimate_from_source_audio_end',
      'translation_queue_clock':'wall_task_created_to_attempt_start','translation_queue_clock_skew':clock_skew}
    save_translation(db,row.id,translated)
    db.commit()
    return {'segment_id':row.id,'reused':reused is not None,'translation_queue_ms':queue_wait,**model_timing}


async def reprocess(db,task):
    from app.providers.aliyun import AliyunProvider, ProviderError, normalize_filetrans
    from app.services.storage import get_storage
    provider=AliyunProvider();payload=dict(task.payload)
    session=db.get(Session,task.session_id)
    if not session:return {'skipped':'session_deleted'}
    if session.status in ('preparing','recording','processing'):raise ValueError('请停止录音并等待收尾后再执行会后校正')
    session_id=session.id;task_id=task.id;user_id=task.user_id
    if session.user_id!=user_id:raise ValueError('会后校正任务归属不匹配')
    jobs=dict(payload.get('remote_jobs',{}));done=list(payload.get('completed_audio_ids',[]))
    for audio_id in payload['audio_ids']:
        if audio_id in done:continue
        audio=db.get(AudioAsset,audio_id)
        if not audio or audio.status!='ready':continue
        if audio.session_id!=session_id:raise ValueError('音频不属于当前会话')
        expiry=audio.expires_at.replace(tzinfo=timezone.utc) if audio.expires_at.tzinfo is None else audio.expires_at
        if expiry<=now():raise ValueError('音频已超过保留期限，不能进行会后校正')
        snapshots=dict(payload.get('source_snapshots',{}))
        if audio_id not in snapshots:
            snapshots[audio_id]={s.sentence_id:s.source_revision for s in latest_segments(db,session_id) if s.stream_id==audio.stream_id}
            payload['source_snapshots']=snapshots;task.payload=dict(payload);db.commit()
        job=jobs.get(audio_id)
        if job=='submission_uncertain':
            raise ValueError('文件转写提交结果不确定，已停止自动重试以避免重复付费；请先检查云端任务')
        if not job:
            # Persist intent before submission. A process crash in this window must not silently submit again.
            jobs[audio_id]='submission_uncertain';payload['remote_jobs']=jobs;task.payload=dict(payload);db.commit()
            job=await provider.submit_filetrans(get_storage().signed_url(audio.storage_key,ttl=3600))
            jobs[audio_id]=job;payload['remote_jobs']=dict(jobs);task.payload=dict(payload);db.commit()
        result=await provider.poll_filetrans(job)
        if result is None:raise PendingRemoteTask()
        # Validate the complete result before touching any stable source version.
        sentences=normalize_filetrans(result)
        if not sentences:
            raise ProviderError('empty_transcript','会后识别未返回可用文字，已保留现有字幕；不会用空结果替换原文。')
        db.expire_all()
        session=db.get(Session,session_id);audio=db.get(AudioAsset,audio_id);task=db.get(ProcessingTask,task_id)
        if not session or not audio or not task:return {'skipped':'source_deleted'}
        if session.user_id!=user_id or audio.session_id!=session_id:raise ValueError('音频归属已变更')
        if session.status in ('preparing','recording','processing'):raise ValueError('录音重新开始，会后校正结果未覆盖当前字幕')
        # File timestamps are relative to each recorded connection; preserve its true offset.
        old_rows=[s for s in latest_segments(db,session.id) if s.stream_id==audio.stream_id]
        if {s.sentence_id:s.source_revision for s in old_rows}!=snapshots[audio_id]:
            raise ProviderError('source_changed','转写期间原文版本已变化，已保留新版本；请核对后再整理。')
        matched=set()
        for index,sentence in enumerate(sentences):
            text=sentence['text'].strip()
            start=audio.offset_ms+sentence['start_ms'];end=audio.offset_ms+sentence['end_ms']
            # Match by overlap where possible; inserted sentences get a durable new identity.
            matches=[s for s in old_rows if s.sentence_id not in matched and max(s.start_ms,start)<min(s.end_ms,end)]
            best=max(matches,key=lambda s:min(s.end_ms,end)-max(s.start_ms,start)) if matches else None
            if best:matched.add(best.sentence_id)
            sid=best.sentence_id if best else f'{audio.stream_id}:file:{job}:{index}'
            latest=db.query(SegmentRevision).filter_by(session_id=session.id,sentence_id=sid).order_by(SegmentRevision.source_revision.desc()).first()
            revision=latest.source_revision+1 if latest else 1
            save_final(db,session.id,audio.stream_id,sid,revision,text,start,end,provenance='filetrans',force=True,commit=False)
            corrected=db.query(SegmentRevision).filter_by(session_id=session.id,sentence_id=sid,source_revision=revision).one()
            corrected.speaker=sentence['speaker']
        # A split/merge may leave original sentence identities unmatched. A new retired
        # revision removes them from current reading/retrieval without erasing old citations.
        for old in old_rows:
            if old.sentence_id in matched:continue
            retired=SegmentRevision(session_id=session.id,stream_id=audio.stream_id,sentence_id=old.sentence_id,
                source_revision=old.source_revision+1,start_ms=old.start_ms,end_ms=old.end_ms,text=old.text,
                mode=session.mode,status='retired',provenance='filetrans',latency={})
            db.add(retired);db.flush()
            emit(db,session,'segment.updated',stream_id=audio.stream_id,sentence_id=old.sentence_id,
                source_revision=retired.source_revision,translation_revision=0,start_ms=old.start_ms,end_ms=old.end_ms,
                status='retired',message='会后校正已合并或替换此片段，原引用仍可追溯')
        done.append(audio_id);payload['completed_audio_ids']=done;task.payload=dict(payload);db.commit()
    enqueue(db,session.user_id,'summarize',f'summary:reprocess:{task.id}',{'session_id':session.id,'user_id':session.user_id},session_id=session.id)
    db.commit();return {'corrected_audio_ids':done,'source':'filetrans','original_revisions_preserved':True}


async def execute_task(task_id):
    with SessionLocal() as db:
        task=db.execute(select(ProcessingTask).where(ProcessingTask.id==task_id).with_for_update()).scalar_one_or_none()
        if task and task.kind==RETIRED_TASK_KIND:
            # Broker deliveries from the old release must never reach a model,
            # even when a retry or an abandoned running task is replayed.
            cancel_retired_task(task);db.commit();return
        if not task or task.status not in ('pending','retry'):return
        if task.attempts>=task.max_attempts:
            task.status='failed';task.error='已达到有限重试上限';db.commit();return
        task.status='running';task.attempts+=1;task.updated_at=now();db.commit()
        try:
            if task.kind=='translate': result=await translate(db,task)
            elif task.kind=='reprocess': result=await reprocess(db,task)
            elif task.kind=='export':
                from app.api.sessions import export_text
                from app.services.exporting import render_pdf
                from app.services.storage import get_storage
                row=db.get(Session,task.session_id)
                if not row:return
                format=task.payload.get('format','pdf')
                content=export_text(db,row,format=='md');key=f'exports/{row.id}/{task.id}.{format}'
                title=row.title
                db.commit()
                value=await asyncio.to_thread(render_pdf,content,title) if format=='pdf' else content.encode('utf-8')
                db.expire_all()
                if db.get(Session,task.session_id) is None:return
                # Keep the final write + database result in one uninterrupted
                # section so deletion cannot race an orphan export into storage.
                get_storage().put(key,value);result={'storage_key':key}
            else:
                from app.services.knowledge import handle_task
                result=await handle_task(task.kind,task.payload,db)
            task=db.get(ProcessingTask,task_id)
            if task:
                task.status='completed';task.result=result or {};task.error=None;task.updated_at=now()
                if 'preview_candidate' in task.payload:task.payload={k:v for k,v in task.payload.items() if k!='preview_candidate'}
                db.commit()
        except PendingRemoteTask:
            db.rollback();task=db.get(ProcessingTask,task_id)
            if task:
                polls=int(task.payload.get('poll_count',0))+1
                task.payload={**task.payload,'poll_count':polls}
                # Polling an existing cloud job does not submit another paid inference.
                task.attempts=max(0,task.attempts-1);task.status='retry' if polls<180 else 'failed'
                task.error=None if polls<180 else '文件转写等待超过允许轮询次数';task.updated_at=now();db.commit()
        except Exception as exc:
            db.rollback();task=db.get(ProcessingTask,task_id)
            if not task:return
            from app.providers.aliyun import ProviderError
            retryable=isinstance(exc,ProviderError) and exc.retryable
            task.error=exc.message if isinstance(exc,ProviderError) else (str(exc)[:500] if isinstance(exc,ValueError) else '后台处理失败，请查看服务端错误类型')
            task.status='retry' if retryable and task.attempts<task.max_attempts else 'failed'
            task.updated_at=now()
            row=db.get(Session,task.session_id) if task.session_id else None
            if row:
                emit(db,row,'processing.failed',code=getattr(exc,'code','task_failed'),message=task.error,status=task.status,task_id=task.id,task_kind=task.kind)
            db.commit();logger.warning('task_failed kind=%s code=%s attempt=%d',task.kind,getattr(exc,'code',type(exc).__name__),task.attempts)


@celery_app.task(name='classbridge.execute')
def process_task(task_id):asyncio.run(execute_task(task_id))


def pending_task_ids(db):
    if cancel_retired_tasks(db):db.commit()
    current=now()
    query=db.query(ProcessingTask).filter(ProcessingTask.status.in_(['pending','retry']))
    if settings.incremental_translation_enabled:
        # Filter retry backoff BEFORE limit, so sleeping retries cannot hide a
        # fresh final translation behind the first 50 rows.
        due=or_(*[and_(ProcessingTask.attempts==n,ProcessingTask.updated_at<=current-timedelta(seconds=min(30,2**max(1,n)))) for n in range(5)],
                and_(ProcessingTask.attempts>=5,ProcessingTask.updated_at<=current-timedelta(seconds=30)))
        query=query.filter(or_(ProcessingTask.status=='pending',due)).order_by(case((ProcessingTask.kind=='translate',0),else_=1))
    rows=query.order_by(ProcessingTask.created_at).limit(50).all()
    return [t.id for t in rows if t.status=='pending' or (current-(t.updated_at.replace(tzinfo=timezone.utc) if t.updated_at.tzinfo is None else t.updated_at)).total_seconds()>=min(30,2**max(1,t.attempts))]


@celery_app.task(name='classbridge.dispatch')
def dispatch_outbox():
    with SessionLocal() as db:
        for task_id in pending_task_ids(db):
            box=db.query(Outbox).filter_by(task_id=task_id).first()
            if settings.incremental_translation_enabled:
                if box and box.dispatched_at:
                    age,_=wall_queue_ms(box.dispatched_at,now())
                    if age<30000:continue # bound broker duplicates; outbox still recovers lost delivery
                task=db.get(ProcessingTask,task_id)
                process_task.apply_async(args=[task_id],priority=0 if task.kind=='translate' else 6)
            else:process_task.delay(task_id)
            if box:box.dispatched_at=now()
            db.commit()


@celery_app.task(name='classbridge.expire_audio')
def expire_audio():
    from app.services.storage import delete_audio_files
    with SessionLocal() as db:
        for asset in db.query(AudioAsset).filter(AudioAsset.status.in_(['ready','failed','empty']),AudioAsset.expires_at<now()).all():
            delete_audio_files(asset);asset.status='expired'
        db.commit()


@celery_app.task(name='classbridge.recover_abandoned')
def recover_abandoned():
    with SessionLocal() as db:
        cancel_retired_tasks(db)
        for task in db.query(ProcessingTask).filter(ProcessingTask.status=='running',ProcessingTask.updated_at<now()-timedelta(minutes=15)):
            # Recovery is deliberately conservative for chargeable operations.
            task.status='failed';task.error='后台进程中断，结果不确定；已停止自动重试以避免重复调用'
        db.commit()


async def local_worker_loop():
    active={};last_cleanup=0
    from app.services import translation_dispatch
    wakeup=asyncio.Event()
    translation_dispatch.worker_loop=asyncio.get_running_loop()
    translation_dispatch.worker_wakeup=wakeup
    try:
        while True:
            wakeup.clear()
            active={tid:pair for tid,pair in active.items() if not pair[1].done()}
            if len(active)<2:
                with SessionLocal() as db:
                    ids=pending_task_ids(db)
                    kinds={tid:db.get(ProcessingTask,tid).kind for tid in ids}
                for tid in ids:
                    if tid in active:continue
                    if len(active)>=2:break
                    # Keep total concurrency at two; reserve capacity for final
                    # translation instead of starting more paid workers.
                    if (settings.incremental_translation_enabled and kinds[tid]!='translate'
                        and any(kind!='translate' for kind,_ in active.values())):continue
                    active[tid]=(kinds[tid],asyncio.create_task(execute_task(tid)))
            if asyncio.get_running_loop().time()-last_cleanup>60:
                expire_audio();recover_abandoned();last_cleanup=asyncio.get_running_loop().time()
            if settings.incremental_translation_enabled:
                try:await asyncio.wait_for(wakeup.wait(),timeout=settings.translation_poll_seconds)
                except asyncio.TimeoutError:pass
            else:await asyncio.sleep(.6)
    finally:
        translation_dispatch.worker_loop=None;translation_dispatch.worker_wakeup=None
        for _,task in active.values():task.cancel()
        for _,task in active.values():
            with contextlib.suppress(asyncio.CancelledError):await task
