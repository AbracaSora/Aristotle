"""Run on the host when the agent's command sandbox cannot reach local PostgreSQL.

Optional SQLite import is explicit, refuses nonempty targets, and preserves source data.
Integration tests run in random schemas of a separate database, never in the business DB.
"""

import argparse
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from aristotle_backend.config import PROJECT_ROOT, database_url
from aristotle_backend.db import Base, open_database
from aristotle_backend.import_sqlite import import_snapshot, snapshot_sqlite
from aristotle_backend.migrations import upgrade_database
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url


def main():
    parser = argparse.ArgumentParser(
        description="Verify the real PostgreSQL migration and save a redacted log"
    )
    parser.add_argument(
        "--import-sqlite", type=Path, help="Explicitly import this source into an empty target"
    )
    parser.add_argument("--test-database", help="Existing test database name; defaults to <business DB>_test")
    args = parser.parse_args()
    url = database_url()
    parsed = make_url(url)
    if parsed.get_backend_name() != "postgresql":
        parser.error("Configure a PostgreSQL ARISTOTLE_DATABASE_URL first")
    if not parsed.database:
        parser.error("ARISTOTLE_DATABASE_URL must include an explicit database name")
    test_name = args.test_database or parsed.database + "_test"
    if test_name == parsed.database or len(test_name.encode()) > 63:
        parser.error("Use a separate test database name of at most 63 UTF-8 bytes")
    log_dir = PROJECT_ROOT / ".local"
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / "postgresql-verification.log"
    log_path.touch(mode=0o600, exist_ok=True)
    log_path.chmod(0o600)
    secrets = [url, str(parsed), parsed.password or ""]

    with log_path.open("w") as log:

        def report(message):
            message = str(message)
            for secret in secrets:
                if secret:
                    message = message.replace(secret, "[redacted]")
            print(message, flush=True)
            print(message, file=log, flush=True)

        report("PostgreSQL host verification " + datetime.now(timezone.utc).isoformat())
        try:
            upgrade_database(url)
            report("PASS: migrations applied")
            if args.import_sqlite:
                backup = snapshot_sqlite(args.import_sqlite, log_dir / "sqlite-backups")
                report("SQLite snapshot: " + str(backup))
                counts = import_snapshot(backup, url)
                report("PASS: imported and verified all rows: " + str(counts))
            engine, _ = open_database(url)
            try:
                with engine.connect() as con:
                    report("Database engine: " + engine.dialect.name)
                    report(
                        "Schema revision: "
                        + con.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                    )
                    counts = {
                        t.name: con.scalar(select(func.count()).select_from(t))
                        for t in Base.metadata.sorted_tables
                    }
                    report("Business row counts: " + str(counts))
                # Creation is outside a transaction; only the separate test DB is created.
                with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as con:
                    exists = con.scalar(
                        select(text("1")).select_from(text("pg_database")).where(text("datname = :name")),
                        {"name": test_name},
                    )
                    if not exists:
                        quoted = con.dialect.identifier_preparer.quote(test_name)
                        con.exec_driver_sql(f"CREATE DATABASE {quoted}")
                    report("Dedicated test database: " + test_name)
            finally:
                engine.dispose()
            test_url = parsed.set(database=test_name).render_as_string(hide_password=False)
            secrets.append(test_url)
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "tests/integration"],
                cwd=PROJECT_ROOT,
                env={**os.environ, "ARISTOTLE_TEST_DATABASE_URL": test_url},
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            report(result.stdout)
            if result.returncode:
                raise RuntimeError("PostgreSQL integration tests failed; see the test output above")
            report("PASS: real PostgreSQL integration tests; business data retained")
        except Exception as exc:
            report(f"FAILED ({type(exc).__name__}): {exc}")
            report(
                "Existing source/business data was not deleted. If import already completed, rerun without --import-sqlite."
            )
            return 1
        finally:
            report("Verification log: " + str(log_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
