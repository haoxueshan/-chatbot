"""Bounded numeric diagnostics and process-local PCM admission accounting."""
import asyncio
import time
import weakref
from collections import deque
from app.config import settings

captures=weakref.WeakSet()


def recognition_progress(metrics, stamp, *, started, last_audio, input_dbfs, backlog_ms, warning_seconds=20):
    """Heuristic observation only. Energy is NOT speech detection or a failure."""
    def age(value):
        return round(max(0,stamp-value)*1000,2) if value is not None else None
    transcript=metrics.get('last_transcript_monotonic')
    ages={name:age(metrics.get(key)) for name,key in (
        ('last_audio_sent_age_ms','last_send_monotonic'),
        ('last_provider_event_age_ms','last_event_monotonic'),
        ('last_provider_heartbeat_age_ms','last_heartbeat_monotonic'),
        ('last_asr_partial_age_ms','last_partial_monotonic'),
        ('last_asr_final_age_ms','last_final_monotonic'))}
    ages['last_asr_transcript_age_ms']=age(transcript)
    ages['recognition_stall_suspected']=bool(started and last_audio is not None and stamp-last_audio<2
        and ages['last_audio_sent_age_ms'] is not None and ages['last_audio_sent_age_ms']<2000
        and ages['last_provider_heartbeat_age_ms'] is not None and ages['last_provider_heartbeat_age_ms']<15000
        and stamp-(transcript if transcript is not None else started)>=warning_seconds
        and input_dbfs>-40 and backlog_ms<1000 and metrics.get('asr_result_queue_size',0)<16)
    return ages


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
