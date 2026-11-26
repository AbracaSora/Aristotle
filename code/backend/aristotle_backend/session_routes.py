import secrets
from pathlib import Path
from uuid import uuid4

from aristotle_core.policy import POLICY_VERSION
from fastapi import Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .api_access import bearer, current_user, fail, get_db
from .db import (
    Audit,
    LoginSession,
    User,
)
from .schemas import (
    Login,
    LoginView,
    UserView,
)
from .security import token_hash, verify_password


def install_session_routes(app):
    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        actor_id = getattr(request.state, "auth_user_id", None)
        if exc.status_code == 403 and actor_id:
            with request.app.state.sessions() as db:
                db.add(
                    Audit(
                        id=str(uuid4()),
                        actor_id=actor_id,
                        action="access_denied",
                        target=request.method + " " + request.url.path,
                        at=request.app.state.clock(),
                    )
                )
                db.commit()
        return JSONResponse(status_code=exc.status_code, content={"error": {"message": exc.detail}})

    @app.exception_handler(RequestValidationError)
    async def validation_error(_, exc):
        # Do not echo passwords, private materials or raw input back into error bodies.
        fields = [{"location": list(e["loc"]), "message": e["msg"], "type": e["type"]} for e in exc.errors()]
        return JSONResponse(status_code=422, content={"error": {"message": "输入校验失败", "fields": fields}})

    @app.exception_handler(IntegrityError)
    async def conflict_error(_, exc):
        return JSONResponse(
            status_code=409, content={"error": {"message": "记录已存在或版本冲突，请刷新后重试"}}
        )

    @app.get("/health", tags=["运行状态"])
    def health(db=Depends(get_db)):
        db.execute(select(1))
        from .providers import ProviderFailure, provider_config

        try:
            generation_ready = provider_config("generation").configured
            embedding_ready = provider_config("embedding").configured
        except ProviderFailure:
            generation_ready = embedding_ready = False
        return {
            "status": "ok",
            "database": app.state.engine.dialect.name,
            "version": "0.1.0",
            "policy_version": POLICY_VERSION,
            "schema_revision": app.state.schema_revision,
            "external_model": "configured" if generation_ready else "not_configured",
            "embedding": "configured" if embedding_ready else "not_configured",
        }

    @app.get("/", include_in_schema=False)
    @app.get("/demo", include_in_schema=False)
    def demo():
        return FileResponse(Path(__file__).parent / "static" / "demo.html")

    @app.post("/api/v1/auth/login", response_model=LoginView, tags=["会话"])
    def login(body: Login, request: Request, db=Depends(get_db)):
        user = db.scalar(select(User).where(User.username == body.username))
        # Use an equally expensive dummy hash to reduce username timing leakage.
        password_hash = user.password_hash if user else app.state.dummy_hash
        valid = verify_password(body.password, password_hash)
        if not user or not valid:
            fail(401, "用户名或密码错误")
        token = secrets.token_urlsafe(32)
        expires = request.app.state.clock() + 8 * 60 * 60
        db.add(LoginSession(token_hash=token_hash(token), user_id=user.id, expires_at=expires))
        db.commit()
        return {
            "access_token": token,
            "token_type": "bearer",
            "expires_at": expires,
            "user": {"id": user.id, "username": user.username, "role": user.role},
        }

    @app.get("/api/v1/auth/me", response_model=UserView, tags=["会话"])
    def me(user=Depends(current_user)):
        return {"id": user.id, "username": user.username, "role": user.role}

    @app.post("/api/v1/auth/logout", status_code=204, tags=["会话"])
    def logout(
        credentials: HTTPAuthorizationCredentials = Depends(bearer),
        user=Depends(current_user),
        db=Depends(get_db),
    ):
        db.delete(db.get(LoginSession, token_hash(credentials.credentials)))
        db.commit()
        return Response(status_code=204)
