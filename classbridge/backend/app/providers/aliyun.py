"""Documented DashScope protocols. Never substitutes demo results for failures."""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator
from urllib.parse import urlparse

import httpx
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus, ConnectionClosed
from app.providers.transport import tls_context


class ProviderError(Exception):
    def __init__(self, code: str, message: str, retryable: bool = False, diagnostics=None):
        super().__init__(message)
        self.code, self.message, self.retryable = code, message, retryable
        self.diagnostics = diagnostics or {}


def classify_error(status: int = 0, code: str = "") -> ProviderError:
    value = code.lower()
    if any(s in value for s in ("arrearage", "quota", "insufficient", "balance")) or status == 402:
        return ProviderError("quota_exhausted", "模型额度或账户余额不足，请在阿里云控制台检查。")
    if "illegalendpoint" in value:
        return ProviderError("region_mismatch", "阿里云业务空间接入地址无效，请核对业务空间ID、地域，或从百炼控制台复制正确的API Host。")
    if "region" in value or "workspace" in value:
        return ProviderError("region_mismatch", "模型地域或业务空间不匹配，请检查服务器配置。")
    if status == 401 or "apikey" in value or "unauthorized" in value:
        return ProviderError("authentication_failed", "阿里云身份认证失败，请检查服务器密钥及地域。")
    if status == 403 or "accessdenied" in value or "permission" in value:
        return ProviderError("model_permission", "当前 API Key 无权调用该模型或业务空间。")
    if status == 404 or "modelnotfound" in value:
        return ProviderError("model_unavailable", "模型或接入地址不可用，请核对模型、地域及权限。")
    if status == 429 or "throttl" in value or "ratelimit" in value:
        return ProviderError("rate_limited", "阿里云请求限流，请稍后手动重试。", True)
    if status in (408, 504) or "timeout" in value:
        return ProviderError("timeout", "模型请求超时；结果未被替换为模拟内容。", True)
    if status in (400, 422) or "invalid" in value or "format" in value:
        return ProviderError("format_error", "模型请求或音频格式不被接受，请检查协议配置。")
    return ProviderError("upstream_error", "模型服务暂时不可用，请检查服务端诊断代码。", status >= 500)


def normalize_filetrans(result: dict) -> list[dict]:
    """Normalize the documented result JSON; timing is relative to this audio file."""
    output = []
    for transcript in result.get("transcripts", []):
        for sentence in transcript.get("sentences", []):
            if not isinstance(sentence.get("text"), str) or not sentence["text"].strip():
                continue
            begin, end = sentence.get("begin_time"), sentence.get("end_time")
            if not isinstance(begin, (int, float)) or not isinstance(end, (int, float)) or begin < 0 or end < begin:
                raise ProviderError("format_error", "文件转写返回了无效的句子时间戳。")
            output.append({"text": sentence["text"], "start_ms": int(begin), "end_ms": int(end), "speaker": None if sentence.get("speaker_id") is None else str(sentence["speaker_id"])})
    return sorted(output, key=lambda item: (item["start_ms"], item["end_ms"]))


