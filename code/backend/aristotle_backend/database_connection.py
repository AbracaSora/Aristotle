"""Open a configured database and enforce the deployed migration revision."""

from pathlib import Path

from sqlalchemy import MetaData, Table, create_engine, event, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker


def create_database_engine(url: str):
    parsed = make_url(url)
    sqlite = parsed.get_backend_name() == "sqlite"
    if sqlite and parsed.database and parsed.database != ":memory:":
        Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)
    kwargs = (
        {"connect_args": {"check_same_thread": False, "timeout": 15}}
        if sqlite
        else {"connect_args": {"connect_timeout": 5}}
    )
    engine = create_engine(url, pool_pre_ping=True, **kwargs)
    if sqlite:

        @event.listens_for(engine, "connect")
        def configure_sqlite(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=15000")

    return engine


def open_database(url: str):
    from .schema_contract import schema_head

    engine = create_database_engine(url)
    try:
        with engine.connect() as connection:
            # Startup never creates or changes tables. Deploy migrations explicitly.
            from sqlalchemy import inspect

            schema = (
                connection.exec_driver_sql("SELECT current_schema()").scalar_one()
                if connection.dialect.name == "postgresql"
                else None
            )
            if not inspect(connection).has_table("alembic_version", schema=schema):
                raise RuntimeError(
                    "Database is not migrated; run: uv run python -m aristotle_backend.migrations"
                )
            version_table = Table("alembic_version", MetaData(), schema=schema, autoload_with=connection)
            revisions = set(connection.execute(select(version_table.c.version_num)).scalars())
            if revisions != {schema_head()}:
                raise RuntimeError(
                    "Database schema is out of date; run: uv run python -m aristotle_backend.migrations"
                )
    except Exception:
        engine.dispose()
        raise
    return engine, sessionmaker(engine, expire_on_commit=False)
