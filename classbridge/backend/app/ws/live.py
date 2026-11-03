import asyncio
import array
import contextlib
import json
import logging
import math
import sys
import time
import wave
from collections import deque
from pathlib import Path
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.api.auth import authenticate_cookie, COOKIE_NAME
from app.config import settings
from app.db import SessionLocal
from app.models import Session, RecognitionStream, Event, AudioAsset, User, ProcessingTask, SegmentRevision, uid
from app.services.events import emit, save_final, enqueue, save_interrupted, latest_segments
from app.services.timing import captured_duration_ms
from app.services.retired_tasks import RETIRED_EVENT_TYPE

router=APIRouter()
logger=logging.getLogger('classbridge.ws')
connections={}

DEMO_SENTENCES=[
 ('오늘은 인공지능과 검색 증강 생성, RAG에 대해 배워 보겠습니다.', '今天我们学习人工智能与检索增强生成，也就是 RAG。'),
 ('A language model generates an answer from its learned patterns. Retrieval gives it evidence from our own documents.', '语言模型根据学到的模式生成回答；检索则为它提供来自我们自己资料的证据。'),
 ('벡터 검색은 단어가 같지 않아도 의미가 비슷한 내용을 찾습니다.', '向量检索可以找到含义相近的内容，即使使用的词语并不相同。'),
 ('Hybrid search combines keyword matching with semantic similarity. We rerank the candidates before answering.', '混合检索结合关键词匹配与语义相似度，在回答之前还会对候选证据重新排序。'),
 ('답변에는 출처가 필요합니다. 문서 페이지와 수업의 타임스탬프를 확인하세요.', '回答需要附上来源，请核对文档页码与课堂时间戳。'),
 ('For next class, compare keyword search and vector search on the same question. The deadline is next Tuesday.', '下次课请比较同一问题的关键词检索与向量检索，截止时间原话为“下周二”，具体日期待确认。'),
]


