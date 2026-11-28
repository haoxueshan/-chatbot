"""Soniox STT v6: official token timestamps and endpoint markers, no MT."""
import asyncio
import hashlib
import json
import math
import time
from collections import deque
from websockets.asyncio.client import connect as WebSocketConnect
from websockets.exceptions import ConnectionClosed, InvalidStatus
from app.providers.errors import ProviderError, classify_status
from app.providers.transport import tls_context, ASRResultQueue

ENDPOINT='wss://stt-rt.soniox.com/transcribe-websocket'


class connect(WebSocketConnect):
    def process_redirect(self,exc):
        # A fixed endpoint must not forward the bearer credential to another host.
        return exc


def soniox_error(status,code=''):
    category,retryable=classify_status(status,code)
    messages={
        'authentication_failed':'Soniox 身份认证失败，请检查服务器 SONIOX_API_KEY。',
        'quota_exhausted':'Soniox 账户额度或余额不足，请检查供应商控制台。',
        'rate_limited':'Soniox 请求限流，请稍后手动重试。',
        'model_permission':'当前 Soniox API Key 无权访问该模型。',
        'model_unavailable':'Soniox 模型不存在或当前账号无权访问。',
    }
    return ProviderError(category,messages.get(category,'Soniox 请求失败，请检查服务端诊断代码。'),retryable)


def check_error(data):
    if data.get('error_code'):
        if data.get('error_type')=='model_not_available':
            raise ProviderError('model_unavailable','Soniox 模型不存在或当前账号无权访问。')
        raise soniox_error(int(data['error_code']),str(data.get('error_type','')))


class TokenMapper:
    """Final tokens append once; provisional tokens replace only the open tail.

    IDs are adapter-local utterance counters, namespaced by ClassBridge stream_id.
    Only Soniox <end> / <fin> / finished confirms a sentence. Its range is the
    envelope of provider token timestamps, never wall-clock arrival time.
    """
    def __init__(self):
        self.index=1;self.confirmed=[];self.pending=[];self.closed_end=-1
        self.messages=deque(maxlen=64);self.last_snapshot=None
        self.final_tokens=deque(maxlen=2048)

    def snapshot(self,final=False):
        tokens=self.confirmed if final else self.confirmed+self.pending
        text=''.join(t['text'] for t in tokens).strip()
        if not text:return None
        timed=[t for t in tokens if t.get('start_ms') is not None and t.get('end_ms') is not None]
        if not timed:raise ProviderError('asr_timestamp_missing','Soniox 未返回可用音频时间戳，未生成伪造时间。')
        result={'sentence_id':str(self.index),'text':text,'start_ms':min(t['start_ms'] for t in timed),
                'end_ms':max(t['end_ms'] for t in timed),'final':final,'words':timed}
        if result==self.last_snapshot:return None
        self.last_snapshot=result
        return result

    def close_sentence(self):
        if self.pending:raise ProviderError('asr_incomplete','Soniox 收尾仍有未确认文本，未冒充正式字幕。')
        result=self.snapshot(True)
        if result:
            self.closed_end=max(self.closed_end,result['end_ms']);self.index+=1
        self.confirmed=[];self.last_snapshot=None
        return result

    def update(self,data):
        check_error(data)
        signature=hashlib.sha256(json.dumps(data,sort_keys=True).encode()).digest()
        if signature in self.messages:return []
        self.messages.append(signature)
        output=[]
        if 'tokens' in data:
            previous_pending=self.pending
            prior_final_tokens=set(self.final_tokens)
            if not data.get('finished') or data['tokens']:self.pending=[]
            stale=False;fresh=False
            for token in data['tokens']:
                if token.get('translation_status')=='translation':
                    raise ProviderError('protocol_error','ASR 链路不接受供应商译文作为原文。')
                text=token.get('text','')
                if text in ('<end>','<fin>'):
                    if not token.get('is_final'):raise ProviderError('protocol_error','Soniox 返回未确认的结束标记。')
                    if stale and not fresh:continue
                    if previous_pending and not fresh:
                        raise ProviderError('asr_incomplete','Soniox 结束标记前的临时文本未确认，未冒充正式字幕。')
                    event=self.close_sentence()
                    if event:output.append(event)
                    continue
                if not text:continue
                item={'text':text}
                for field in ('start_ms','end_ms'):
                    if token.get(field) is not None:
                        value=token[field]
                        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<0:
                            raise ProviderError('protocol_error','Soniox 音频时间戳无效。')
                        item[field]=int(value)
                if 'start_ms' in item and 'end_ms' in item:
                    if item['end_ms']<item['start_ms']:raise ProviderError('protocol_error','Soniox 时间戳范围无效。')
                    if item['end_ms']<=self.closed_end:
                        stale=True;continue # late prior utterance cannot recreate a final
                key=(item.get('start_ms'),item.get('end_ms'),text)
                if token.get('is_final') and key[0] is not None:
                    if key in prior_final_tokens:
                        stale=True;continue
                    self.final_tokens.append(key)
                fresh=True
                (self.confirmed if token.get('is_final') else self.pending).append(item)
            if stale and not fresh:self.pending=previous_pending
            if sum(len(t['text']) for t in self.confirmed+self.pending)>65536:
                raise ProviderError('asr_result_backlog','单个未结束识别片段超过应用限制，已停止采集。')
        if data.get('finished'):
            event=self.close_sentence()
        else:event=self.snapshot()
        if event:output.append(event)
        return output


