"""Bounded optional previews. No persistent source state and no paid retries.

One process-wide admission gate covers all LiveCapture instances. Admission is
non-waiting: final background requests never wait for a preview semaphore.
"""
import asyncio
from collections import OrderedDict, deque
from dataclasses import dataclass, field
import hashlib
import json
import re
import time
from datetime import datetime, timedelta, timezone

from app.services.stable_prefix import StablePrefixProcessor, complete_words
from app.services.translation_timing import TranslationTiming


def translation_spec(settings, terms, target_language='zh-CN'):
    # Mirror exactly the MT adapter's existing options. ASR context is NOT MT
    # context. Include endpoint/region as well as model to prevent cross-config reuse.
    from app.services.translation_languages import translation_terms,target_name
    normalized=translation_terms(terms,target_language)
    return {'model': settings.translation_model, 'terms': normalized,
            'source_lang': 'auto', 'target_lang': target_name(target_language), 'context': '', 'memory': [],
            'endpoint': settings.openai_base_url, 'region': settings.dashscope_region,
            'workspace': settings.dashscope_workspace_id}


def spec_digest(spec):
    return hashlib.sha256(json.dumps(spec, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def reuse_candidate(entry, text, revision, settings, *, stamp=None):
    record=entry.completed if entry else None
    stamp=time.monotonic() if stamp is None else stamp
    if not record or not record.get('complete') or record['text']!=text or not record['translation'].strip():return None
    age=stamp-record['completed_at']
    if not 0<=age<settings.preview_reuse_ttl_seconds:return None
    current=datetime.now(timezone.utc)
    return {k:v for k,v in record.items() if k!='completed_at'} | {
        'source_revision':revision,'saved_at':current.isoformat(),
        'expires_at':(current+timedelta(seconds=settings.preview_reuse_ttl_seconds-age)).isoformat()}


def validated_reuse(candidate, row, spec, current):
    if not isinstance(candidate,dict):return None
    try:
        saved=datetime.fromisoformat(candidate['saved_at'])
        expiry=datetime.fromisoformat(candidate['expires_at'])
        valid=(candidate.get('complete') is True and saved<=current<expiry
            and candidate['text']==row.text and candidate['stream_id']==row.stream_id
            and candidate['sentence_id']==row.sentence_id and candidate['source_revision']==row.source_revision
            and candidate['spec_digest']==spec_digest(spec)
            and isinstance(candidate['translation'],str) and candidate['translation'].strip())
        return candidate['translation'] if valid else None
    except (KeyError,ValueError,TypeError):return None


class PreviewBudget:
    def __init__(self):
        self.active = 0
        self.calls = deque()

    def acquire(self, stamp, concurrency, per_minute):
        while self.calls and stamp - self.calls[0] >= 60:
            self.calls.popleft()
        if self.active >= concurrency or len(self.calls) >= per_minute:
            return False
        self.active += 1
        self.calls.append(stamp)
        return True

    def release(self):
        self.active = max(0, self.active - 1)


preview_budget = PreviewBudget()


@dataclass
class Sentence:
    text: str
    revision: int
    start_ms: int
    end_ms: int
    first_at: float
    updated_at: float
    last_request_at: float = float('-inf')
    requested_text: str = ''
    request_id: int = 0
    task: object = None
    attempted: set = field(default_factory=set)
    completed: object = None
    first_output_at: object = None


class IncrementalTranslator:
    def __init__(self, settings, stream_id, spec, provider, publish, *, clock=time.monotonic, budget=None):
        self.settings = settings
        self.stream_id = stream_id
        self.spec = spec
        self.provider = provider
        self.publish = publish
        self.clock = clock
        self.budget = budget or preview_budget
        self.prefix = StablePrefixProcessor(settings.preview_min_stable_seconds,
            settings.preview_max_chars, settings.preview_max_sentences, settings.preview_ttl_seconds)
        self.sentences = OrderedDict()
        self.tasks = set()
        self.closed = False
        self.metrics = {'requests': 0, 'cancelled': 0, 'failed': 0, 'suppressed': 0}

    def _cancel(self, entry):
        entry.request_id += 1
        if entry.task and not entry.task.done():
            entry.task.cancel()
            self.metrics['cancelled'] += 1
        entry.task = None

    def update(self, sentence_id, revision, text, start_ms, end_ms):
        stamp = self.clock()
        self.expire(stamp)
        entry = self.sentences.get(sentence_id)
        if entry and revision < entry.revision:
            return self.prefix.view(self.stream_id, sentence_id, stamp)
        preview = self.prefix.update(self.stream_id, sentence_id, text, stamp)
        if self.closed or len(text) > self.settings.preview_max_chars:
            self.discard(sentence_id)
            return preview
        if entry is None:
            while len(self.sentences) >= self.settings.preview_max_sentences:
                self.discard(next(iter(self.sentences)))
            entry = Sentence(text, revision, start_ms, end_ms, stamp, stamp)
            self.sentences[sentence_id] = entry
        elif text != entry.text:
            # A growing compatible tail can use the same prefix result, explicitly
            # labelled with preview_source_text. A rewrite invalidates it immediately.
            if entry.requested_text and not text.startswith(entry.requested_text):
                self._cancel(entry)
                entry.completed = None
            entry.updated_at = stamp
        entry.text, entry.revision = text, revision
        entry.start_ms, entry.end_ms = start_ms, end_ms
        self.sentences.move_to_end(sentence_id)
        return preview

    def expire(self, stamp):
        for sid, entry in list(self.sentences.items()):
            if stamp - entry.updated_at > self.settings.preview_ttl_seconds:
                self.discard(sid)
        self.prefix.expire(stamp)

    def candidate(self, sid, entry, stamp):
        stable = self.prefix.view(self.stream_id, sid, stamp).stable_preview.rstrip()
        # Heuristic, not a semantic guarantee: Korean predicates/punctuation or
        # several complete words. Timer fallback does not declare source final.
        meaningful = bool(re.search(r'[.!?。！？;；]$|(?:습니다|합니다|해요|이에요|예요|이다)$', stable))
        reference = entry.first_at if entry.last_request_at == float('-inf') else entry.last_request_at
        if stamp - reference >= self.settings.preview_max_wait_seconds:
            words = complete_words(entry.text)
            if words and (len(words) >= 2 or re.search(r'[.!?。！？]$', entry.text)):
                return entry.text[:words[-1][1]].rstrip()
        if stable and (meaningful or len(stable.split()) >= self.settings.preview_min_words):
            return stable
        return ''

    def tick(self):
        if self.closed:
            return
        stamp = self.clock()
        self.expire(stamp)
        # Round-robin admission: a long sentence must not starve another sentence.
        for sid, entry in list(self.sentences.items()):
            text = self.candidate(sid, entry, stamp)
            digest = hashlib.sha256(text.encode()).hexdigest()
            if not text or digest in entry.attempted or len(entry.attempted) >= 64:
                continue
            if stamp - entry.last_request_at < self.settings.preview_interval_seconds:
                continue
            if (entry.requested_text and text.startswith(entry.requested_text)
                and len(text) - len(entry.requested_text) < self.settings.preview_min_change_chars
                and stamp - entry.last_request_at < self.settings.preview_max_wait_seconds):
                continue
            # Cancel only when a replacement is worth requesting. The done callback
            # retains the admission slot until cancellation actually completes.
            if entry.task and not entry.task.done():
                self._cancel(entry)
                continue
            if not self.budget.acquire(stamp, self.settings.preview_concurrency, self.settings.preview_calls_per_minute):
                self.metrics['suppressed'] += 1
                continue
            entry.request_id += 1
            entry.last_request_at = stamp
            entry.requested_text = text
            entry.completed = None
            entry.attempted.add(digest)
            state = self.prefix.states.get((self.stream_id, sid))
            if state: state.last_translation_time = stamp
            task = asyncio.create_task(self._translate(sid, entry, entry.request_id, text))
            entry.task = task
            self.tasks.add(task)
            def done(task):
                self.tasks.discard(task)
                self.budget.release()
            task.add_done_callback(done)
            self.metrics['requests'] += 1
            self.sentences.move_to_end(sid)

    async def _translate(self, sid, entry, request_id, text):
        timing = TranslationTiming(self.clock)
        translated = ''
        last_emit = float('-inf')
        def valid():
            return (not self.closed and self.sentences.get(sid) is entry
                    and entry.request_id == request_id and entry.text.startswith(text))
        async def emit(complete=False):
            if not valid(): return
            stamp = self.clock()
            if entry.first_output_at is None: entry.first_output_at = stamp
            await self.publish(sid, entry.revision, entry.start_ms, entry.end_ms, translated,
                {'preview_source_text': text, 'preview_request_id': request_id,
                 'preview_complete': complete, 'preview_model_first_ms': timing.first,
                 'preview_model_final_ms': timing.finish()['translation_model_final_ms'] if complete else None,
                 'preview_first_at': entry.first_output_at})
        try:
            async for delta in self.provider.translate_stream(text, terms=self.spec['terms'], target_lang=self.spec['target_lang'], require_complete=True):
                if not valid(): return
                if not delta: continue
                timing.token(); translated += delta
                if len(translated) > self.settings.preview_max_chars * 4:
                    raise ValueError('preview_output_limit')
                if self.clock() - last_emit >= self.settings.translation_emit_seconds:
                    await emit(); last_emit = self.clock()
            if valid() and translated.strip():
                entry.completed = {'text': text, 'translation': translated,
                    'spec_digest': spec_digest(self.spec), 'stream_id': self.stream_id,
                    'sentence_id': sid, 'completed_at': self.clock(), 'complete': True}
                await emit(complete=True)
        except asyncio.CancelledError:
            raise
        except Exception:
            self.metrics['failed'] += 1
            # A speculative failure must not stop audio or create a paid retry.

    def discard(self, sid):
        entry = self.sentences.pop(sid, None)
        if entry: self._cancel(entry)
        self.prefix.finalize(self.stream_id, sid)
        return entry

    def finalize(self, sid):
        return self.discard(sid)

    async def close(self):
        self.closed = True
        for sid in list(self.sentences): self.discard(sid)
        for task in self.tasks: task.cancel()
        if self.tasks: await asyncio.gather(*list(self.tasks), return_exceptions=True)
