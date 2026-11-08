"""Copy a read-only SQLite snapshot into an empty, migrated business database."""

import argparse
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.engine import make_url

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


def import_snapshot(source: Path, target_url: str) -> dict[str, int]:
    source = source.resolve(strict=True)
    reader = create_engine(
        "sqlite://",
        creator=lambda: sqlite3.connect(source.as_uri() + "?mode=ro", uri=True),
    )
    target = None
    try:
        target, _ = open_database(target_url)
        with reader.connect() as old, target.begin() as new:
            if old.exec_driver_sql("PRAGMA integrity_check").scalar_one() != "ok":
                raise ValueError("Source SQLite integrity check failed")
            if old.exec_driver_sql("PRAGMA foreign_key_check").first():
                raise ValueError("Source SQLite has broken foreign keys")
            metadata = inspect(old)
            old_tables = set(metadata.get_table_names()) - {"alembic_version"}
            known = set(Base.metadata.tables)
            if old_tables - known:
                raise ValueError("Source contains unknown tables; review its schema before importing")
            if not {"users", "graphs"} <= old_tables:
                raise ValueError("Source is not an Aristotle database")
            if new.dialect.name == "postgresql":
                # Keep API writes and other imports from racing the empty-target check.
                new.exec_driver_sql("SET LOCAL lock_timeout = '5s'")
                names = ", ".join(new.dialect.identifier_preparer.quote(t) for t in sorted(known))
                new.exec_driver_sql(f"LOCK TABLE {names} IN ACCESS EXCLUSIVE MODE")
            for table in Base.metadata.sorted_tables:
                if new.scalar(select(func.count()).select_from(table)):
                    raise ValueError("Target contains business data; import into an empty migrated database")
            counts = {}
            for table in Base.metadata.sorted_tables:
                if table.name not in old_tables:
                    counts[table.name] = 0
                    continue
                columns = {c["name"] for c in metadata.get_columns(table.name)}
                permitted_missing = {"external_processing_allowed"} if table.name == "materials" else set()
                if (
                    columns - set(table.columns.keys())
                    or set(table.columns.keys()) - columns - permitted_missing
                ):
                    raise ValueError(
                        f"Source table {table.name} has a different schema; refusing partial import"
                    )
                source_columns = [c for c in table.columns if c.name in columns]
                rows = [dict(row) for row in old.execute(select(*source_columns)).mappings()]
                if rows:
                    new.execute(table.insert(), rows)
                order = list(table.primary_key.columns)
                copied = [
                    dict(row) for row in new.execute(select(*source_columns).order_by(*order)).mappings()
                ]
                original = [
                    dict(row) for row in old.execute(select(*source_columns).order_by(*order)).mappings()
                ]
                if copied != original:
                    raise ValueError(f"Verification failed for {table.name}; rolling back the entire import")
                counts[table.name] = len(rows)
            if new.dialect.name == "postgresql":
                # Explicitly copied serial IDs must not collide with the next graph publication.
                new.execute(
                    text(
                        "SELECT setval(pg_get_serial_sequence('graphs', 'sequence'), "
                        "COALESCE((SELECT MAX(sequence) FROM graphs), 1), EXISTS(SELECT 1 FROM graphs))"
                    )
                )
        return counts
    finally:
        reader.dispose()
        if target is not None:
            target.dispose()


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
    for table, count in counts.items():
        print(f"{table}: {count} rows verified")
    print("Import committed; original SQLite file was not modified. Start the API against PostgreSQL.")


if __name__ == "__main__":
    main()
