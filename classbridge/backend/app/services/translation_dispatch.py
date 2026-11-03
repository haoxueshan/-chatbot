"""Local wake-up is advisory and only after commit; durable outbox is authoritative."""
from sqlalchemy import event
from sqlalchemy.orm import Session
from app.config import settings

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
