"""Provider-independent transcript boundary; offset is applied exactly once."""
import math
from dataclasses import dataclass
from sqlalchemy import select, literal
from app.providers.errors import ProviderError
from app.models import Session, SegmentRevision


def audio_time(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 2**53 - 1:
        raise ProviderError('protocol_error', '原文音频时间戳无效，未生成正式记录。')
    return int(value)


@dataclass(frozen=True)
class TranscriptUpdate:
    sentence_id: str
    text: str
    final: bool
    start_ms: int
    end_ms: int  # UI compatibility only when end_state != confirmed
    end_state: str

    @property
    def result(self):
        return self.text, self.start_ms, self.end_ms, self.final, self.end_state

    @property
    def fingerprint(self):
        return self.sentence_id, self.text, self.start_ms, self.end_ms


def normalize_update(event, stream_id, offset):
    if event.get('stream_id') not in (None, stream_id):
        return None
    sid = event.get('sentence_id')
    # Existing direct consume callers omit these two fields for partials.
    final = event.get('final', False)
    if not isinstance(sid, str) or not sid or not isinstance(event.get('text'), str) or type(final) is not bool:
        raise ProviderError('protocol_error', '原文事件字段无效。')
    start = audio_time(event.get('start_ms', 0))
    end = event.get('end_ms')
    state = 'confirmed'
    if end is None:
        if final:
            raise ProviderError('protocol_error', '正式原文缺少结束时间，未生成伪造时间。')
        end = event.get('provisional_end_ms')
        state = 'provisional' if end is not None else 'unknown'
        if end is None:
            end = start
    end = audio_time(end)
    if end < start:
        raise ProviderError('protocol_error', '原文音频时间范围无效。')
    return TranscriptUpdate(f'{stream_id}:{sid}', event['text'].strip(), final,
                            offset + start, offset + end, state)


def lookup_transcript(db, session_id, user_id, stream_id, update, known_revision):
    """Revalidate cross-process ownership/active stream on every accepted event."""
    identity=(SegmentRevision.session_id==session_id,SegmentRevision.stream_id==stream_id,
              SegmentRevision.sentence_id==update.sentence_id)
    # One statement, no long-lived Session or process-local permission cache.
    # Even a known partial checks durable final evidence from other processes.
    revision=select(SegmentRevision.source_revision).where(*identity).order_by(
        SegmentRevision.source_revision.desc()).limit(1).scalar_subquery()
    duplicate=(select(SegmentRevision.id).where(*identity,SegmentRevision.text==update.text,
        SegmentRevision.start_ms==update.start_ms,SegmentRevision.end_ms==update.end_ms).exists()
        if update.final else literal(False))
    row=db.execute(select(Session.id,revision,duplicate).where(Session.id==session_id,
        Session.user_id==user_id,Session.active_stream_id==stream_id)).first()
    return (True,row[1],bool(row[2])) if row else (False,None,False)


def persist_final_update(db, session_id, stream_id, update, revision, *, save, **options):
    """Reuse save_final's transaction and Outbox, including idempotent verification."""
    if not update.final or update.end_state!='confirmed':
        raise ProviderError('protocol_error','临时原文不能保存为正式记录。')
    saved=save(db,session_id,stream_id,update.sentence_id,revision,update.text,
               update.start_ms,update.end_ms,**options)
    if saved is None:
        row=db.get(Session,session_id)
        if not row or row.active_stream_id!=stream_id:return False
        existing=db.query(SegmentRevision).filter_by(session_id=session_id,stream_id=stream_id,
            sentence_id=update.sentence_id,source_revision=revision).first()
        if not existing or (existing.text,existing.start_ms,existing.end_ms)!=(update.text,update.start_ms,update.end_ms):
            raise ValueError('source_revision_conflict')
    return True
