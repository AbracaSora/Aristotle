from uuid import uuid4

from fastapi import Depends, Request
from sqlalchemy import select

from .api_access import administrator_session
from .db import (
    LoginSession,
    SystemSetting,
    User,
)
from .flow_schemas import (
    ProviderSettings,
    RoleChange,
)
from .flow_support import provider_settings
from .workflow import (
    reject,
)


def install(app, dependencies, services):
    get_db = dependencies.get_db
    administrator = dependencies.administrator
    state_of, graph_of, task_view, owned, audit_record = services

    @app.get("/api/v1/admin/provider-settings", tags=["系统管理"])
    def get_settings(user=Depends(administrator), db=Depends(get_db)):
        return {
            "settings": provider_settings(db),
            "implementation": "runtime-config",
            "real_provider": "openai-compatible",
        }

    @app.patch("/api/v1/admin/provider-settings", tags=["系统管理"])
    def set_settings(
        body: ProviderSettings, request: Request, user=Depends(administrator), db=Depends(get_db)
    ):
        data = {**body.model_dump(), "revision": str(uuid4())}
        row = db.get(SystemSetting, "provider")
        if row:
            row.data = data
        else:
            db.add(SystemSetting(key="provider", data=data))
        db.add(audit_record(user, "provider_config_changed", data["revision"], request.app.state.clock()))
        db.commit()
        return {"settings": data, "implementation": "runtime-config"}

    @app.post("/api/v1/admin/providers/live", tags=["系统管理"])
    def live_provider_status(user=Depends(administrator)):
        from .providers import provider_config

        cfg = provider_config("generation")
        if not cfg.configured:
            reject(501, "真实模型尚未配置，请在后端环境变量中填写地址、模型名和密钥")
        return {
            "implementation": "openai-compatible",
            "model": cfg.model,
            "configured": True,
            "notice": "配置已就绪；此接口不发起付费调用，标注需显式建立任务。",
        }

    @app.get("/api/v1/admin/users", tags=["系统管理"])
    def users(user=Depends(administrator), db=Depends(get_db)):
        return {
            "items": [{"id": u.id, "username": u.username, "role": u.role} for u in db.scalars(select(User))]
        }

    @app.patch("/api/v1/admin/users/{user_id}/role", tags=["系统管理"])
    def change_role(user_id: str, body: RoleChange, ctx=Depends(administrator_session)):
        row = ctx.db.get(User, user_id)
        if not row:
            reject(404, "用户不存在")
        if row.id == ctx.user.id:
            reject(409, "原型中不允许修改当前管理员自身角色")
        row.role = body.role
        for session in ctx.db.scalars(select(LoginSession).where(LoginSession.user_id == row.id)):
            ctx.db.delete(session)
        ctx.db.add(
            audit_record(ctx.user, "role_changed", row.id + ":" + body.role, ctx.request.app.state.clock())
        )
        ctx.db.commit()
        return {"id": row.id, "role": row.role, "sessions_revoked": True}
