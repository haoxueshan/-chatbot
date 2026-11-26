"""Incident metadata adds meaning to existing capture.gap events; no audio recovery claims."""
import re
import uuid
from datetime import datetime,timezone

KINDS={'audio_missing','audio_delayed','asr_interrupted','asr_result_uncertain',
       'translation_delayed','user_paused','connection_recovering','connection_recovered','storage_failed'}


def safe_identifier(value):
    return value if isinstance(value,str) and re.fullmatch(r'[A-Za-z0-9_:.-]{1,120}',value) else None


def fields(capture_id,stream_id,kind,reason_code,duration_ms=None,incident_id=None):
    kind=kind if kind in KINDS else 'asr_result_uncertain'
    # Wall-clock pauses may exceed the per-recording 105-minute limit.
    duration=duration_ms if isinstance(duration_ms,(int,float)) and 0<duration_ms<=2**53 else None
    identity=safe_identifier(capture_id) or safe_identifier(stream_id) or uuid.uuid4().hex
    return dict(incident_id=safe_identifier(incident_id) or f'{identity}:failure',capture_id=identity,
        gap_kind=kind,reason_code=safe_identifier(reason_code) or 'capture_interrupted',
        duration_ms=duration,missing_audio_ms=duration if kind=='audio_missing' else None,
        uncertain_audio_ms=duration if kind=='asr_result_uncertain' else None,
        recoverable=False,recovered=False,detected_at=datetime.now(timezone.utc).isoformat())
