"""Upgrade tombstones only: never import a provider or rewrite historical sources."""
from app.models import ProcessingTask, now

RETIRED_TASK_KIND = 'suggest_correction'
RETIRED_EVENT_TYPE = 'segment.suggestion'
ACTIVE_TASK_STATUSES = ('pending', 'retry', 'running')


def cancel_retired_task(task):
    # The executor already holds this row's lock. Do not lock other tasks here.
    if task.kind == RETIRED_TASK_KIND and task.status in ACTIVE_TASK_STATUSES:
        task.status = 'cancelled'
        task.error = '此任务类型已移除，不再执行。'
        task.updated_at = now()


def cancel_retired_tasks(db):
    # Keep payload, result, attempts and outbox for audit. Terminal historical
    # records, including accepted versions, are deliberately left untouched.
    return db.query(ProcessingTask).filter(
        ProcessingTask.kind == RETIRED_TASK_KIND,
        ProcessingTask.status.in_(ACTIVE_TASK_STATUSES),
    ).update({'status': 'cancelled', 'error': '此任务类型已移除，不再执行。',
              'updated_at': now()}, synchronize_session='fetch')
