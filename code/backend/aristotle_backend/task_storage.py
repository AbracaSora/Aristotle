"""Persist the assigned question order and task snapshot in the caller's transaction."""

from .db import TaskQuestion


def store_task(db, task):
    db.add(task)
    db.flush()
    for position, key in enumerate(task.decision["question_keys"]):
        db.add(TaskQuestion(task_id=task.id, question_key=key, position=position))
