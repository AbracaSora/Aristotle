"""Small SQLAlchemy adapter for pgvector; SQLite stores JSON only in isolated tests."""

import json
import math

from sqlalchemy.dialects.postgresql.base import ischema_names
from sqlalchemy.types import UserDefinedType


def checked_vector(value):
    if not isinstance(value, list) or not 1 <= len(value) <= 4096:
        raise ValueError("Invalid embedding dimensions")
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in value):
        raise ValueError("Embedding must contain finite numbers")
    if not any(value):
        raise ValueError("Zero embeddings cannot be used for cosine search")
    return [float(v) for v in value]


class Vector(UserDefinedType):
    cache_ok = True

    def get_col_spec(self, **kwargs):
        return "VECTOR"

    def bind_processor(self, dialect):
        return lambda value: json.dumps(checked_vector(value)) if value is not None else None

    def result_processor(self, dialect, coltype):
        return lambda value: json.loads(value) if isinstance(value, str) else value


# Teach SQLAlchemy/Alembic to reflect pgvector instead of treating it as an unknown type.
ischema_names.setdefault("vector", Vector)
