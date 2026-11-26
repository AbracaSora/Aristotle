"""Fail production startup when known public demonstration accounts remain enabled."""

from sqlalchemy import select

from .config import deployment_mode
from .db import User
from .security import verify_password


def validate_accounts(sessions):
    if deployment_mode() != "production":
        return
    with sessions() as db:
        users = db.scalars(select(User).where(User.username.in_(("student1", "student2", "editor", "admin"))))
        if any(verify_password("demo-password", user.password_hash) for user in users):
            raise RuntimeError("Production contains enabled accounts using the public demo credential")
