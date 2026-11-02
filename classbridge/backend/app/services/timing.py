"""Keep wall-clock evidence offsets separate from the capture duration limit."""
from app.models import RecognitionStream


def captured_duration_ms(db, session_id):
    streams = db.query(RecognitionStream).filter_by(session_id=session_id).all()
    return sum(max(0, stream.ended_ms - stream.offset_ms)
               for stream in streams if stream.ended_ms is not None)
