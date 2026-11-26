"""Copy a read-only SQLite snapshot into an empty, migrated business database."""

import argparse
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, inspect, select, text, tuple_
from sqlalchemy.engine import make_url
from sqlalchemy.sql.functions import count

from .config import PROJECT_ROOT, database_url
from .db import Base, open_database


def snapshot_sqlite(source: Path, directory: Path) -> Path:
    source = source.resolve(strict=True)
    directory.mkdir(parents=True, exist_ok=True)
    suffix = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    backup = directory / f"{source.stem}-{suffix}.db"
    backup.touch(mode=0o600, exist_ok=False)
    # SQLite's backup API includes committed WAL data and gives a consistent snapshot.
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as reader:
        with sqlite3.connect(backup) as writer:
            reader.backup(writer)
    return backup


def inspect_source(old):
    if old.exec_driver_sql("PRAGMA integrity_check").scalar_one() != "ok":
        raise ValueError("Source SQLite integrity check failed")
    if old.exec_driver_sql("PRAGMA foreign_key_check").first():
        raise ValueError("Source SQLite has broken foreign keys")
    schema = inspect(old)
    tables = set(schema.get_table_names()) - {"alembic_version"}
    if tables - set(Base.metadata.tables):
        raise ValueError("Source contains unknown tables; review its schema before importing")
    if not {"users", "graphs"} <= tables:
        raise ValueError("Source is not an Aristotle database")
    return schema, tables


def require_empty_target(new):
    if new.dialect.name == "postgresql":
        new.exec_driver_sql("SET LOCAL lock_timeout = '5s'")
        names = ", ".join(new.dialect.identifier_preparer.quote(t) for t in sorted(Base.metadata.tables))
        new.exec_driver_sql(f"LOCK TABLE {names} IN ACCESS EXCLUSIVE MODE")
    for table in Base.metadata.sorted_tables:
        if new.scalar(select(count()).select_from(table)):
            raise ValueError("Target contains business data; import into an empty migrated database")


def copy_table(old, new, table, schema):
    present = {c["name"] for c in schema.get_columns(table.name)}
    expected = set(table.columns.keys())
    optional = {"external_processing_allowed"} if table.name == "materials" else set()
    if present - expected or expected - present - optional:
        raise ValueError(f"Source table {table.name} has a different schema; refusing partial import")
    query = select(*(col for col in table.columns if col.name in present))
    copied = 0
    with old.execute(query) as rows:
        for group in rows.mappings().partitions(500):
            new.execute(table.insert(), [dict(row) for row in group])
            copied += len(group)
    verify_table(old, new, table, query)
    return copied


def verify_table(old, new, table, query):
    keys = list(table.primary_key.columns)
    key_names = [col.name for col in keys]
    verified = 0
    with old.execute(query) as rows:
        # Stay under the SQLite bind-variable limit, including tables with composite keys.
        for batch in rows.mappings().partitions(min(500, 999 // len(keys))):
            expected = {tuple(row[name] for name in key_names): row for row in batch}
            restored = new.execute(query.where(tuple_(*keys).in_(expected.keys()))).mappings()
            actual = {tuple(row[name] for name in key_names): row for row in restored}
            if actual != expected:
                raise ValueError(f"Verification failed for {table.name}; rolling back the entire import")
            verified += len(expected)
    if verified != new.scalar(select(count()).select_from(table)):
        raise ValueError(f"Row count differs for {table.name}; rolling back the entire import")


def copy_snapshot(old, new):
    schema, tables = inspect_source(old)
    require_empty_target(new)
    counts = {
        t.name: copy_table(old, new, t, schema) if t.name in tables else 0
        for t in Base.metadata.sorted_tables
    }
    if new.dialect.name == "postgresql":
        new.execute(
            text(
                "SELECT setval(pg_get_serial_sequence('graphs', 'sequence'), "
                "COALESCE((SELECT MAX(sequence) FROM graphs), 1), EXISTS(SELECT 1 FROM graphs))"
            )
        )
    return counts


def import_snapshot(source: Path, target_url: str) -> dict[str, int]:
    source = source.resolve(strict=True)
    reader = create_engine(
        "sqlite://", creator=lambda: sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)
    )
    try:
        target, _ = open_database(target_url)
        try:
            with reader.connect() as old, target.begin() as new:
                return copy_snapshot(old, new)
        finally:
            target.dispose()
    finally:
        reader.dispose()


def main():
    parser = argparse.ArgumentParser(description="Snapshot SQLite, then import and verify all business rows")
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--backup-dir", type=Path, default=PROJECT_ROOT / ".local" / "sqlite-backups")
    args = parser.parse_args()
    url = database_url()
    if make_url(url).get_backend_name() != "postgresql":
        parser.error("The destination must be PostgreSQL; set ARISTOTLE_DATABASE_URL")
    backup = snapshot_sqlite(args.source, args.backup_dir)
    print(f"Read-only source snapshot saved: {backup}")
    counts = import_snapshot(backup, url)
    for table, row_count in counts.items():
        print(f"{table}: {row_count} rows verified")
    print("Import committed; original SQLite file was not modified. Start the API against PostgreSQL.")


if __name__ == "__main__":
    main()
