"""Test in a separate PostgreSQL database BEFORE migrating the business database.

Never imports demo data or SQLite and never drops business tables. Reports contain
counts only, not student data, model keys or database credentials.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

from aristotle_backend.config import database_url
from aristotle_backend.db import create_database_engine
from aristotle_backend.migrations import upgrade_database
from sqlalchemy import MetaData, Table, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.sql.functions import count

ROOT = Path(__file__).resolve().parents[1]


def row_counts(engine):
    with engine.connect() as connection:
        metadata = MetaData()
        return {
            name: connection.scalar(
                select(count()).select_from(Table(name, metadata, autoload_with=connection))
            )
            for name in inspect(connection).get_table_names()
            if name != "alembic_version"
        }


def main():
    url = make_url(database_url())
    if url.get_backend_name() != "postgresql" or not url.database:
        raise ValueError("An explicit PostgreSQL business database is required")
    engine = create_database_engine(url)
    test_name = url.database + "_test"
    if len(test_name.encode()) > 63:
        raise ValueError("Dedicated test database name exceeds PostgreSQL limit")
    output = ROOT / "docs/software/quality_evidence/after"
    output.mkdir(parents=True, exist_ok=True)
    try:
        before = row_counts(engine)
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as con:
            exists = con.scalar(text("SELECT 1 FROM pg_database WHERE datname=:name"), {"name": test_name})
            if not exists:
                con.exec_driver_sql("CREATE DATABASE " + con.dialect.identifier_preparer.quote(test_name))
        test_url = url.set(database=test_name).render_as_string(hide_password=False)
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "tests/integration"],
            cwd=ROOT,
            env={**os.environ, "ARISTOTLE_TEST_DATABASE_URL": test_url},
            capture_output=True,
            text=True,
            check=False,
        )
        # Defensive redaction even for driver failures.
        log = result.stdout + result.stderr
        for secret in (test_url, url.render_as_string(hide_password=False), url.password):
            if secret:
                log = log.replace(secret, "[redacted]")
        (output / "postgresql-tests.txt").write_text(log)
        if result.returncode:
            print("PostgreSQL tests failed; business schema was not changed. See postgresql-tests.txt")
            return result.returncode
        upgrade_database(url.render_as_string(hide_password=False))
        after = row_counts(engine)
        if any(after.get(table) != rows for table, rows in before.items()):
            raise RuntimeError("Business row-count mismatch; inspect migration before further writes")
        with engine.connect() as con:
            revision = con.scalar(text("SELECT version_num FROM alembic_version"))
        (output / "business-migration.json").write_text(
            json.dumps(
                {
                    "revision": revision,
                    "before": before,
                    "after": after,
                    "old_rows_preserved": True,
                    "dedicated_test_database": test_name,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )
        print(
            "PASS: isolated PostgreSQL tests, incremental migration, original business row counts preserved."
        )
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
