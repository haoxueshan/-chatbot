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
from anyio import CancelScope
from app.api.auth import authenticate_cookie, COOKIE_NAME
from app.config import settings
from app.db import SessionLocal
from app.providers.transport import blocking_call, PCM_BYTES_PER_MS, PCM_QUEUE_BYTES
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
        self.queue=asyncio.Queue(maxsize=PCM_QUEUE_BYTES//2)
        self.stream_id=None;self.mode=None;self.offset=0;self.started=0;self.task=None
        self.stopping=False;self.current_revisions={};self.finalized=set();self.last_results={};self.final_results=set();self.translation_tasks={}
        self.last_translation={};self.first_seen={};self.audio_file=None;self.audio_path=None;self.audio_id=None;self.audio_bytes=0
        self.legacy_inputs={}
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
        self.audio_queue_peak=0
        self.delivery=None;self.delivery_pending={};self.delivery_wakeup=asyncio.Event();self.delivery_failed=None
        self.archive_queue=deque();self.archive_bytes=0
        self.preview_terms=None
        self.dispatch_started=asyncio.Event()
        self.database_lock=asyncio.Lock()
        self.queued_frames=0

    async def write_database(self,function):
        # Preserve per-capture transaction ordering, including SQLite, while
        # the actual Session is created and closed entirely in the worker.
        async with self.database_lock:return await blocking_call(function)

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
            terms=self.preview_terms
            if terms is None:
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
            elif not self.stopping and not settings.incremental_translation_enabled:self.tick_legacy()

    async def send(self,payload):
        async def locked_send():
            async with self.send_lock:await self.ws.send_json(payload)
        # Include lock acquisition in the deadline, not only the socket write.
        await asyncio.wait_for(locked_send(),timeout=10)

    async def transient(self,event_type,**fields):
        payload={'type':event_type,'event_id':uid(),'event_seq':0,'session_id':self.session_id,
          'stream_id':self.stream_id,'mode':self.mode,'target_language':self.capture_language(),**fields}
        if self.delivery is not None and event_type in ('transcript.partial','translation.partial','capture.health'):
            # Full replaceable UI snapshots only. Source revisions/unconfirmed
            # recovery are already maintained independently by consume().
            key=(event_type,fields.get('sentence_id'))
            if key not in self.delivery_pending and len(self.delivery_pending)>=401:
                from app.providers.aliyun import ProviderError
                self.delivery_failed=ProviderError('subtitle_backlog','字幕接收积压，已停止采集；原文仍按版本保存。')
            elif not self.delivery_failed:self.delivery_pending[key]=payload
            self.delivery_wakeup.set()
        else:await self.send(payload)

    async def deliver_previews(self):
        from app.providers.aliyun import ProviderError
        try:
            while True:
                await self.delivery_wakeup.wait()
                if self.delivery_failed:raise self.delivery_failed
                while self.delivery_pending:
                    key=next(iter(self.delivery_pending))
                    await self.send(self.delivery_pending.pop(key))
                    if self.delivery_failed:raise self.delivery_failed
                self.delivery_wakeup.clear()
        except asyncio.CancelledError:raise
        except Exception as exc:
            self.delivery_failed=exc if isinstance(exc,ProviderError) else ProviderError('subtitle_delivery_failed','字幕连接发送失败，已停止采集；已保存原文保留。')
            raise self.delivery_failed from exc

    def signal_stop(self):
        if not self.stopping:
            self.stopping=True;self.capture_ended=time.monotonic()
            # If full, audio_iter sees stopping after the last queued frame.
            if not self.queue.full():self.queue.put_nowait(None)

    async def maintain_capture(self):
        while True:
            await asyncio.sleep(1)
            if not self.ready or self.stopping:continue
            def check():
                with SessionLocal() as db:
                    row=db.get(Session,self.session_id)
                    allowed=bool(row and row.user_id==self.user_id and row.active_stream_id==self.stream_id and row.status=='recording')
                    pending=db.query(ProcessingTask).filter(ProcessingTask.session_id==self.session_id,ProcessingTask.status.in_(['pending','retry','running'])).count()
                    return allowed,pending
            allowed,pending=await blocking_call(check)
            if self.stopping:continue
            from app.providers.aliyun import ProviderError
            if not allowed:raise ProviderError('capture_state_changed','会话已停止或采集权限状态发生变化。')
            if pending>=200:raise ProviderError('task_backlog','后台待处理任务达到200项，已停止采集。')

    async def archive_audio(self):
        while True:
            await asyncio.sleep(.1)
            await self.flush_archive()

    async def flush_archive(self):
        if not self.archive_queue:return
        # One serialized disk batch, at most 2 seconds. Bytes in flight still
        # count against the archive budget until write completion.
        batch=b''.join(self.archive_queue);self.archive_queue.clear()
        written=False
        def write():
            nonlocal written
            self.audio_file.writeframesraw(batch);written=True
        try:await blocking_call(write)
        except Exception as exc:
            from app.providers.aliyun import ProviderError
            raise ProviderError('audio_storage_failed','保留音频写入失败，不能保证音频文件完整。') from exc
        finally:
            if written:self.archive_bytes-=len(batch);self.audio_bytes+=len(batch)

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
            self.queue=asyncio.Queue(maxsize=PCM_QUEUE_BYTES//2)
            self.queued_bytes=0;self.queued_frames=0;self.audio_queue_peak=0
            self.archive_queue.clear();self.archive_bytes=0
            self.delivery_pending.clear();self.delivery_failed=None;self.preview_terms=None
            self.current_revisions={};self.finalized=set();self.last_results={};self.final_results=set();self.first_seen={};self.last_translation={}
            self.legacy_inputs.clear()
            self.audio_id=None;self.audio_bytes=0
            stream=RecognitionStream(id=self.stream_id,session_id=row.id,status='preparing',offset_ms=self.offset,mode=self.mode)
            db.add(stream);db.flush();row.active_stream_id=self.stream_id;row.status='preparing'
            emit(db,row,'session.state',state='preparing',status='preparing',request_id=self.request_id,
                 message='正在准备识别服务，请稍候再说话')
            db.commit()
        self.dispatch_started.clear()
        self.task=asyncio.create_task(self.run())
        # Wait only for local dispatch, never for the paid upstream handshake.
        await self.dispatch_started.wait()

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
        if not data or len(data)>32000 or len(data)%2:
            await self.fail('audio_format','音频必须为 16 kHz 单声道 PCM16LE，单帧不超过一秒');await self.stop();return
        if self.queue.full() or self.queued_bytes+len(data)>PCM_QUEUE_BYTES:
            await self.gap('音频队列已满',None);await self.fail('audio_backlog','音频转发积压超过 2 秒，已停止采集；请检查服务器到阿里云的网络后重新开始。');await self.stop();return
        if self.audio_file:
            if self.archive_bytes+len(data)>PCM_QUEUE_BYTES:
                await self.fail('audio_storage_backlog','保留音频写入积压超过2秒，已停止采集。')
                await self.gap('音频保存队列已满，当前帧未接收',len(data)/PCM_BYTES_PER_MS)
                await self.stop();return
            self.archive_queue.append(data);self.archive_bytes+=len(data)
        self.queue.put_nowait(data);self.queued_bytes+=len(data);self.queued_frames+=1
        self.audio_queue_peak=max(self.audio_queue_peak,self.queued_bytes)
        self.received_audio_ms+=len(data)/PCM_BYTES_PER_MS;self.last_audio_at=time.monotonic()
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
        return {'queue_frames':self.queued_frames,'queued_audio_ms':self.queued_bytes/PCM_BYTES_PER_MS,
                'audio_queue_peak_ms':self.audio_queue_peak/PCM_BYTES_PER_MS,
                'archive_queue_ms':self.archive_bytes/PCM_BYTES_PER_MS,
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
        def persist():
            with SessionLocal() as db:
                row=db.get(Session,self.session_id)
                if not row:return
                payload=emit(db,row,'capture.gap',stream_id=self.stream_id,status='gap',start_ms=self.offset+int((time.monotonic()-self.started)*1000) if self.started else row.duration_ms,
                             duration_ms=duration_ms,message=str(reason)[:500])
                if self.audio_id:
                    asset=db.get(AudioAsset,self.audio_id)
                    if asset:asset.gaps=[*(asset.gaps or []),payload]
                db.commit()
        await self.write_database(persist)

    async def fail(self,code,message,diagnostics=None):
        if self.failure_reported:return
        self.failure_reported=True
        details={**self.diagnostics(),**(diagnostics or {})}
        logger.warning('capture_failed session_id=%s stream_id=%s code=%s diagnostics=%s',self.session_id,self.stream_id,code,details)
        def persist():
            with SessionLocal() as db:
                row=db.get(Session,self.session_id)
                if row:
                    emit(db,row,'processing.failed',stream_id=self.stream_id,request_id=self.request_id,code=str(code),message=str(message)[:500],status='failed',diagnostics=details)
                    db.commit()
        await self.write_database(persist)

    async def stop(self):
        first=not self.stopping
        self.signal_stop()
        if not self.task or self.task.done() or self.task is asyncio.current_task():return
        if first:
            if self.mode=='demo' or not self.ready:
                self.task.cancel()
                await asyncio.gather(self.task,return_exceptions=True)
                return
            else:
                def processing():
                    with SessionLocal() as db:
                        row=db.get(Session,self.session_id)
                        if row and row.active_stream_id==self.stream_id:
                            row.status='processing';emit(db,row,'session.state',state='processing',status='processing',request_id=self.request_id);db.commit()
                await self.write_database(processing)
        try:await asyncio.wait_for(asyncio.shield(self.task),timeout=settings.model_timeout_seconds+5)
        except asyncio.TimeoutError:
            await self.fail('upstream_drain_timeout','上游收尾超时，末尾音频可能未识别。')
            self.task.cancel()
            await self.gap('上游收尾超时，末尾音频可能未恢复',None)
            await asyncio.gather(self.task,return_exceptions=True)
        except asyncio.CancelledError:
            if asyncio.current_task().cancelling():
                self.task.cancel();await asyncio.gather(self.task,return_exceptions=True);raise

    async def audio_iter(self):
        while True:
            if self.stopping and self.queue.empty():return
            remaining=settings.capture_max_seconds-self.captured_before/1000-(time.monotonic()-self.started)
            if remaining<=0 and not self.stopping:
                self.signal_stop()
                await self.fail('application_duration_limit','达到应用单次 105 分钟限制（不是账户消费上限）')
                continue # Stop admission; still drain every previously accepted frame.
            try:item=self.queue.get_nowait() if not self.queue.empty() else await asyncio.wait_for(self.queue.get(),timeout=min(remaining,15))
            except asyncio.TimeoutError:
                if time.monotonic()-self.started+self.captured_before/1000>=settings.capture_max_seconds:continue
                await self.fail('audio_interrupted','15 秒未收到音频，采集已中断');await self.gap('设备、后台切换或网络中断',None);return
            if item is None:return
            self.queued_bytes=max(0,self.queued_bytes-len(item))
            self.queued_frames=max(0,self.queued_frames-1)
            yield item

    def update_legacy(self,sid,revision,text,start,end):
        from app.services.incremental_translation import Sentence
        stamp=time.monotonic()
        entry=self.legacy_inputs.get(sid)
        if entry is None:
            entry=Sentence(text,revision,start,end,stamp,stamp);self.legacy_inputs[sid]=entry
        elif entry.requested_text and not text.startswith(entry.requested_text):
            entry.request_id+=1;entry.requested_text=''
            task=self.translation_tasks.get(sid)
            if task and not task.done():task.cancel()
        entry.text=text;entry.revision=revision;entry.start_ms=start;entry.end_ms=end;entry.updated_at=stamp
        self.tick_legacy()

    def tick_legacy(self):
        import hashlib
        from app.services.incremental_translation import preview_budget,worth_refresh
        self.translation_tasks={sid:t for sid,t in self.translation_tasks.items() if not t.done()}
        stamp=time.monotonic()
        for sid,entry in self.legacy_inputs.items():
            if self.stopping or sid in self.finalized:continue
            if stamp-entry.updated_at>settings.preview_ttl_seconds:continue
            text=entry.text
            if not text or len(text)>settings.preview_max_chars or len(entry.attempted)>=64:continue
            digest=hashlib.sha256(text.encode()).hexdigest()
            if digest in entry.attempted:continue
            if sid in self.translation_tasks or len(self.translation_tasks)>=2:continue
            if stamp-entry.last_request_at<settings.preview_interval_seconds:continue
            if not entry.requested_text and len(text)<12 and stamp-entry.first_at<settings.preview_max_wait_seconds:continue
            if entry.requested_text and not worth_refresh(entry.requested_text,text,stamp-entry.last_request_at,settings):continue
            if not preview_budget.acquire(stamp,2,settings.preview_calls_per_minute):continue
            entry.request_id+=1;entry.last_request_at=stamp;entry.requested_text=text;entry.attempted.add(digest)
            self.last_translation[sid]=stamp
            task=asyncio.create_task(self.partial_translation(sid,entry.revision,text,entry.start_ms,entry.end_ms,entry,entry.request_id))
            self.translation_tasks[sid]=task
            task.add_done_callback(lambda _:preview_budget.release())

    async def partial_translation(self,sentence_id,revision,text,start_ms,end_ms,entry=None,request_id=None):
        try:
            from app.providers.aliyun import AliyunProvider
            provider=AliyunProvider()
            translated=''
            def load_terms():
                with SessionLocal() as db:return (db.get(User,self.user_id).settings or {}).get('terms',[])
            terms=await blocking_call(load_terms)
            from app.services.translation_languages import translation_terms,target_name
            language=self.capture_language()
            from app.services.incremental_translation import translation_spec,spec_digest
            digest=spec_digest(translation_spec(settings,terms,language))
            last_emit=float('-inf');last_text=''
            def valid():
                if sentence_id in self.finalized:return False
                return (self.legacy_inputs.get(sentence_id) is entry and entry.request_id==request_id and entry.text.startswith(text)) if entry else self.current_revisions.get(sentence_id)==revision
            async def publish(complete=False):
                nonlocal last_emit,last_text
                if not valid() or not translated or (translated==last_text and not complete):return
                current=entry.revision if entry else revision
                if entry and entry.first_output_at is None:entry.first_output_at=time.monotonic()
                await self.transient('translation.partial',sentence_id=sentence_id,source_revision=current,translation_revision=current,
                    start_ms=entry.start_ms if entry else start_ms,end_ms=entry.end_ms if entry else end_ms,translation=translated,status='partial',
                    **({'preview_source_text':text,'preview_request_id':request_id,'preview_complete':complete} if entry else {}))
                last_emit=time.monotonic();last_text=translated
            async for delta in provider.translate_stream(text,terms=translation_terms(terms,language),target_lang=target_name(language),require_complete=True):
                if not valid():return
                if not delta:continue
                translated+=delta
                if len(translated)>settings.preview_max_chars*4:return
                if time.monotonic()-last_emit>=settings.translation_emit_seconds:await publish()
            if entry and valid() and translated.strip():
                entry.completed={'text':text,'translation':translated,'spec_digest':digest,'stream_id':self.stream_id,
                    'sentence_id':sentence_id,'completed_at':time.monotonic(),'complete':True}
            await publish(complete=True)
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
        def lookup():
            with SessionLocal() as db:
                session=db.get(Session,self.session_id)
                if not session or session.active_stream_id!=self.stream_id:return False,None,False
                saved=None
                if sid not in self.current_revisions:
                    saved=db.query(SegmentRevision).filter_by(session_id=self.session_id,stream_id=self.stream_id,sentence_id=sid).order_by(SegmentRevision.source_revision.desc()).first()
                duplicate=final and db.query(SegmentRevision.id).filter_by(session_id=self.session_id,stream_id=self.stream_id,sentence_id=sid,text=text,start_ms=start,end_ms=end).first() is not None
                return True,saved.source_revision if saved else None,duplicate
        allowed,saved_revision,duplicate=await blocking_call(lookup)
        if not allowed:return
        if saved_revision is not None:
            self.current_revisions[sid]=saved_revision;self.finalized.add(sid);self.trim_source_cache()
            if not final:return
        if duplicate:return
        revision=self.current_revisions.get(sid,0)+1
        stamp=time.monotonic();self.first_seen.setdefault(sid,stamp)
        if final:
            if sid in self.translation_tasks:self.translation_tasks[sid].cancel()
            legacy_entry=self.legacy_inputs.pop(sid,None)
            preview_entry=self.preview.finalize(sid) if self.preview else legacy_entry
            from app.services.incremental_translation import reuse_candidate
            candidate=reuse_candidate(preview_entry,text,revision,settings) if preview_entry else None
            preview_latency={}
            if preview_entry and preview_entry.first_output_at is not None:
                preview_latency={'preview_first_ms':max(0,int((preview_entry.first_output_at-self.started)*1000)-int(event.get('start_ms') or 0)),
                    'preview_clock':'server_estimate_from_source_audio_start'}
            try:
                def persist_final():
                    with SessionLocal() as db:
                        saved=save_final(db,self.session_id,self.stream_id,sid,revision,text,start,max(start,end),
                            latency={'source_first_ms':max(0,int((self.first_seen[sid]-self.started)*1000)-int(event.get('start_ms') or 0)),
                                     'source_final_ms':max(0,int((stamp-self.started)*1000)-int(event.get('end_ms') or 0)),**preview_latency},preview_candidate=candidate)
                        if saved is None:
                            row=db.get(Session,self.session_id)
                            if not row or row.active_stream_id!=self.stream_id:return False
                            existing=db.query(SegmentRevision).filter_by(session_id=self.session_id,stream_id=self.stream_id,sentence_id=sid,source_revision=revision).first()
                            if not existing or (existing.text,existing.start_ms,existing.end_ms)!=(text,start,end):
                                raise ValueError('source_revision_conflict')
                    return True
                if not await self.write_database(persist_final):return
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
            else:self.update_legacy(sid,revision,text,start,end)

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
        preview_timer=asyncio.create_task(self.preview_loop()) if self.mode=='real' else None
        maintenance=asyncio.create_task(self.maintain_capture()) if self.mode=='real' else None
        archive=asyncio.create_task(self.archive_audio()) if self.mode=='real' else None
        self.delivery=asyncio.create_task(self.deliver_previews()) if self.mode=='real' else None
        processing=None
        try:
            if self.mode=='demo':
                self.dispatch_started.set()
                await self.mark_ready()
                await self.demo()
            else:
                from app.providers.aliyun import AliyunProvider
                from app.services.asr_options import asr_vocabulary,asr_language_hints
                with SessionLocal() as db:
                    user=db.get(User,self.user_id)
                    preferences=(user.settings or {}) if user else {}
                    self.preview_terms=preferences.get('terms',[])
                    weight=preferences.get('asr_hotword_weight',2)
                    vocabulary=asr_vocabulary(preferences.get('terms',[]),weight)
                    context=str(preferences.get('asr_context','')).strip()[:400]
                    self.asr_enhancement={'hotword_count':len(vocabulary),'weight':weight,'context_chars':len(context)}
                    self.asr_language_mode=preferences.get('asr_language_mode','auto')
                    profile=preferences.get('asr_acoustic_profile','far')
                    self.asr_acoustic_profile=profile if profile in ('far','near') else 'far'
                async def recognize():
                    self.dispatch_started.set()
                    stream=AliyunProvider().stream_asr(self.audio_iter(),on_ready=self.mark_ready,metrics=self.asr_metrics,
                        vocabulary=vocabulary,context=context,language_hints=asr_language_hints(self.asr_language_mode),
                        vad_model='near_meeting_16k' if self.asr_acoustic_profile=='near' else 'far_field_meeting_16k')
                    async with contextlib.aclosing(stream):
                        async for event in stream:await self.consume(event)
                processing=asyncio.create_task(recognize())
                workers=[t for t in (periodic,health,preview_timer,maintenance,archive,self.delivery) if t]
                done,_=await asyncio.wait([processing,*workers],return_when=asyncio.FIRST_COMPLETED)
                failed=next((t for t in workers if t in done),None)
                if failed:
                    from app.providers.aliyun import ProviderError
                    error=failed.exception() or ProviderError('capture_worker_failed','采集维护任务意外结束。')
                    # Stop admission, but let accepted PCM and official ASR finals
                    # drain even when browser preview delivery/storage failed.
                    self.signal_stop()
                    await self.fail(error.code if isinstance(error,ProviderError) else 'capture_worker_failed',
                                    error.message if isinstance(error,ProviderError) else '采集维护失败，已停止采集。')
                    await self.gap('采集维护或字幕发送失败，已停止接收新音频',None)
                    try:await asyncio.wait_for(asyncio.shield(processing),settings.model_timeout_seconds+5)
                    except Exception:processing.cancel();await asyncio.gather(processing,return_exceptions=True)
                    raise error
                await processing
        except asyncio.CancelledError:raise
        except Exception as exc:
            from app.providers.aliyun import ProviderError
            await self.fail(exc.code if isinstance(exc,ProviderError) else 'upstream_error',
                exc.message if isinstance(exc,ProviderError) else '识别处理异常，已停止采集；请检查服务器诊断日志。',
                {**(exc.diagnostics if isinstance(exc,ProviderError) else {}),'exception_type':type(exc).__name__})
            if self.ready and not self.stopping:await self.gap('上游任务异常结束，未定稿音频无法恢复',None)
        finally:
            self.dispatch_started.set()
            self.signal_stop()
            children=[t for t in (processing,maintenance,archive,self.delivery) if t]
            for child in children:child.cancel()
            await asyncio.gather(*children,return_exceptions=True)
            self.delivery=None;self.delivery_pending.clear();self.delivery_wakeup.clear()
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
            self.legacy_inputs.clear()
            if self.audio_file:
                saved_audio=False
                try:
                    if archive and archive.done() and not archive.cancelled() and archive.exception():raise archive.exception()
                    await self.flush_archive()
                    await blocking_call(self.audio_file.close);self.audio_file=None
                    with SessionLocal() as db:
                        asset=db.get(AudioAsset,self.audio_id)
                        key=asset.storage_key if asset else None
                    if key and self.audio_bytes:
                        from app.services.storage import get_storage
                        def store_audio():get_storage().put(key,self.audio_path.read_bytes())
                        await blocking_call(store_audio)
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
                    if self.audio_file:
                        try:await blocking_call(self.audio_file.close)
                        except Exception as exc:
                            logger.error('audio_close_failed session_id=%s stream_id=%s exception_type=%s',self.session_id,self.stream_id,type(exc).__name__)
                            await self.fail('audio_storage_failed','音频文件关闭失败，保留音频可能不完整。')
                    self.audio_file=None
                    if saved_audio:
                        with contextlib.suppress(OSError):self.audio_path.unlink(missing_ok=True)
            try:
                def finalize():
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
                await self.write_database(finalize)
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
            def summarize():
                with SessionLocal() as db:
                    row=db.get(Session,self.session_id)
                    if not row or not latest_segments(db,row.id):return
                    enqueue(db,row.user_id,'summarize',f'summary:{self.stream_id}:{int((time.monotonic()-self.started)//settings.summary_interval_seconds)}',{'session_id':row.id,'user_id':row.user_id},session_id=row.id)
                    db.commit()
            await self.write_database(summarize)


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
            def read_events():
                with SessionLocal() as db:
                    events=db.query(Event).filter(Event.session_id==session_id,Event.event_seq>seq).order_by(Event.event_seq).limit(500).all()
                    return [(e.event_seq,e.type,e.payload) for e in events]
            for number,event_type,payload in await blocking_call(read_events):
                if event_type!=RETIRED_EVENT_TYPE:await capture.send(payload)
                seq=number
            await asyncio.sleep(.12)

    sender=asyncio.create_task(publisher())
    try:
        with SessionLocal() as db:
            status=db.get(Session,session_id).status
        await capture.transient('session.state',state=status,status=status,recovered=True,message='记录已恢复；麦克风需手动开启')
        while True:
            receiving=asyncio.create_task(ws.receive())
            try:
                done,_=await asyncio.wait((receiving,sender),return_when=asyncio.FIRST_COMPLETED)
                if sender in done:
                    await capture.fail('subtitle_delivery_failed','字幕推送连接失败，采集已停止；已保存原文保留。')
                    break
                message=receiving.result()
            finally:
                receiving.cancel();await asyncio.gather(receiving,return_exceptions=True)
            if message['type']=='websocket.disconnect':break
            if message.get('bytes') is not None:await capture.audio(message['bytes'])
            elif message.get('text'):
                if len(message['text'])>4096:await ws.close(code=1009);break
                try:body=json.loads(message['text'])
                except ValueError:continue
                if body.get('type')=='start':await capture.start(str(body.get('request_id',''))[:100])
                elif body.get('type')=='stop':await capture.stop()
                elif body.get('type')=='capture.gap':await capture.gap(body.get('reason','采集中断'),body.get('duration_ms'))
                elif body.get('type')=='ping':await capture.transient('connection.pong',queue_size=capture.queued_frames)
    except (WebSocketDisconnect,RuntimeError):pass
    except asyncio.CancelledError:
        logger.debug('capture_connection_cancelled session_id=%s stream_id=%s',session_id,capture.stream_id)
    finally:
        with CancelScope(shield=True):
            try:
                sender.cancel()
                await asyncio.gather(sender,return_exceptions=True)
                if capture.task and not capture.task.done():
                    try:await capture.gap('连接断开，未发送的音频无法恢复',None)
                    finally:await capture.stop()
            finally:
                if connections.get(session_id) is capture:connections.pop(session_id,None)
                with contextlib.suppress(WebSocketDisconnect,RuntimeError,TimeoutError):await asyncio.wait_for(ws.close(),timeout=2)
