"""Schema revision metadata; independent of database connections."""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def migration_config() -> Config:
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).with_name("migration_scripts")))
    return config


def schema_head() -> str:
    head = ScriptDirectory.from_config(migration_config()).get_current_head()
    if head is None:
        raise RuntimeError("Migration history has no schema head")
    return head
