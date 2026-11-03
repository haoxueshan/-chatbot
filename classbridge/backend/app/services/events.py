"""Atomic stable versions, durable event sequence and transactional task outbox."""
from sqlalchemy import select
from app.models import Session, Event, SegmentRevision, Translation, ProcessingTask, Outbox, uid
from app.services import translation_dispatch  # register commit/rollback hooks


def emit(db, session, event_type, **fields):
    # Locking session makes seq allocation safe between websocket and worker processes.
    session = db.execute(select(Session).where(Session.id == session.id).with_for_update()).scalar_one()
    db.refresh(session)
    session.event_seq += 1
    event_id = uid()
    payload = {'type':event_type,'event_id':event_id,'event_seq':session.event_seq,
               'session_id':session.id,'stream_id':session.active_stream_id,
               'mode':session.mode,'target_language':session.target_language, **fields}
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
    if kind=='translate':db.info['translation_pending']=True
    return task


def latest_segments(db, session_id):
    revisions = db.query(SegmentRevision).filter_by(session_id=session_id).order_by(SegmentRevision.start_ms,SegmentRevision.source_revision).all()
    latest = {}
    for row in revisions:
        if row.sentence_id not in latest or row.source_revision > latest[row.sentence_id].source_revision:
            latest[row.sentence_id] = row
    return sorted((r for r in latest.values() if r.status=='final'),key=lambda r:(r.start_ms,r.sentence_id))


def serialize_segment(db, row):
    language=db.get(Session,row.session_id).target_language
    translation = db.query(Translation).filter_by(segment_id=row.id,target_language=language).order_by(Translation.translation_revision.desc()).first()
    failed=db.query(ProcessingTask).filter_by(idempotency_key=f'translate:{row.id}',status='failed').first() if not translation else None
    return {'target_language':language,'sentence_id':row.sentence_id,'stream_id':row.stream_id,'source_revision':row.source_revision,
            'translation_revision':translation.translation_revision if translation else 0,
            'start_ms':row.start_ms,'end_ms':row.end_ms,'text':row.text,
            'translation':translation.text if translation else '', 'status':('retired' if row.status=='retired' else 'final' if translation else 'translating'),
            'source_status':row.status,'source_final':row.status=='final',
            'translation_status':'final' if translation else 'failed' if failed else 'pending','translation_final':bool(translation),
            'translation_error':failed.error if failed else None,
            'mode':row.mode,'speaker':row.speaker,'latency':row.latency,'provenance':row.provenance}


def save_final(db, session_id, stream_id, sentence_id, revision, text, start_ms, end_ms, translation=None, latency=None, provenance='realtime', force=False, commit=True, preview_candidate=None):
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
        task_payload={'segment_id':row.id,'source_revision':revision,'target_language':session.target_language}
        if preview_candidate is not None:task_payload['preview_candidate']=preview_candidate
        enqueue(db,session.user_id,'translate',f'translate:{row.id}',task_payload,session_id=session_id)
    session.duration_ms = max(session.duration_ms,end_ms)
    if commit:db.commit()
    return payload


def save_translation(db, segment_id, text, revision=1, *, target_language=None):
    row = db.get(SegmentRevision,segment_id)
    if not row: return None
    from app.services.translation_languages import target_code
    session=db.execute(select(Session).where(Session.id==row.session_id).with_for_update()).scalar_one()
    language=target_code(session.target_language)
    if target_language is not None and target_language!=language:raise ValueError('译文目标语言与会话不一致')
    latest = db.query(SegmentRevision).filter_by(session_id=row.session_id,sentence_id=row.sentence_id).order_by(SegmentRevision.source_revision.desc()).first()
    if latest.id != row.id or latest.status!='final': return None
    previous = db.query(Translation).filter_by(segment_id=row.id).order_by(Translation.translation_revision.desc()).first()
    if previous and previous.translation_revision >= revision: return None
    db.add(Translation(segment_id=row.id,source_revision=row.source_revision,translation_revision=revision,text=text,mode=row.mode,target_language=language))
    session = db.get(Session,row.session_id)
    return emit(db,session,'translation.final',sentence_id=row.sentence_id,stream_id=row.stream_id,
                source_revision=row.source_revision,translation_revision=revision,start_ms=row.start_ms,end_ms=row.end_ms,
                text=row.text,translation=text,status='final',latency=row.latency)


def save_interrupted(db, session_id, stream_id, snapshot):
    """Recovery-only event. Never enqueue work or create a formal source revision."""
    session=db.execute(select(Session).where(Session.id==session_id).with_for_update()).scalar_one_or_none()
    if not session or session.active_stream_id!=stream_id:return None
    sid=snapshot['sentence_id']
    if db.query(SegmentRevision.id).filter_by(session_id=session_id,stream_id=stream_id,sentence_id=sid).first():return None
    # Only called during bounded cleanup, not once per audio frame or partial.
    prior=db.query(Event).filter_by(session_id=session_id,type='transcript.interrupted').order_by(Event.event_seq.desc())
    for event in prior:
        p=event.payload
        if p.get('stream_id')==stream_id and p.get('sentence_id')==sid:
            if p.get('source_revision',0)>=snapshot['source_revision']:return None
            break
    return emit(db,session,'transcript.interrupted',stream_id=stream_id,**snapshot,
        source_status='interrupted',status='interrupted',source_final=False,translation_revision=0,
        message='识别结束前未收到正式定稿；原文待确认，不能作为正式证据')


def unconfirmed_segments(db, session_id):
    """Caller must check session ownership; formal evidence queries stay unchanged."""
    confirmed=set(db.query(SegmentRevision.stream_id,SegmentRevision.sentence_id).filter_by(session_id=session_id).all())
    latest={}
    for event in db.query(Event).filter_by(session_id=session_id,type='transcript.interrupted').order_by(Event.event_seq):
        p=event.payload;key=(p.get('stream_id'),p.get('sentence_id'))
        if key not in confirmed and all(key):
            previous=latest.get(key)
            if not previous or p.get('source_revision',0)>=previous.get('source_revision',0):
                latest[key]={**p,'translation':'','translation_status':'pending','translation_final':False,
                             'source_status':'interrupted','source_final':False,'source_event_seq':event.event_seq}
    return sorted(latest.values(),key=lambda p:(p.get('start_ms',0),p.get('end_ms',0),p['sentence_id']))
