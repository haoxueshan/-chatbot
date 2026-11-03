"""Only durations/clock labels; no source or translation content in diagnostics."""
from datetime import timezone
import time


def wall_queue_ms(created, started):
    created = created.replace(tzinfo=timezone.utc) if created.tzinfo is None else created
    started = started.replace(tzinfo=timezone.utc) if started.tzinfo is None else started
    raw = int((started - created).total_seconds() * 1000)
    return max(0, raw), raw < 0


class TranslationTiming:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.started = clock()
        self.first = None

    def token(self):
        if self.first is None:
            self.first = max(0, int((self.clock() - self.started) * 1000))

    def finish(self):
        return {'translation_model_first_ms': self.first,
                'translation_model_final_ms': max(0, int((self.clock() - self.started) * 1000))}