class SonioxASRAdapter:
    supports_final_revisions = False
    def __init__(self,config):self.config=config
    def ensure_configured(self):
        if not getattr(self.config,'soniox_api_key',''):
            raise ProviderError('missing_api_key','服务器未配置 SONIOX_API_KEY；不会使用模拟字幕替代。')

    async def stream_asr(self,audio,*,vocabulary=None,context=None,language_hints=None,vad_model=None,on_ready=None,metrics=None):
        self.ensure_configured()
        timeout=float(getattr(self.config,'model_timeout_seconds',30))
        event_timeout=float(getattr(self.config,'asr_event_timeout_seconds',None) or timeout)
        finish_timeout=float(getattr(self.config,'asr_finish_timeout_seconds',None) or timeout)
        send_timeout=float(getattr(self.config,'asr_send_timeout_seconds',5))
        options=getattr(self.config,'asr_options',{})
        if getattr(self.config,'asr_effective_resolved',False):
            options={key:value for key,value in options.items() if key not in ('context','terms')}
        hints=getattr(self.config,'asr_language_hints',None)
        if getattr(self.config,'asr_effective_resolved',False):hints=None
        hints=language_hints if hints is None else hints
        context_data={'text':options.get('context',context) or '',
            'terms':list(dict.fromkeys([*(vocabulary or {}),*options.get('terms',[])]))[:200]}
        config={'model':getattr(self.config,'asr_model','stt-rt-v6'),'audio_format':'pcm_s16le',
            'sample_rate':16000,'num_channels':1,'enable_endpoint_detection':True,
            'max_endpoint_delay_ms':options.get('max_endpoint_delay_ms',2000),
            'language_hints_strict':options.get('language_hints_strict',False),'context':context_data}
        if hints:config['language_hints']=hints
        metrics=metrics if metrics is not None else {}
        metrics.update(sent_audio_ms=0,send_wait_ms=0)
        try:
            async with connect(ENDPOINT,additional_headers={'Authorization':f'Bearer {self.config.soniox_api_key}'},
                    ssl=await tls_context(),open_timeout=timeout,close_timeout=5,max_size=2**20,max_queue=32,
                    ping_interval=20) as ws:
                await asyncio.wait_for(ws.send(json.dumps(config)),timeout)
                # Official ping after the start request is answered once the stream starts.
                await asyncio.wait_for(ws.send(json.dumps({'type':'ping','id':0})),send_timeout)
                async with asyncio.timeout(timeout):
                    while True:
                        first=json.loads(await ws.recv());check_error(first)
                        if first.get('type')=='pong' and first.get('id')==0:break
                        if first.get('tokens') or first.get('finished'):raise ProviderError('protocol_error','Soniox 在发送音频前返回了异常识别数据。')
                metrics['last_event_monotonic']=time.monotonic()
                if on_ready:await on_ready()
                mapper=TokenMapper();queue=ASRResultQueue(metrics);lock=asyncio.Lock()
                finish_at=None;finishing=asyncio.get_running_loop().create_future();receiver=None;pending=None
                async def send(value):
                    async with lock:await ws.send(value)
                async def send_audio():
                    nonlocal finish_at
                    async for frame in audio:
                        if not frame or len(frame)%2 or len(frame)>32000:raise ProviderError('format_error','需要 PCM16LE 单声道 16kHz 音频。')
                        stamp=time.monotonic()
                        metrics.update(upstream_inflight_pcm_bytes=len(frame),send_started_monotonic=stamp)
                        try:await asyncio.wait_for(send(frame),send_timeout)
                        except BaseException as exc:
                            metrics['uncertain_delivery_pcm_bytes']=metrics.get('uncertain_delivery_pcm_bytes',0)+len(frame)
                            if isinstance(exc,TimeoutError):raise ProviderError('upstream_send_timeout','向 Soniox 发送音频超时。',diagnostics={'timeout_phase':'audio_send'}) from exc
                            raise
                        else:
                            metrics['last_send_monotonic']=time.monotonic()
                            metrics['sent_audio_ms']+=len(frame)/32
                            metrics['upstream_sent_pcm_bytes']=metrics.get('upstream_sent_pcm_bytes',0)+len(frame)
                        finally:
                            metrics['send_wait_ms']=int((time.monotonic()-stamp)*1000)
                            metrics['upstream_inflight_pcm_bytes']=0;metrics.pop('send_started_monotonic',None)
                        await asyncio.sleep(0)
                    finish_at=time.monotonic();finishing.set_result(None)
                    await asyncio.wait_for(send(''),send_timeout) # Empty TEXT ends input, not empty bytes.
                async def heartbeat():
                    index=1
                    while not finishing.done():
                        await asyncio.sleep(min(10,event_timeout/3))
                        if finishing.done():return
                        await asyncio.wait_for(send(json.dumps({'type':'ping','id':index})),send_timeout)
                        index+=1
                def remaining():
                    left=(finish_at+finish_timeout if finish_at is not None else metrics['last_event_monotonic']+event_timeout)-time.monotonic()
                    if left<=0:raise ProviderError('asr_finish_timeout' if finish_at is not None else 'asr_event_timeout','Soniox 识别或收尾响应超时，已保存字幕保留。')
                    return left
                async def receive_results():
                    nonlocal receiver
                    while True:
                        remaining();receiver=asyncio.create_task(ws.recv())
                        while not receiver.done():
                            for task in (sender,pinger):
                                if task.done():task.result()
                            waiting={receiver,*[t for t in (sender,pinger,finishing) if not t.done()]}
                            done,_=await asyncio.wait(waiting,timeout=remaining(),return_when=asyncio.FIRST_COMPLETED)
                            for task in (sender,pinger):
                                if task in done:task.result()
                            if not done:remaining()
                        data=json.loads(receiver.result());receiver=None;check_error(data)
                        metrics['last_event_monotonic']=time.monotonic()
                        if data.get('type')=='pong':
                            metrics['last_heartbeat_monotonic']=time.monotonic()
                            metrics['heartbeat_events']=metrics.get('heartbeat_events',0)+1;continue
                        for event in mapper.update(data):
                            metrics['last_transcript_monotonic']=time.monotonic()
                            metrics['transcript_events']=metrics.get('transcript_events',0)+1
                            try:await asyncio.wait_for(queue.put(event),remaining())
                            except TimeoutError as exc:
                                raise ProviderError('asr_result_backlog','Soniox 字幕结果队列持续满载，已停止采集；未自动重试。') from exc
                        if data.get('finished'):
                            if finish_at is None:raise ProviderError('upstream_ended_early','Soniox 提前结束，未自动重启付费识别。')
                            await asyncio.wait_for(asyncio.shield(sender),remaining())
                            return
                sender=asyncio.create_task(send_audio());pinger=asyncio.create_task(heartbeat());reader=asyncio.create_task(receive_results())
                try:
                    while True:
                        if reader.done():
                            while not queue.empty():yield queue.get_nowait()
                            reader.result();break
                        pending=asyncio.create_task(queue.get())
                        done,_=await asyncio.wait((pending,reader),return_when=asyncio.FIRST_COMPLETED)
                        if pending in done:
                            value=pending.result();pending=None;yield value
                        else:
                            pending.cancel();await asyncio.gather(pending,return_exceptions=True);pending=None
                finally:
                    tasks=[t for t in (sender,pinger,reader,receiver,pending,finishing) if t is not None]
                    for task in tasks:task.cancel()
                    await asyncio.gather(*tasks,return_exceptions=True)
        except InvalidStatus as exc:raise soniox_error(exc.response.status_code) from exc
        except ConnectionClosed as exc:raise ProviderError('upstream_disconnected','Soniox 连接中断，未确认原文不标记正式完成。') from exc
        except TimeoutError as exc:raise ProviderError('timeout','Soniox 连接、发送或收尾超时。') from exc
        except OSError as exc:raise ProviderError('upstream_unavailable','无法连接 Soniox 服务，请检查服务器网络。') from exc
        except (ValueError,KeyError,TypeError) as exc:raise ProviderError('protocol_error','Soniox 返回了无法解析的识别消息。') from exc
