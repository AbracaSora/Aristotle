import os
import secrets
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api_access import (
    get_db,
    maintainer,
    student,
)
from .api_views import (
    active_graph,
    audit_record,
    learning_state,
    owned,
    task_view,
)
from .assistance_routes import install_assistance_routes
from .config import database_url as configured_database_url
from .curriculum_routes import install_curriculum_routes
from .db import (
    open_database,
)
from .flow_routes import install_flow_routes
from .legacy_content_routes import install_legacy_content_routes
from .schemas import (
    ErrorView,
)
from .security import hash_password
from .session_routes import install_session_routes
from .task_routes import install_task_routes


def create_app(database_url: str | None = None):
    from .runtime_logging import configure_logging

    configure_logging("api")
    engine, sessions = open_database(configured_database_url(database_url))
    from .deployment import validate_accounts

    try:
        validate_accounts(sessions)
    except Exception:
        engine.dispose()
        raise

    app = application(engine, sessions)
    install_session_routes(app)
    install_task_routes(app)
    install_legacy_content_routes(app)
    services = (learning_state, active_graph, task_view, owned, audit_record)
    install_curriculum_routes(app, get_db, student, maintainer)
    install_flow_routes(app, services)
    install_assistance_routes(app, services)
    app.state.dummy_hash = hash_password("unused-" + secrets.token_urlsafe(16))
    return app


def application(engine, sessions):
    @asynccontextmanager
    async def lifespan(_):
        from .model_jobs import expire_running

        expire_running(sessions)
        from .final_tests import expire_generating

        expire_generating(sessions)
        yield
        engine.dispose()

    app = FastAPI(
        title="Aristotle 408 后端原型",
        version="0.1.0",
        lifespan=lifespan,
        responses={code: {"model": ErrorView} for code in (401, 403, 404, 409, 422, 503)},
        description="408 预设题、先修解锁、持久化 AI 小测与旧诊断接口；PDF 仍为占位。",
    )
    app.state.sessions, app.state.engine, app.state.clock = sessions, engine, time.time
    from .migrations import schema_head

    app.state.schema_revision = schema_head()
    # Same-origin /demo works without CORS; Vue development ports are explicit.
    origins = os.getenv("ARISTOTLE_CORS_ORIGINS", "http://localhost:5173,http://localhost:5179").split(",")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    return app
