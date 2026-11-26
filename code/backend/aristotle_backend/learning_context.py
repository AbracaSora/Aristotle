"""Server-owned learning action and the evidence snapshot used to plan it."""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from .db import Graph, User


@dataclass(frozen=True)
class LearnerAction:
    db: Session
    user: User
    now: float


@dataclass(frozen=True)
class LearningRun(LearnerAction):
    graph: Graph
    attempts: list
    states: list


@dataclass(frozen=True)
class Activity:
    name: str
    round_id: str | None = None
    resume_level: str | None = None
