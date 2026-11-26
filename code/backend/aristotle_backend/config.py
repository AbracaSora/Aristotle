"""Local configuration shared by the API, seed command and migration tools."""

import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.engine import make_url

PROJECT_ROOT = next(
    (path for path in Path(__file__).resolve().parents if (path / "pyproject.toml").is_file()), Path.cwd()
)
DEFAULT_DB = "postgresql+psycopg://aristotle:aristotle-local@127.0.0.1:5433/aristotle"


def deployment_mode() -> str:
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    mode = os.getenv("ARISTOTLE_ENV", "development")
    if mode not in {"development", "test", "production"}:
        raise ValueError("ARISTOTLE_ENV must be development, test or production")
    return mode


def require_demo_mode() -> None:
    if deployment_mode() == "production":
        raise RuntimeError("Demo data import is disabled in production")


def validate_production_database(url) -> None:
    if deployment_mode() != "production":
        return
    if url.get_backend_name() != "postgresql":
        raise ValueError("Production requires PostgreSQL")
    if (
        not url.password
        or len(url.password) < 12
        or url.password in {"aristotle-local", "demo-password", "ci-only"}
    ):
        raise ValueError("Production requires an explicit non-demo database credential")


def database_url(value: str | None = None) -> str:
    # Explicit environment variables win over the repository's ignored .env file.
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    url = make_url(value or os.getenv("ARISTOTLE_DATABASE_URL") or DEFAULT_DB)
    if url.drivername in {"postgres", "postgresql"}:
        url = url.set(drivername="postgresql+psycopg")
    if url.get_backend_name() not in {"postgresql", "sqlite"}:
        raise ValueError("Only PostgreSQL and explicit SQLite test/import databases are supported")
    validate_production_database(url)
    return url.render_as_string(hide_password=False)
