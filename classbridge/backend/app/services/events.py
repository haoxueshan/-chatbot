"""Atomic stable versions, durable event sequence and transactional task outbox."""
from sqlalchemy import select
from app.models import Session, Event, SegmentRevision, Translation, ProcessingTask, Outbox, uid


def emit(db, session, event_type, **fields):
    # Locking session makes seq allocation safe between websocket and worker processes.
    session = db.execute(select(Session).where(Session.id == session.id).with_for_update()).scalar_one()
    db.refresh(session)
    session.event_seq += 1
    event_id = uid()
    payload = {'type':event_type,'event_id':event_id,'event_seq':session.event_seq,
               'session_id':session.id,'stream_id':session.active_stream_id,
               'mode':session.mode, **fields}
    db.add(Event(id=event_id, session_id=session.id,event_seq=session.event_seq,type=event_type,payload=payload))
    db.flush()
    return payload


def enqueue(db, user_id, kind, key, payload, session_id=None, document_id=None):
    task = db.query(ProcessingTask).filter_by(idempotency_key=key).first()
    if task: return task
    task = ProcessingTask(id=uid(),user_id=user_id,kind=kind,idempotency_key=key,payload=payload,
                          session_id=session_id,document_id=document_id)
    db.add(task); db.flush()
    db.add(Outbox(task_id=task.id)); db.flush()
    return task


def latest_segments(db, session_id):
    revisions = db.query(SegmentRevision).filter_by(session_id=session_id).order_by(SegmentRevision.start_ms,SegmentRevision.source_revision).all()
    latest = {}
    for row in revisions:
        if row.sentence_id not in latest or row.source_revision > latest[row.sentence_id].source_revision:
            latest[row.sentence_id] = row
    return sorted((r for r in latest.values() if r.status=='final'),key=lambda r:(r.start_ms,r.sentence_id))


def serialize_segment(db, row):
    from app.services.correction import visible_suggestion
    task=db.query(ProcessingTask).filter_by(idempotency_key=f'correction:{row.id}').first()
    translation = db.query(Translation).filter_by(segment_id=row.id).order_by(Translation.translation_revision.desc()).first()
    return {'sentence_id':row.sentence_id,'stream_id':row.stream_id,'source_revision':row.source_revision,
            'translation_revision':translation.translation_revision if translation else 0,
            'start_ms':row.start_ms,'end_ms':row.end_ms,'text':row.text,
            'translation':translation.text if translation else '', 'status':('retired' if row.status=='retired' else 'final' if translation else 'translating'),
            'mode':row.mode,'speaker':row.speaker,'latency':row.latency,'provenance':row.provenance,
            'suggestion':visible_suggestion(task)}


def save_final(db, session_id, stream_id, sentence_id, revision, text, start_ms, end_ms, translation=None, latency=None, provenance='realtime', force=False, commit=True):
    session = db.execute(select(Session).where(Session.id == session_id).with_for_update()).scalar_one_or_none()
    if not session or (not force and session.active_stream_id != stream_id): return None
    old = db.query(SegmentRevision).filter_by(session_id=session_id,sentence_id=sentence_id).order_by(SegmentRevision.source_revision.desc()).first()
    if old and revision <= old.source_revision: return None
    row = SegmentRevision(id=uid(),session_id=session_id,stream_id=stream_id,sentence_id=sentence_id,
                          source_revision=revision,text=text,start_ms=start_ms,end_ms=end_ms,mode=session.mode,
                          latency=latency or {},provenance=provenance)
    db.add(row); db.flush()
    payload = emit(db,session,'transcript.final',sentence_id=sentence_id,stream_id=stream_id,
                  source_revision=revision,translation_revision=0,start_ms=start_ms,end_ms=end_ms,text=text,status='final',latency=latency or {})
    enqueue(db,session.user_id,'index_segment',f'index:{row.id}',{'segment_id':row.id},session_id=session_id)
    if translation is not None:
        save_translation(db,row.id,translation)
    else:
        enqueue(db,session.user_id,'translate',f'translate:{row.id}',{'segment_id':row.id},session_id=session_id)
    session.duration_ms = max(session.duration_ms,end_ms)
    from app.services.correction import queue_assist
    queue_assist(db,row)
    if commit:db.commit()
    return payload


def save_translation(db, segment_id, text, revision=1):
    row = db.get(SegmentRevision,segment_id)
    if not row: return None
    latest = db.query(SegmentRevision).filter_by(session_id=row.session_id,sentence_id=row.sentence_id).order_by(SegmentRevision.source_revision.desc()).first()
    if latest.id != row.id or latest.status!='final': return None
    previous = db.query(Translation).filter_by(segment_id=row.id).order_by(Translation.translation_revision.desc()).first()
    if previous and previous.translation_revision >= revision: return None
    db.add(Translation(segment_id=row.id,source_revision=row.source_revision,translation_revision=revision,text=text,mode=row.mode))
    session = db.get(Session,row.session_id)
    return emit(db,session,'translation.final',sentence_id=row.sentence_id,stream_id=row.stream_id,
                source_revision=row.source_revision,translation_revision=revision,start_ms=row.start_ms,end_ms=row.end_ms,
                text=row.text,translation=text,status='final',latency=row.latency)