class AliyunProvider:
    def __init__(self, config=None):
        if config is None:
            from app.config import settings
            config = settings
        self.config = config

    def value(self, key: str, default=None):
        return getattr(self.config, key, default)

    def ensure_ready(self):
        key = self.value("dashscope_api_key", "")
        if hasattr(key, "get_secret_value"):
            key = key.get_secret_value()
        if not key:
            raise ProviderError("missing_api_key", "服务器未配置 DASHSCOPE_API_KEY；真实模式不可用，不会产生模拟字幕。")
        return key

    @property
    def timeout(self):
        return float(self.value("model_timeout_seconds", 35))

    def ensure_configured(self, protocols=('ws', 'openai', 'native')):
        """Local configuration validation only; no network or claim of model access."""
        self.ensure_ready()
        for protocol in protocols:
            self.base(protocol)

    def base(self, protocol="openai"):
        attr = {"openai": "openai_base_url", "native": "dashscope_base_url", "ws": "asr_ws_url"}[protocol]
        explicit = self.value(attr, "")
        if explicit:
            url = str(explicit).rstrip("/")
            parsed = urlparse(url)
            if parsed.scheme != ('wss' if protocol == 'ws' else 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ProviderError('invalid_endpoint', '模型接入地址格式无效：HTTP接口须使用HTTPS，识别连接须使用WSS，地址中不能包含凭据或查询参数。')
            return url
        workspace = self.value("dashscope_workspace_id", "")
        region = self.value("dashscope_region", "cn-beijing")
        if not workspace:
            raise ProviderError("missing_workspace", "请在服务器配置 DASHSCOPE_WORKSPACE_ID，或明确设置经过核验的接入地址。")
        if not all(c.isalnum() or c == "-" for c in str(workspace)):
            raise ProviderError("region_mismatch", "业务空间 ID 格式不正确。")
        host = f"{workspace}.{region}.maas.aliyuncs.com"
        return {"openai": f"https://{host}/compatible-mode/v1", "native": f"https://{host}/api/v1", "ws": f"wss://{host}/api-ws/v1/inference"}[protocol]

    def headers(self):
        return {"Authorization": f"Bearer {self.ensure_ready()}"}

    async def request(self, path, payload=None, *, native=False, method="POST", headers=None):
        auth = self.headers()
        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False, verify=await tls_context()) as client:
                response = await client.request(method, self.base("native" if native else "openai") + path, json=payload, headers={**auth, **(headers or {})})
            if response.is_error:
                try:
                    data = response.json()
                    err = data.get("error", data)
                    code = str(err.get("code", "")) if isinstance(err, dict) else ""
                except ValueError:
                    code = ""
                raise classify_error(response.status_code, code)
            data = response.json()
            if data.get("code"):
                raise classify_error(0, data["code"])
            return data
        except httpx.TimeoutException as exc:
            raise classify_error(408) from exc
        except httpx.RequestError as exc:
            raise ProviderError("network_error", "无法连接阿里云模型服务。", True) from exc

    async def translate_stream(self, text: str, *, terms=None, context="", memory=None, source_lang="auto", require_complete=False) -> AsyncIterator[str]:
        options = {"source_lang": source_lang, "target_lang": "Chinese"}
        if terms:
            options["terms"] = [{"source": str(t["source"]), "target": str(t["target"])} for t in terms[:100] if isinstance(t, dict) and t.get("source") and t.get("target")]
        if context:
            options["domains"] = str(context)[:1500]
        if memory:
            options["tm_list"] = [{"source": str(t["source"]), "target": str(t["target"])} for t in memory[-5:] if isinstance(t, dict) and t.get("source") and t.get("target")]
        payload = {"model": self.value("translation_model", "qwen-mt-flash"), "messages": [{"role": "user", "content": text}], "translation_options": options, "stream": True}
        auth = self.headers()
        complete = False
        truncated = False
        try:
            async with httpx.AsyncClient(timeout=self.timeout, verify=await tls_context()) as client:
                async with client.stream("POST", self.base() + "/chat/completions", headers=auth, json=payload) as response:
                    if response.is_error:
                        await response.aread()
                        try:
                            error = response.json().get("error", {})
                            code = error.get("code", "") if isinstance(error, dict) else ""
                        except ValueError:
                            code = ""
                        raise classify_error(response.status_code, code)
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        value = line[5:].strip()
                        if value == "[DONE]":
                            complete = True
                            break
                        data = json.loads(value)
                        if data.get("error"):
                            raise classify_error(0, data["error"].get("code", ""))
                        choices = data.get("choices", [])
                        if choices:
                            if choices[0].get('finish_reason') == 'stop':complete = True
                            if choices[0].get('finish_reason') not in (None,'stop'):truncated = True
                            token = choices[0].get("delta", {}).get("content")
                            if token:
                                yield token
                    if require_complete and (not complete or truncated):
                        raise ProviderError('incomplete_translation','翻译流未正常结束，未将临时结果保存为正式译文。',True)
        except httpx.TimeoutException as exc:
            raise classify_error(408) from exc
        except httpx.RequestError as exc:
            raise ProviderError("network_error", "翻译服务连接中断。", True) from exc

    async def translate(self, text, **kwargs):
        return "".join([token async for token in self.translate_stream(text, **kwargs)])

    async def generate(self, prompt: str, *, system: str = "请根据证据用简体中文回答。", model=None, json_mode=False):
        payload = {"model": model or self.value("answer_model", "qwen3.7-plus"), "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}], "enable_thinking": False}
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        data = await self.request("/chat/completions", payload)
        return data["choices"][0]["message"]["content"]

    async def embeddings(self, texts: list[str]):
        output = []
        for start in range(0, len(texts), 10):
            data = await self.request("/embeddings", {"model": self.value("embedding_model", "text-embedding-v4"), "input": texts[start:start + 10], "dimensions": 1024, "encoding_format": "float"})
            vectors = sorted(data["data"], key=lambda item: item["index"])
            if len(vectors) != len(texts[start:start + 10]) or any(len(item["embedding"]) != 1024 for item in vectors):
                raise ProviderError("format_error", "向量服务返回了不匹配的维度或数量。")
            output.extend(item["embedding"] for item in vectors)
        return output

    async def rerank(self, question: str, documents: list[str], top_n=8):
        if not documents:
            return []
        data = await self.request("/services/rerank/text-rerank/text-rerank", {"model": self.value("rerank_model", "qwen3-rerank"), "input": {"query": question, "documents": documents}, "parameters": {"top_n": min(top_n, len(documents)), "return_documents": False}}, native=True)
        return [(r["index"], r["relevance_score"]) for r in data["output"]["results"] if 0 <= r["index"] < len(documents)]

    async def stream_asr(self, audio: AsyncIterator[bytes], *, vocabulary=None, context=None, language_hints=None, vad_model=None, on_ready=None, metrics=None) -> AsyncIterator[dict]:
        """Caller closes audio iterator on stop; final results drain until task-finished."""
        task_id = uuid.uuid4().hex
        params = {"format": "pcm", "sample_rate": 16000, "heartbeat": True}
        if vad_model is not None:
            if vad_model not in ("near_meeting_16k", "far_field_meeting_16k"):
                raise ProviderError("invalid_asr_parameter", "不支持的拾音场景参数。")
            params["vad_model"] = vad_model
        if language_hints:
            params['language_hints'] = list(language_hints)
        if vocabulary:
            params["vocabulary"] = {str(k): max(1, min(5, int(v))) for k, v in vocabulary.items()}
        input_data = {}
        if context:
            # Only the documented input.context messages are sent; no invented prompt field.
            input_data["context"] = [{"role": "user", "content": [{"type": "input_text", "text": str(context).strip()[:400]}]}]
        message = {"header": {"action": "run-task", "task_id": task_id, "streaming": "duplex"}, "payload": {"task_group": "audio", "task": "asr", "function": "recognition", "model": self.value("asr_model", "qwen-audio-3.1-asr-flash-streaming"), "parameters": params, "input": input_data}}
        headers = self.headers()
        sender = None
        receiver = None
        metrics = metrics if metrics is not None else {}
        metrics.update(sent_audio_ms=0, send_wait_ms=0)
        finish_sent = False
        try:
            async with connect(self.base("ws"), additional_headers=headers, open_timeout=self.timeout, close_timeout=5, max_size=2**20, max_queue=32, ping_interval=20) as ws:
                await ws.send(json.dumps(message))
                first = json.loads(await asyncio.wait_for(ws.recv(), self.timeout))
                if first.get("header", {}).get("event") != "task-started":
                    raise classify_error(0, first.get("header", {}).get("error_code", ""))
                if first.get("header", {}).get("task_id") != task_id:
                    raise ProviderError('protocol_error','识别服务返回了不匹配的任务确认，音频尚未发送，请重新开始。')
                metrics['last_event_monotonic']=time.monotonic()
                if on_ready:
                    await on_ready()

                async def send_audio():
                    nonlocal finish_sent
                    async for frame in audio:
                        if not frame or len(frame) % 2 or len(frame) > 32000:
                            raise ProviderError("format_error", "PCM 帧须为单声道 16 kHz int16，且不超过一秒。")
                        stamp=time.monotonic()
                        try:
                            await asyncio.wait_for(ws.send(frame),float(self.value('asr_send_timeout_seconds',5)))
                        except TimeoutError as exc:
                            raise ProviderError('upstream_send_timeout','向阿里云发送音频超时，采集已停止；请检查服务器网络后重试。') from exc
                        metrics['send_wait_ms']=int((time.monotonic()-stamp)*1000)
                        metrics['last_send_monotonic']=time.monotonic()
                        metrics['sent_audio_ms']+=len(frame)//32
                        # Buffered browser packets must not starve response handling.
                        await asyncio.sleep(0)
                    finish_sent=True
                    await asyncio.wait_for(ws.send(json.dumps({"header": {"action": "finish-task", "task_id": task_id, "streaming": "duplex"}, "payload": {"input": {}}})),self.timeout)

                sender = asyncio.create_task(send_audio())
                try:
                    while True:
                        receiver=asyncio.create_task(ws.recv())
                        if not sender.done():
                            done,_=await asyncio.wait({sender,receiver},timeout=self.timeout,return_when=asyncio.FIRST_COMPLETED)
                            if not done:raise TimeoutError()
                            if sender in done:sender.result()  # Propagate a failed send immediately.
                        else:sender.result()
                        data=json.loads(await asyncio.wait_for(receiver,self.timeout))
                        receiver=None
                        metrics['last_event_monotonic']=time.monotonic()
                        header = data.get("header", {})
                        if header.get("task_id") != task_id:
                            continue
                        event = header.get("event")
                        if event == "task-failed":
                            raise classify_error(0, header.get("error_code", ""))
                        if event == "task-finished":
                            if not finish_sent:
                                raise ProviderError('upstream_ended_early','识别服务提前结束了当前任务；已保存字幕保留，请手动重新开始。')
                            break
                        if event != "result-generated":
                            continue
                        sentence = data.get("payload", {}).get("output", {}).get("sentence", {})
                        if sentence.get("heartbeat") or not sentence.get("text"):
                            continue
                        metrics['last_transcript_monotonic']=time.monotonic()
                        metrics['transcript_events']=metrics.get('transcript_events',0)+1
                        yield {"sentence_id": str(sentence["sentence_id"]), "text": sentence["text"], "start_ms": int(sentence.get("begin_time") or 0), "end_ms": sentence.get("end_time"), "final": bool(sentence.get("sentence_end")), "words": sentence.get("words", [])}
                finally:
                    # Cancel children BEFORE closing the socket. Shutdown errors must
                    # not replace the original failure or caller cancellation.
                    tasks=[task for task in (sender,receiver) if task is not None]
                    for task in tasks:task.cancel()
                    await asyncio.gather(*tasks,return_exceptions=True)
        except InvalidStatus as exc:
            # Classify a handshake failure before audio submission; never log
            # authorization headers or the raw provider response body.
            code = ""
            try:
                body = exc.response.body or b""
                if len(body) <= 16384:
                    data = json.loads(body)
                    if isinstance(data, dict):
                        code = str(data.get("code", ""))
            except (ValueError, TypeError):
                pass
            raise classify_error(exc.response.status_code, code) from exc
        except ConnectionClosed as exc:
            close_code=exc.rcvd.code if exc.rcvd else (exc.sent.code if exc.sent else 1006)
            raise ProviderError('upstream_disconnected',f'阿里云识别连接已断开（关闭码 {close_code}），已停止采集。已保存字幕保留，请手动重新开始。',
                                diagnostics={'upstream_close_code':close_code}) from exc
        except (TimeoutError, asyncio.TimeoutError) as exc:
            raise classify_error(408) from exc
        except OSError as exc:
            raise ProviderError('network_error','无法连接阿里云或网络连接已中断，请检查服务器网络。') from exc

    async def submit_filetrans(self, url: str):
        if urlparse(url).scheme != "https":
            raise ProviderError("audio_url_unavailable", "会后转写需要服务器签发的短期 HTTPS 音频地址。")
        data = await self.request("/services/audio/asr/transcription", {"model": self.value("filetrans_model", "qwen-audio-3.1-asr-flash-filetrans"), "input": {"file_urls": [url]}, "parameters": {"diarization_enabled": True, "channel_id": [0]}}, native=True, headers={"X-DashScope-Async": "enable"})
        return data["output"]["task_id"]

    async def poll_filetrans(self, task_id: str):
        if not all(c.isalnum() or c == "-" for c in task_id):
            raise ProviderError("format_error", "无效的转写任务编号。")
        data = await self.request(f"/tasks/{task_id}", native=True, method="GET")
        output = data["output"]
        if output["task_status"] in ("PENDING", "RUNNING"):
            return None
        if output["task_status"] != "SUCCEEDED":
            raise classify_error(0, output.get("code", ""))
        results = output.get("results", [])
        if not results or results[0].get("subtask_status") != "SUCCEEDED":
            raise ProviderError("filetrans_failed", "音频文件转写失败，检查短期地址是否可访问。")
        url = results[0]["transcription_url"]
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith(".aliyuncs.com"):
            raise ProviderError("format_error", "拒绝不受信任的转写结果下载地址。")
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False, verify=await tls_context()) as client:
            result = await client.get(url)
            result.raise_for_status()
            return result.json()

    async def filetrans(self, url: str, *, task_id=None, max_wait_seconds=600):
        task_id = task_id or await self.submit_filetrans(url)
        deadline = time.monotonic() + max_wait_seconds
        while time.monotonic() < deadline:
            result = await self.poll_filetrans(task_id)
            if result is not None:
                return result
            await asyncio.sleep(5)
        raise ProviderError("timeout", "会后转写仍未完成；已停止轮询，不自动重复提交付费任务。")
