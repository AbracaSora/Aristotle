"""Explicit schema upgrade command; the server only checks the applied revision."""

import argparse
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from .config import database_url
from .db import create_database_engine


def migration_config() -> Config:
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).with_name("migration_scripts")))
    return config


def schema_head() -> str:
    return ScriptDirectory.from_config(migration_config()).get_current_head()


def upgrade_database(url: str, revision: str = "head") -> None:
    engine = create_database_engine(url)
    try:
        with engine.begin() as connection:
            if (
                connection.dialect.name == "postgresql"
                and not connection.exec_driver_sql(
                    "SELECT EXISTS(SELECT 1 FROM pg_available_extensions WHERE name = 'vector')"
                ).scalar_one()
            ):
                raise RuntimeError(
                    "PostgreSQL has no pgvector extension. Run docker compose up -d --wait postgres with the updated pgvector image; preserve the existing data volume."
                )
            config = migration_config()
            config.attributes["connection"] = connection
            command.upgrade(config, revision)
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(description="Apply reviewed database migrations (no demo data)")
    parser.add_argument(
        "--sql", action="store_true", help="Print PostgreSQL migration SQL without connecting"
    )
    args = parser.parse_args()
    if args.sql:
        config = migration_config()
        config.attributes["url"] = database_url()
        command.upgrade(config, "head", sql=True)
    else:
        upgrade_database(database_url())
        print("Database schema is at head; no demo data was inserted.")


if __name__ == "__main__":
    main()