class LiveCapture:
    def __init__(self,ws,session_id,user_id):
        self.ws=ws;self.session_id=session_id;self.user_id=user_id
        self.queue=asyncio.Queue(maxsize=settings.audio_max_queue_frames)
        self.stream_id=None;self.mode=None;self.offset=0;self.started=0;self.task=None
        self.stopping=False;self.current_revisions={};self.finalized=set();self.last_results={};self.final_results=set();self.translation_tasks={}
        self.last_translation={};self.first_seen={};self.audio_file=None;self.audio_path=None;self.audio_id=None;self.audio_bytes=0
        self.send_lock=asyncio.Lock()
        self.last_backlog_check=0;self.capture_ended=None;self.queued_bytes=0
        self.ready=False;self.request_id=None;self.captured_before=0
        self.asr_metrics={};self.failure_reported=False
        self.asr_language_mode='auto'
        self.asr_acoustic_profile='far'
        self.asr_enhancement={}
        self.received_audio_ms=0;self.last_audio_at=None;self.level_window=deque(maxlen=50)
        self.preview=None
        self.unconfirmed={}
        self.target_language=None

    def capture_language(self):
        if self.target_language is None:
            from app.services.translation_languages import target_code
            with SessionLocal() as db:
                row=db.get(Session,self.session_id)
                self.target_language=target_code(row.target_language) if row else 'zh-CN'
        return self.target_language

    def ensure_preview(self):
        if not settings.incremental_translation_enabled or self.mode!='real':return None
        if self.preview is None:
            from app.providers.aliyun import AliyunProvider
            from app.services.incremental_translation import IncrementalTranslator, translation_spec
            with SessionLocal() as db:
                user=db.get(User,self.user_id)
                terms=(user.settings or {}).get('terms',[]) if user else []
            self.preview=IncrementalTranslator(settings,self.stream_id,translation_spec(settings,terms,self.capture_language()),
                AliyunProvider(),self.publish_preview)
        return self.preview

    async def publish_preview(self,sid,revision,start,end,translated,metadata):
        if sid in self.finalized or self.current_revisions.get(sid)!=revision:return
        first_at=metadata.pop('preview_first_at')
        latency={key:metadata.pop(key) for key in ('preview_model_first_ms','preview_model_final_ms')}
        latency['preview_first_ms']=max(0,int((first_at-self.started)*1000)-(start-self.offset))
        latency['preview_clock']='server_estimate_from_source_audio_start'
        await self.transient('translation.partial',sentence_id=sid,source_revision=revision,translation_revision=revision,
            start_ms=start,end_ms=end,translation=translated,status='partial',latency=latency,**metadata)

    async def preview_loop(self):
        while True:
            await asyncio.sleep(.1)
            if self.preview and not self.stopping:self.preview.tick()

    async def send(self,payload):
        async with self.send_lock: await asyncio.wait_for(self.ws.send_json(payload),timeout=10)

    async def transient(self,event_type,**fields):
        await self.send({'type':event_type,'event_id':uid(),'event_seq':0,'session_id':self.session_id,
          'stream_id':self.stream_id,'mode':self.mode,'target_language':self.capture_language(),**fields})

    async def start(self,request_id=None):
        if self.task and not self.task.done():
            await self.transient('processing.failed',request_id=request_id,code='already_recording',message='录音已经开始');return
        with SessionLocal() as db:
            row=db.get(Session,self.session_id)
            if row.status in ('preparing','recording','processing'):
                await self.transient('processing.failed',request_id=request_id,code='session_active',message='会话正在另一连接中录音');return
            if db.query(ProcessingTask).filter(ProcessingTask.session_id==row.id,ProcessingTask.kind=='reprocess',ProcessingTask.status.in_(['pending','retry','running'])).first():
                await self.transient('processing.failed',request_id=request_id,code='post_processing_active',message='会后音频整理尚未完成，请等待处理结束后继续录音');return
            if row.mode=='real' and not settings.dashscope_api_key:
                await self.transient('processing.failed',request_id=request_id,code='missing_api_key',message='服务器未配置 DASHSCOPE_API_KEY，真实模式已拒绝');return
            self.captured_before=captured_duration_ms(db,row.id)
            if self.captured_before>=settings.capture_max_seconds*1000:
                await self.transient('processing.failed',request_id=request_id,code='application_duration_limit',message='此会话已达到105分钟应用限制，请创建新会话');return
            if sum(1 for item in connections.values() if item.task and not item.task.done())>=2:
                await self.transient('processing.failed',request_id=request_id,code='concurrency_limit',message='同时采集的会话已达应用上限，请先停止另一会话');return
            self.target_language=row.target_language
            self.stream_id=uid();self.mode=row.mode;self.offset=row.duration_ms;self.started=0;self.stopping=False
            self.ready=False;self.request_id=request_id
            self.asr_metrics={};self.failure_reported=False
            self.received_audio_ms=0;self.last_audio_at=None;self.level_window.clear()
            self.preview=None
            self.unconfirmed={}
            self.capture_ended=None;self.last_backlog_check=0
            self.queue=asyncio.Queue(maxsize=settings.audio_max_queue_frames)
            self.queued_bytes=0
            self.current_revisions={};self.finalized=set();self.last_results={};self.final_results=set();self.first_seen={};self.last_translation={}
            self.audio_id=None;self.audio_bytes=0
            stream=RecognitionStream(id=self.stream_id,session_id=row.id,status='preparing',offset_ms=self.offset,mode=self.mode)
            db.add(stream);db.flush();row.active_stream_id=self.stream_id;row.status='preparing'
            emit(db,row,'session.state',state='preparing',status='preparing',request_id=self.request_id,
                 message='正在准备识别服务，请稍候再说话')
            db.commit()
        self.task=asyncio.create_task(self.run())
        # Enter run's try/finally before an immediately following cancel/stop.
        await asyncio.sleep(0)

    async def mark_ready(self):
        if self.stopping:raise asyncio.CancelledError()
        with SessionLocal() as db:
            row=db.get(Session,self.session_id)
            if not row or row.active_stream_id!=self.stream_id:raise asyncio.CancelledError()
            if self.mode=='real':
                first=db.query(RecognitionStream).filter(RecognitionStream.session_id==row.id,
                    RecognitionStream.ended_ms>RecognitionStream.offset_ms).order_by(RecognitionStream.created_at).first()
                if first:
                    origin=first.created_at.replace(tzinfo=timezone.utc) if first.created_at.tzinfo is None else first.created_at
                    self.offset=max(row.duration_ms,int((datetime.now(timezone.utc)-origin).total_seconds()*1000))
                    if self.offset>row.duration_ms+500:
                        emit(db,row,'capture.gap',stream_id=self.stream_id,start_ms=row.duration_ms,end_ms=self.offset,
                             duration_ms=self.offset-row.duration_ms,status='gap',message='两次采集之间的暂停或断线时段没有音频')
            self.started=time.monotonic();self.ready=True
            stream=db.get(RecognitionStream,self.stream_id)
            stream.status='active';stream.offset_ms=self.offset;stream.created_at=datetime.now(timezone.utc)
            row.status='recording';row.duration_ms=self.offset
            emit(db,row,'session.state',state='recording',status='recording',ready=True,request_id=self.request_id,
                 offset_ms=self.offset,captured_ms=self.captured_before,asr_language_mode=self.asr_language_mode,asr_acoustic_profile=self.asr_acoustic_profile,asr_enhancement=self.asr_enhancement,
                 message='模拟演示，不调用付费 API' if self.mode=='demo' else '识别服务已就绪，可以开始说话')
            if row.retain_audio and self.mode=='real':
                temp=Path(settings.data_dir)/'audio-temp';temp.mkdir(parents=True,exist_ok=True)
                self.audio_path=temp/(self.stream_id+'.wav')
                self.audio_file=wave.open(str(self.audio_path),'wb');self.audio_file.setnchannels(1);self.audio_file.setsampwidth(2);self.audio_file.setframerate(16000)
                asset=AudioAsset(id=uid(),session_id=row.id,stream_id=self.stream_id,storage_key=f'audio/{row.id}/{self.stream_id}.wav',offset_ms=self.offset,expires_at=datetime.now(timezone.utc)+timedelta(days=settings.audio_retention_days))
                db.add(asset);self.audio_id=asset.id;self.audio_bytes=0
            db.commit()

    async def audio(self,data):
        if not self.task or self.task.done() or self.stopping or self.mode!='real': return
        if not self.ready:
            await self.fail('capture_not_ready','识别服务尚未就绪，请刷新页面后重新开始，等待准备完成再说话')
            await self.stop();return
        if time.monotonic()-self.last_backlog_check>=1:
            self.last_backlog_check=time.monotonic()
            with SessionLocal() as db:
                pending=db.query(ProcessingTask).filter(ProcessingTask.session_id==self.session_id,ProcessingTask.status.in_(['pending','retry','running'])).count()
            if pending>=200:
                await self.gap('后台待处理任务积压超过200项',None);await self.fail('task_backlog','后台处理队列已满，已停止采集；请等待任务完成后继续');await self.stop();return
        if not data or len(data)>32000 or len(data)%2:
            await self.fail('audio_format','音频必须为 16 kHz 单声道 PCM16LE，单帧不超过一秒');await self.stop();return
        if self.queue.full() or self.queued_bytes+len(data)>64000:
            await self.gap('音频队列已满',None);await self.fail('audio_backlog','音频转发积压超过 2 秒，已停止采集；请检查服务器到阿里云的网络后重新开始。');await self.stop();return
        if self.audio_file:
            self.audio_file.writeframesraw(data);self.audio_bytes+=len(data)
        self.queue.put_nowait(data);self.queued_bytes+=len(data)
        self.received_audio_ms+=len(data)//32;self.last_audio_at=time.monotonic()
        samples=array.array('h',data)
        if sys.byteorder!='little':samples.byteswap()
        if samples:self.level_window.append((self.last_audio_at,sum(x*x for x in samples),len(samples)))
        # VPN/network bursts may arrive without yielding in ws.receive(). Give
        # the upstream sender a turn instead of filling a healthy queue in a loop.
        await asyncio.sleep(0)

    def diagnostics(self):
        stamp=time.monotonic()
        level=[(energy,count) for at,energy,count in self.level_window if stamp-at<=1]
        rms=math.sqrt(sum(e for e,_ in level)/sum(n for _,n in level)) if level else 0
        return {'queue_frames':self.queue.qsize(),'queued_audio_ms':self.queued_bytes//32,
                'preview_metrics':{**self.preview.metrics,'stable_rollbacks':self.preview.prefix.rollbacks} if self.preview else None,
                'received_audio_ms':self.received_audio_ms,
                'last_audio_age_ms':int((stamp-self.last_audio_at)*1000) if self.last_audio_at is not None else None,
                'input_dbfs':round(20*math.log10(max(rms,1)/32768),1),
                'transcript_events':self.asr_metrics.get('transcript_events',0),
                'last_transcript_age_ms':int((stamp-self.asr_metrics.get('last_transcript_monotonic',self.started))*1000) if self.started else 0,
                'sent_audio_ms':self.asr_metrics.get('sent_audio_ms',0),
                'send_wait_ms':self.asr_metrics.get('send_wait_ms',0),
                'last_send_age_ms':int((stamp-self.asr_metrics['last_send_monotonic'])*1000) if self.asr_metrics.get('last_send_monotonic') else None,
                'last_upstream_event_age_ms':int((stamp-self.asr_metrics['last_event_monotonic'])*1000) if self.asr_metrics.get('last_event_monotonic') else None}

    async def gap(self,reason,duration_ms=None):
        with SessionLocal() as db:
            row=db.get(Session,self.session_id)
            if not row:return
            payload=emit(db,row,'capture.gap',stream_id=self.stream_id,status='gap',start_ms=self.offset+int((time.monotonic()-self.started)*1000) if self.started else row.duration_ms,
                         duration_ms=duration_ms,message=str(reason)[:500])
            if self.audio_id:
                asset=db.get(AudioAsset,self.audio_id)
                if asset:asset.gaps=[*(asset.gaps or []),payload]
            db.commit()

    async def fail(self,code,message,diagnostics=None):
        if self.failure_reported:return
        self.failure_reported=True
        details={**self.diagnostics(),**(diagnostics or {})}
        logger.warning('capture_failed session_id=%s stream_id=%s code=%s diagnostics=%s',self.session_id,self.stream_id,code,details)
        with SessionLocal() as db:
            row=db.get(Session,self.session_id)
            if row:
                emit(db,row,'processing.failed',stream_id=self.stream_id,request_id=self.request_id,code=str(code),message=str(message)[:500],status='failed',diagnostics=details)
                db.commit()

    async def stop(self):
        if self.stopping:return
        self.stopping=True
        self.capture_ended=time.monotonic()
        if not self.task or self.task.done():return
        if self.mode=='demo' or not self.ready: self.task.cancel()
        else:
            with SessionLocal() as db:
                row=db.get(Session,self.session_id)
                if row and row.active_stream_id==self.stream_id:
                    row.status='processing';emit(db,row,'session.state',state='processing',status='processing',request_id=self.request_id);db.commit()
            # Make room only for the ending sentinel. Audio is never silently discarded.
            try: await asyncio.wait_for(self.queue.put(None),timeout=2)
            except asyncio.TimeoutError:
                await self.gap('停止时音频队列未能排空',None);self.task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            try:await asyncio.wait_for(asyncio.shield(self.task),timeout=settings.model_timeout_seconds+5)
            except asyncio.TimeoutError:
                self.task.cancel();await self.gap('上游收尾超时，末尾音频可能未恢复',None)
                with contextlib.suppress(asyncio.CancelledError):await self.task

    async def audio_iter(self):
        while True:
            remaining=settings.capture_max_seconds-self.captured_before/1000-(time.monotonic()-self.started)
            if remaining<=0:
                await self.fail('application_duration_limit','达到应用单次 105 分钟限制（不是账户消费上限）');return
            try:item=await asyncio.wait_for(self.queue.get(),timeout=min(remaining,15))
            except asyncio.TimeoutError:
                if time.monotonic()-self.started+self.captured_before/1000>=settings.capture_max_seconds:continue
                await self.fail('audio_interrupted','15 秒未收到音频，采集已中断');await self.gap('设备、后台切换或网络中断',None);return
            if item is None:return
            self.queued_bytes=max(0,self.queued_bytes-len(item))
            yield item

    async def partial_translation(self,sentence_id,revision,text,start_ms,end_ms):
        try:
            from app.providers.aliyun import AliyunProvider
            provider=AliyunProvider()
            translated=''
            with SessionLocal() as db:terms=(db.get(User,self.user_id).settings or {}).get('terms',[])
            from app.services.translation_languages import translation_terms,target_name
            language=self.capture_language()
            async for delta in provider.translate_stream(text,terms=translation_terms(terms,language),target_lang=target_name(language)):
                if sentence_id in self.finalized or self.current_revisions.get(sentence_id)!=revision:return
                translated+=delta
                await self.transient('translation.partial',sentence_id=sentence_id,source_revision=revision,translation_revision=revision,
                    start_ms=start_ms,end_ms=end_ms,translation=translated,status='partial')
        except asyncio.CancelledError:raise
        except Exception:
            # Final translation task separately reports failures durably. Partial attempts are optional and bounded.
            return

    def trim_source_cache(self):
        # Unfinished records have their own 200-entry limit; only completed
        # identities are evicted. Database revisions still reject late callbacks.
        while len(self.finalized)>512:
            sid=next(key for key in self.current_revisions if key in self.finalized)
            self.finalized.remove(sid)
            for cache in (self.current_revisions,self.last_results,self.first_seen,self.last_translation):cache.pop(sid,None)
            self.final_results={fp for fp in self.final_results if fp[0]!=sid}
        while len(self.final_results)>2048:self.final_results.pop()

    async def consume(self,event):
        sid=f'{self.stream_id}:{event["sentence_id"]}'
        text=event.get('text','').strip()
        if not text:return
        final=bool(event.get('final'))
        # Receipt order is not a source revision. Late provisional hypotheses
        # cannot reopen a final sentence, and duplicate events must be idempotent.
        if sid in self.finalized and not final:return
        start=self.offset+max(0,int(event.get('start_ms') or 0))
        end=max(start,self.offset+max(0,int(event.get('end_ms') or event.get('start_ms') or 0)))
        result=(text,start,end,final)
        if self.last_results.get(sid)==result:return
        fingerprint=(sid,text,start,end)
        if final and fingerprint in self.final_results:return
        from app.providers.aliyun import ProviderError
        if event.get('stream_id') not in (None,self.stream_id):return
        with SessionLocal() as db:
            session=db.get(Session,self.session_id)
            if not session or session.active_stream_id!=self.stream_id:return
            # Evicted completed identities recover their authority from the DB.
            # This bounds live caches without imposing an extra recording duration limit.
            if sid not in self.current_revisions:
                saved=db.query(SegmentRevision).filter_by(session_id=self.session_id,stream_id=self.stream_id,sentence_id=sid).order_by(SegmentRevision.source_revision.desc()).first()
                if saved:
                    self.current_revisions[sid]=saved.source_revision;self.finalized.add(sid)
                    self.trim_source_cache()
                    if not final:return
            if final and db.query(SegmentRevision.id).filter_by(session_id=self.session_id,stream_id=self.stream_id,
                    sentence_id=sid,text=text,start_ms=start,end_ms=end).first():return
        revision=self.current_revisions.get(sid,0)+1
        stamp=time.monotonic();self.first_seen.setdefault(sid,stamp)
        if final:
            if sid in self.translation_tasks:self.translation_tasks[sid].cancel()
            preview_entry=self.preview.finalize(sid) if self.preview else None
            from app.services.incremental_translation import reuse_candidate
            candidate=reuse_candidate(preview_entry,text,revision,settings) if preview_entry else None
            preview_latency={}
            if preview_entry and preview_entry.first_output_at is not None:
                preview_latency={'preview_first_ms':max(0,int((preview_entry.first_output_at-self.started)*1000)-int(event.get('start_ms') or 0)),
                    'preview_clock':'server_estimate_from_source_audio_start'}
            try:
                with SessionLocal() as db:
                    saved=save_final(db,self.session_id,self.stream_id,sid,revision,text,start,max(start,end),
                        latency={'source_first_ms':max(0,int((self.first_seen[sid]-self.started)*1000)-int(event.get('start_ms') or 0)),
                                 'source_final_ms':max(0,int((stamp-self.started)*1000)-int(event.get('end_ms') or 0)),**preview_latency},preview_candidate=candidate)
                    if saved is None:
                        row=db.get(Session,self.session_id)
                        if not row or row.active_stream_id!=self.stream_id:return
                        existing=db.query(SegmentRevision).filter_by(session_id=self.session_id,stream_id=self.stream_id,sentence_id=sid,source_revision=revision).first()
                        if not existing or (existing.text,existing.start_ms,existing.end_ms)!=(text,start,end):
                            raise ValueError('source_revision_conflict')
            except Exception as exc:
                raise ProviderError('source_storage_failed','正式原文保存失败，未标记定稿成功；请检查数据库。',diagnostics={'exception_type':type(exc).__name__}) from exc
            # Only committed or verified idempotent final results own these markers.
            self.current_revisions[sid]=revision;self.last_results[sid]=result
            self.finalized.add(sid);self.final_results.add(fingerprint);self.unconfirmed.pop(sid,None)
            self.trim_source_cache()
        else:
            if sid not in self.unconfirmed and len(self.unconfirmed)>=200:
                raise ProviderError('source_buffer_full','未定稿原文积压超过保护上限，已停止采集并保留未确认记录。')
            self.current_revisions[sid]=revision;self.last_results[sid]=result
            self.unconfirmed[sid]={'sentence_id':sid,'source_revision':revision,'text':text,
                'start_ms':start,'end_ms':end,'last_received_at':datetime.now(timezone.utc).isoformat()}
            self.translation_tasks={sid:t for sid,t in self.translation_tasks.items() if not t.done()}
            preview=self.ensure_preview()
            fields={}
            if preview:
                state=preview.update(sid,revision,text,start,end)
                fields={'stable_preview':state.stable_preview,'unstable_tail':state.unstable_tail,
                    'hypothesis_revision':state.hypothesis_revision}
            await self.transient('transcript.partial',sentence_id=sid,source_revision=revision,translation_revision=0,start_ms=start,end_ms=max(start,end),text=text,status='partial',
                latency={'source_first_ms':max(0,int((self.first_seen[sid]-self.started)*1000)-int(event.get('start_ms') or 0))},**fields)
            if preview:
                preview.tick()
            elif len(text)>=12 and stamp-self.last_translation.get(sid,0)>=1.2:
                self.last_translation[sid]=stamp
                old=self.translation_tasks.get(sid)
                if old:old.cancel()
                # At most one translation per sentence; at most two active provisional requests overall.
                active=[t for t in self.translation_tasks.values() if not t.done()]
                if len(active)<2:self.translation_tasks[sid]=asyncio.create_task(self.partial_translation(sid,revision,text,start,end))

    async def demo(self):
        for i,(original,translation) in enumerate(DEMO_SENTENCES):
            if self.stopping:break
            sid=f'{self.stream_id}:{i}';start=self.offset+i*7000;end=start+6200
            self.unconfirmed[sid]={'sentence_id':sid,'source_revision':1,'text':original[:len(original)//2],'start_ms':start,'end_ms':end,'last_received_at':datetime.now(timezone.utc).isoformat()}
            await self.transient('transcript.partial',sentence_id=sid,source_revision=1,translation_revision=0,start_ms=start,end_ms=end,text=original[:len(original)//2],status='partial')
            await asyncio.sleep(.65)
            await self.transient('translation.partial',sentence_id=sid,source_revision=1,translation_revision=1,start_ms=start,end_ms=end,translation=translation[:len(translation)//2],status='partial')
            await asyncio.sleep(.65)
            with SessionLocal() as db:
                save_final(db,self.session_id,self.stream_id,sid,2,original,start,end,translation=translation,
                  latency={'source_first_ms':0,'source_final_ms':650,'translation_first_ms':650,'translation_final_ms':1300,'synthetic':True})
            self.unconfirmed.pop(sid,None)
            await asyncio.sleep(1.6)

    async def run(self):
        self.capture_language()
        periodic=asyncio.create_task(self.periodic_summary())
        health=asyncio.create_task(self.report_health())
        preview_timer=asyncio.create_task(self.preview_loop()) if settings.incremental_translation_enabled and self.mode=='real' else None
        try:
            if self.mode=='demo':
                await self.mark_ready()
                await self.demo()
            else:
                from app.providers.aliyun import AliyunProvider
                from app.services.asr_options import asr_vocabulary,asr_language_hints
                with SessionLocal() as db:
                    user=db.get(User,self.user_id)
                    preferences=(user.settings or {}) if user else {}
                    weight=preferences.get('asr_hotword_weight',2)
                    vocabulary=asr_vocabulary(preferences.get('terms',[]),weight)
                    context=str(preferences.get('asr_context','')).strip()[:400]
                    self.asr_enhancement={'hotword_count':len(vocabulary),'weight':weight,'context_chars':len(context)}
                    self.asr_language_mode=preferences.get('asr_language_mode','auto')
                    profile=preferences.get('asr_acoustic_profile','far')
                    self.asr_acoustic_profile=profile if profile in ('far','near') else 'far'
                async for event in AliyunProvider().stream_asr(self.audio_iter(),on_ready=self.mark_ready,metrics=self.asr_metrics,
                    vocabulary=vocabulary,context=context,language_hints=asr_language_hints(self.asr_language_mode),
                    vad_model='near_meeting_16k' if self.asr_acoustic_profile=='near' else 'far_field_meeting_16k'):await self.consume(event)
        except asyncio.CancelledError:raise
        except Exception as exc:
            from app.providers.aliyun import ProviderError
            await self.fail(exc.code if isinstance(exc,ProviderError) else 'upstream_error',
                exc.message if isinstance(exc,ProviderError) else '识别处理异常，已停止采集；请检查服务器诊断日志。',
                {**(exc.diagnostics if isinstance(exc,ProviderError) else {}),'exception_type':type(exc).__name__})
            if self.ready and not self.stopping:await self.gap('上游任务异常结束，未定稿音频无法恢复',None)
        finally:
            periodic.cancel()
            health.cancel()
            await asyncio.gather(periodic,health,return_exceptions=True)
            if preview_timer:
                preview_timer.cancel()
                await asyncio.gather(preview_timer,return_exceptions=True)
            if self.preview:await self.preview.close()
            for t in self.translation_tasks.values():t.cancel()
            await asyncio.gather(*self.translation_tasks.values(),return_exceptions=True)
            self.translation_tasks.clear()
            if self.audio_file:
                saved_audio=False
                try:
                    self.audio_file.close();self.audio_file=None
                    with SessionLocal() as db:
                        asset=db.get(AudioAsset,self.audio_id)
                        key=asset.storage_key if asset else None
                    if key and self.audio_bytes:
                        from app.services.storage import get_storage
                        def store_audio():get_storage().put(key,self.audio_path.read_bytes())
                        await asyncio.to_thread(store_audio)
                    with SessionLocal() as db:
                        asset=db.get(AudioAsset,self.audio_id)
                        if asset:
                            asset.status='ready' if self.audio_bytes else 'empty';asset.duration_ms=self.audio_bytes//32
                            db.commit()
                    saved_audio=True
                except Exception as exc:
                    with SessionLocal() as db:
                        asset=db.get(AudioAsset,self.audio_id)
                        if asset:asset.status='failed';db.commit()
                    await self.fail('audio_storage_failed','音频文件保存失败，已保存的文字仍保留；请检查服务器存储空间。',{'exception_type':type(exc).__name__})
                finally:
                    self.audio_file=None
                    if saved_audio:
                        with contextlib.suppress(OSError):self.audio_path.unlink(missing_ok=True)
            try:
                with SessionLocal() as db:
                    row=db.get(Session,self.session_id)
                    stream=db.get(RecognitionStream,self.stream_id)
                    ended=self.capture_ended or time.monotonic()
                    elapsed=max(0,int((ended-self.started)*1000)) if self.started else 0
                    if stream:stream.status='stopped' if self.ready else 'cancelled';stream.ended_ms=self.offset+elapsed
                    if row and row.active_stream_id==self.stream_id:
                        row.duration_ms=max(row.duration_ms,self.offset+elapsed)
                        for snapshot in self.unconfirmed.values():save_interrupted(db,row.id,self.stream_id,snapshot)
                        row.status='stopped';emit(db,row,'session.state',state='stopped',status='stopped',captured_ms=self.captured_before+elapsed,request_id=self.request_id)
                        if self.ready and latest_segments(db,row.id):enqueue(db,row.user_id,'summarize',f'summary:stop:{self.stream_id}',{'session_id':row.id,'user_id':row.user_id},session_id=row.id)
                        row.active_stream_id=None
                    db.commit()
                self.unconfirmed.clear()
            except Exception as exc:
                logger.error('source_cleanup_failed session_id=%s stream_id=%s exception_type=%s',self.session_id,self.stream_id,type(exc).__name__)
                with contextlib.suppress(Exception):
                    await self.transient('processing.failed',request_id=self.request_id,code='source_storage_failed',
                        message='未确认原文或停止状态保存失败；不能保证刷新后恢复，请检查数据库。',status='failed')


    async def report_health(self):
        while True:
            await asyncio.sleep(2)
            if self.mode=='real' and self.ready and not self.stopping:
                await self.transient('capture.health',status='recording',diagnostics=self.diagnostics())

    async def periodic_summary(self):
        while True:
            await asyncio.sleep(settings.summary_interval_seconds)
            if not self.ready:continue
            with SessionLocal() as db:
                row=db.get(Session,self.session_id)
                if not row or not latest_segments(db,row.id):continue
                enqueue(db,row.user_id,'summarize',f'summary:{self.stream_id}:{int((time.monotonic()-self.started)//settings.summary_interval_seconds)}',{'session_id':row.id,'user_id':row.user_id},session_id=row.id)
                db.commit()


@router.websocket('/ws/sessions/{session_id}')
async def websocket_session(ws:WebSocket,session_id:str,after_seq:int=0):
    origin=ws.headers.get('origin','').rstrip('/')
    if origin not in settings.origins:
        logger.warning('websocket_rejected code=origin_forbidden origin=%r',origin[:256])
        await ws.close(code=4403,reason='Origin forbidden');return
    with SessionLocal() as db:
        user=authenticate_cookie(db,ws.cookies.get(COOKIE_NAME))
        row=db.get(Session,session_id)
        if not user or not row or row.user_id!=user.id:
            code='authentication_required' if not user else 'session_not_accessible'
            logger.warning('websocket_rejected code=%s origin=%r',code,origin[:256])
            await ws.close(code=4401 if not user else 4404,reason=code);return
        user_id=user.id;mode=row.mode
    await ws.accept()
    if session_id in connections:
        old=connections[session_id]
        await old.gap('新连接替代旧连接，未提交音频无法重放',None)
        await old.stop()
        with contextlib.suppress(Exception):await old.ws.close(code=4001,reason='Replaced by new connection')
    capture=LiveCapture(ws,session_id,user_id);capture.mode=mode;connections[session_id]=capture

    async def publisher():
        seq=max(0,after_seq)
        while True:
            with SessionLocal() as db:
                events=db.query(Event).filter(Event.session_id==session_id,Event.event_seq>seq).order_by(Event.event_seq).limit(500).all()
                for event in events:
                    if event.type!=RETIRED_EVENT_TYPE:await capture.send(event.payload)
                    seq=event.event_seq
            await asyncio.sleep(.12)

    sender=asyncio.create_task(publisher())
    with SessionLocal() as db:
        row=db.get(Session,session_id)
        await capture.transient('session.state',state=row.status,status=row.status,recovered=True,message='记录已恢复；麦克风需手动开启')
    try:
        while True:
            message=await ws.receive()
            if message['type']=='websocket.disconnect':break
            if message.get('bytes') is not None:await capture.audio(message['bytes'])
            elif message.get('text'):
                if len(message['text'])>4096:await ws.close(code=1009);break
                try:body=json.loads(message['text'])
                except ValueError:continue
                if body.get('type')=='start':await capture.start(str(body.get('request_id',''))[:100])
                elif body.get('type')=='stop':await capture.stop()
                elif body.get('type')=='capture.gap':await capture.gap(body.get('reason','采集中断'),body.get('duration_ms'))
                elif body.get('type')=='ping':await capture.transient('connection.pong',queue_size=capture.queue.qsize())
    except (WebSocketDisconnect,RuntimeError):pass
    finally:
        sender.cancel()
        if capture.task and not capture.task.done():
            await capture.gap('连接断开，未发送的音频无法恢复',None)
            await capture.stop()
        if connections.get(session_id) is capture:connections.pop(session_id,None)
