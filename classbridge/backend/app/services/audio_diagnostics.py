"""Bounded numeric diagnostics and process-local PCM admission accounting."""
import asyncio
import time
import weakref
from collections import deque
from app.config import settings

captures=weakref.WeakSet()


def process_buffer_bytes():
    return sum(c.buffer_bytes() for c in list(captures))


def buffering_state(milliseconds, warning, high, maximum):
    return 'OVERFLOW' if milliseconds>=maximum else 'DEGRADED' if milliseconds>=high else 'BUFFERING' if milliseconds>=warning else 'NORMAL'


class LoopHealth:
    def __init__(self):self.samples=deque(maxlen=120);self.peak=0
    def record(self,lag):
        self.samples.append(max(0,lag));self.peak=max(self.peak,lag)
    def snapshot(self):
        values=sorted(self.samples)
        return {'event_loop_lag_ms':round(self.samples[-1],2) if values else 0,
                'event_loop_lag_peak_ms':round(self.peak,2),
                'event_loop_lag_p95_ms':round(values[min(len(values)-1,int(len(values)*.95))],2) if values else 0}
    async def run(self):
        interval=settings.event_loop_lag_sample_ms/1000
        while True:
            start=time.monotonic();await asyncio.sleep(interval)
            self.record((time.monotonic()-start-interval)*1000)


loop_health=LoopHealth()
