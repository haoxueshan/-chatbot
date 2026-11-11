"""Local wake-up is advisory and only after commit; durable outbox is authoritative."""
from sqlalchemy import event
from sqlalchemy.orm import Session
from app.config import settings


def handoff_pending(payload, current):
    """Durable lease only: workers never share asyncio objects with a capture."""
    from datetime import datetime
    lease=payload.get('preview_handoff')
    if not lease:return False
    try:return current < datetime.fromisoformat(lease['deadline'])
    except (KeyError,TypeError,ValueError):return False


def finish_handoff(db, task_id, request_id, candidate):
    from sqlalchemy import select
    from app.models import ProcessingTask, Outbox
    task=db.execute(select(ProcessingTask).where(ProcessingTask.id==task_id).with_for_update()).scalar_one_or_none()
    if not task or task.status not in ('pending','retry'):return False
    lease=task.payload.get('preview_handoff') or {}
    if lease.get('request_id')!=request_id:return False
    payload={k:v for k,v in task.payload.items() if k!='preview_handoff'}
    if candidate is not None:payload['preview_candidate']=candidate
    else:payload['preview_failed']=True
    task.payload=payload
    box=db.query(Outbox).filter_by(task_id=task.id).first()
    if box:box.dispatched_at=None
    db.info['translation_pending']=True
    db.commit()
    return True

worker_loop = None
worker_wakeup = None


@event.listens_for(Session, 'after_commit')
def committed(db):
    if not db.info.pop('translation_pending', False): return
    if settings.incremental_translation_enabled and worker_loop and not worker_loop.is_closed() and worker_wakeup:
        worker_loop.call_soon_threadsafe(worker_wakeup.set)


@event.listens_for(Session, 'after_rollback')
def rolled_back(db):
    db.info.pop('translation_pending', None)
