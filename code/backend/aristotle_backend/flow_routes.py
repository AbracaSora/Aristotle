"""Compose the learning, material, content and system route groups."""

from types import SimpleNamespace

from fastapi import Depends

from . import content_routes, learning_routes, material_routes, system_routes
from .api_access import administrator, current_user, get_db, maintainer, student
from .flow_support import chunks_view as chunks_view
from .flow_support import job_view as job_view
from .flow_support import provider_settings as provider_settings
from .flow_support import purge_material_derivatives as purge_material_derivatives
from .workflow import reject


def install_flow_routes(app, services):
    def content_role(user=Depends(current_user)):
        if user.role not in ("maintainer", "admin"):
            reject(403, "此操作需要维护权限")
        return user

    dependencies = SimpleNamespace(
        get_db=get_db,
        current_user=current_user,
        student=student,
        maintainer=maintainer,
        administrator=administrator,
        content_role=content_role,
    )
    dependencies.annotation_job = content_routes.install(app, dependencies, services)
    learning_routes.install(app, dependencies, services)
    material_routes.install(app, dependencies, services)
    system_routes.install(app, dependencies, services)
