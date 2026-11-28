"""Bounded stream-local hypotheses. Persistence remains the authority on eviction."""
from enum import Enum
from app.providers.errors import ProviderError


class Decision(str, Enum):
    ACCEPTED_PARTIAL = 'accepted_partial'
    DUPLICATE = 'duplicate'
    STALE = 'stale'
    REQUIRES_LOOKUP = 'requires_lookup'
    FINAL_CANDIDATE = 'final_candidate'
    CONFLICT = 'conflict'


class HypothesisStore:
    def __init__(self):
        self.revisions = {}
        self.finalized = set()
        self.last_results = {}
        self.final_results = set()
        self.unconfirmed = {}
        self.first_seen = {}

    def assess(self, update, *, allow_final_revision=True):
        sid = update.sentence_id
        if sid in self.finalized and not update.final:
            return Decision.STALE
        if self.last_results.get(sid) == update.result or (update.final and update.fingerprint in self.final_results):
            return Decision.DUPLICATE
        if update.final and sid in self.finalized and not allow_final_revision:
            return Decision.CONFLICT
        if sid not in self.revisions:
            return Decision.REQUIRES_LOOKUP
        return Decision.FINAL_CANDIDATE if update.final else Decision.ACCEPTED_PARTIAL

    def check_partial_capacity(self, sid):
        if sid not in self.unconfirmed and len(self.unconfirmed) >= 200:
            raise ProviderError('source_buffer_full', '未定稿原文积压超过保护上限，已停止采集并保留未确认记录。')

    def commit_final(self, update, revision):
        # Caller MUST confirm transaction success before calling this method.
        sid = update.sentence_id
        self.revisions[sid] = revision
        self.last_results[sid] = update.result
        self.finalized.add(sid)
        self.final_results.add(update.fingerprint)
        self.unconfirmed.pop(sid, None)

    def trim(self):
        evicted = []
        while len(self.finalized) > 512:
            sid = next(key for key in self.revisions if key in self.finalized)
            self.finalized.remove(sid)
            for cache in (self.revisions, self.last_results, self.first_seen):
                cache.pop(sid, None)
            self.final_results.difference_update({fp for fp in self.final_results if fp[0] == sid})
            evicted.append(sid)
        while len(self.final_results) > 2048:
            self.final_results.pop()
        return evicted
