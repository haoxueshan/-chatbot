"""Reversible word-boundary agreement for sentence hypotheses, never a final source.

Inspired by LocalAgreement, not a port of token/timestamp Whisper code. Qwen owns
all final boundaries. A duplicated hypothesis is not an independent agreement.
"""
from collections import OrderedDict
from dataclasses import dataclass, field
import re


def complete_words(text):
    # A trailing word without whitespace/punctuation may still acquire a Korean
    # ending or English suffix. Never cut an eojeol/word at a character LCP.
    return [(m.group(), m.end()) for m in re.finditer(r"\S+", text)
            if m.end() < len(text) or re.search(r"[.!?。！？,;:，；：]$", m.group())]


@dataclass(frozen=True)
class Preview:
    stable_preview: str
    unstable_tail: str
    hypothesis_revision: int
    is_final: bool = False


@dataclass
class Hypothesis:
    previous_hypothesis: str = ""
    current_hypothesis: str = ""
    stable_prefix: str = ""
    unstable_tail: str = ""
    last_update_time: float = 0
    last_translation_time: float = float('-inf')
    first_update_time: float = 0
    revision: int = 0
    words: list = field(default_factory=list)
    agreed: int = 0


class StablePrefixProcessor:
    def __init__(self, min_stable_seconds=.35, max_chars=2048, max_sentences=64, ttl_seconds=30):
        self.min_stable_seconds = min_stable_seconds
        self.max_chars = max_chars
        self.max_sentences = max_sentences
        self.ttl_seconds = ttl_seconds
        self.states = OrderedDict()
        self.rollbacks = 0

    def expire(self, timestamp):
        for key, state in list(self.states.items()):
            if timestamp - state.last_update_time > self.ttl_seconds:
                del self.states[key]

    def update(self, stream_id, sentence_id, text, timestamp):
        self.expire(timestamp)
        key = (stream_id, sentence_id)
        # Oversized hypotheses remain visible in the original transcript, but
        # are excluded from speculative processing rather than silently truncated.
        if len(text) > self.max_chars:
            self.states.pop(key, None)
            return Preview('', text, 0)
        state = self.states.get(key)
        if state and timestamp < state.last_update_time:
            return self.view(stream_id, sentence_id, state.last_update_time)
        if state is None:
            while len(self.states) >= self.max_sentences:
                self.states.popitem(last=False)
            state = Hypothesis(first_update_time=timestamp)
            self.states[key] = state
        if text == state.current_hypothesis and state.revision:
            state.last_update_time=timestamp # liveness, not independent agreement
            return self.view(stream_id, sentence_id, timestamp)
        words = complete_words(text)
        common = 0
        for old, new in zip(state.words, words):
            if old[0] != new[0]:
                break
            common += 1
        state.words = [(word, end, state.words[i][2] if i < common else timestamp)
                       for i, (word, end) in enumerate(words)]
        state.agreed = common
        state.previous_hypothesis = state.current_hypothesis
        state.current_hypothesis = text
        state.last_update_time = timestamp
        state.revision += 1
        self.states.move_to_end(key)
        return self.view(stream_id, sentence_id, timestamp)

    def view(self, stream_id, sentence_id, timestamp):
        state = self.states.get((stream_id, sentence_id))
        if state is None:
            return Preview('', '', 0)
        end = 0
        for _, position, since in state.words[:state.agreed]:
            if timestamp - since < self.min_stable_seconds:
                break
            end = position
        # Include the original separator, not an invented space/normalization.
        while end and end < len(state.current_hypothesis) and state.current_hypothesis[end].isspace():
            end += 1
        stable = state.current_hypothesis[:end]
        if state.stable_prefix and not stable.startswith(state.stable_prefix):
            self.rollbacks += 1
        state.stable_prefix = stable
        state.unstable_tail = state.current_hypothesis[end:]
        return Preview(stable, state.unstable_tail, state.revision)

    def finalize(self, stream_id, sentence_id):
        state = self.states.pop((stream_id, sentence_id), None)
        return Preview('', '', state.revision if state else 0, is_final=True)

    def reset_stream(self, stream_id):
        for key in list(self.states):
            if key[0] == stream_id:
                del self.states[key]
