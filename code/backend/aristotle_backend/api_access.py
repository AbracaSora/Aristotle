from dataclasses import dataclass
from typing import Never

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .db import (
    LoginSession,
    User,
)
from .security import token_hash

bearer = HTTPBearer(auto_error=False)


def fail(status: int, message: str) -> Never:
    raise HTTPException(status_code=status, detail=message)


def get_db(request: Request):
    with request.app.state.sessions() as session:
        yield session


def current_user(
    request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db=Depends(get_db)
):
    if not credentials or credentials.scheme.lower() != "bearer":
        fail(401, "请先登录")
    session = db.get(LoginSession, token_hash(credentials.credentials))
    if not session or session.expires_at <= request.app.state.clock():
        fail(401, "会话无效或已过期，请重新登录")
    user = db.get(User, session.user_id)
    request.state.auth_user_id = user.id
    return user


def maintainer(user=Depends(current_user)):
    if user.role != "maintainer":
        fail(403, "此操作需要内容维护者权限")
    return user


def student(user=Depends(current_user)):
    if user.role != "student":
        fail(403, "请使用学生账号执行学习操作")
    return user


@dataclass
class RequestSession:
    request: Request
    user: User
    db: Session


def session_for(role):
    def authorized(request: Request, user=Depends(role), db=Depends(get_db)):
        return RequestSession(request, user, db)

    return authorized


def administrator(user=Depends(current_user)):
    if user.role != "admin":
        fail(403, "此操作需要系统管理员权限")
    return user


student_session = session_for(student)
maintainer_session = session_for(maintainer)
current_user_session = session_for(current_user)
administrator_session = session_for(administrator)
