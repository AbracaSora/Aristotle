"""Local configuration shared by the API, seed command and migration tools."""

import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.engine import make_url

PROJECT_ROOT = next(
    (path for path in Path(__file__).resolve().parents if (path / "pyproject.toml").is_file()), Path.cwd()
)
DEFAULT_DB = "postgresql+psycopg://aristotle:aristotle-local@127.0.0.1:5433/aristotle"


def database_url(value: str | None = None) -> str:
    # Explicit environment variables win over the repository's ignored .env file.
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    url = make_url(value or os.getenv("ARISTOTLE_DATABASE_URL", DEFAULT_DB))
    if url.drivername in {"postgres", "postgresql"}:
        url = url.set(drivername="postgresql+psycopg")
    if url.get_backend_name() not in {"postgresql", "sqlite"}:
        raise ValueError("Only PostgreSQL and explicit SQLite test/import databases are supported")
    return url.render_as_string(hide_password=False)
