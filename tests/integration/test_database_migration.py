import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from aristotle_backend import config as settings
from aristotle_backend.app import create_app
from aristotle_backend.config import database_url
from aristotle_backend.db import Base, Graph, Material, create_database_engine, open_database
from aristotle_backend.design_seed import seed_design_flow
from aristotle_backend.import_sqlite import import_snapshot, snapshot_sqlite
from aristotle_backend.migrations import migration_config, schema_head, upgrade_database
from aristotle_backend.seed import seed_demo
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import IntegrityError


def test_unmigrated_database_fails_startup_without_silently_creating_tables(tmp_path):
    url = f"sqlite:///{tmp_path / 'blank.db'}"
    with pytest.raises(RuntimeError, match="not migrated"):
        create_app(url)
    engine = create_database_engine(url)
    with engine.connect() as con:
        assert inspect(con).get_table_names() == []
    engine.dispose()


def test_schema_upgrade_is_repeatable_and_matches_models(test_database_url):
    upgrade_database(test_database_url)
    upgrade_database(test_database_url)
    engine, sessions = open_database(test_database_url)
    try:
        with engine.connect() as con:
            assert set(inspect(con).get_table_names()) == set(Base.metadata.tables) | {"alembic_version"}
            assert compare_metadata(MigrationContext.configure(con), Base.metadata) == []
        assert seed_demo(sessions)
        assert not seed_demo(sessions)
    finally:
        engine.dispose()


def test_outdated_schema_fails_startup(tmp_path):
    url = f"sqlite:///{tmp_path / 'outdated.db'}"
    upgrade_database(url)
    engine = create_database_engine(url)
    with engine.begin() as con:
        con.execute(text("UPDATE alembic_version SET version_num='old_revision'"))
    engine.dispose()
    with pytest.raises(RuntimeError, match="out of date"):
        create_app(url)


def test_sqlite_import_preserves_all_rows_source_and_next_graph_id(tmp_path, test_database_url):
    source = tmp_path / "source.db"
    url = f"sqlite:///{source}"
    upgrade_database(url)
    old_engine, sessions = open_database(url)
    seed_demo(sessions)
    seed_design_flow(sessions)
    with sessions() as db:
        db.add(Material(id="private", user_id="student1", title="笔记", text="原文", knowledge_id="stack"))
        db.commit()
    old_engine.dispose()
    before = source.read_bytes()
    snapshot = snapshot_sqlite(source, tmp_path / "backups")
    upgrade_database(test_database_url)
    counts = import_snapshot(snapshot, test_database_url)
    assert source.read_bytes() == before
    assert len(counts) == len(Base.metadata.tables) and counts["users"] == 4 and counts["materials"] == 1
    engine, destination = open_database(test_database_url)
    try:
        with destination() as db:
            assert db.get(Material, "private").text == "原文"
            last = db.scalar(select(func.max(Graph.sequence)))
            graph = Graph(version="after-import", nodes=[])
            db.add(graph)
            db.commit()
            assert graph.sequence > last
        with pytest.raises(ValueError, match="Target contains"):
            import_snapshot(snapshot, test_database_url)
    finally:
        engine.dispose()


def test_import_schema_failure_rolls_back_every_table(tmp_path, test_database_url):
    source = tmp_path / "broken.db"
    url = f"sqlite:///{source}"
    upgrade_database(url)
    engine, sessions = open_database(url)
    seed_demo(sessions)
    with engine.begin() as con:
        con.exec_driver_sql("ALTER TABLE users ADD COLUMN unexpected TEXT")
    engine.dispose()
    upgrade_database(test_database_url)
    with pytest.raises(ValueError, match="different schema"):
        import_snapshot(source, test_database_url)
    engine, _ = open_database(test_database_url)
    with engine.connect() as con:
        assert all(con.scalar(select(func.count()).select_from(t)) == 0 for t in Base.metadata.sorted_tables)
    engine.dispose()


def test_initial_migration_can_be_reversed_on_disposable_database(tmp_path):
    url = f"sqlite:///{tmp_path / 'reverse.db'}"
    upgrade_database(url)
    engine = create_database_engine(url)
    with engine.begin() as con:
        config = migration_config()
        config.attributes["connection"] = con
        command.downgrade(config, "base")
        assert set(inspect(con).get_table_names()) == {"alembic_version"}
    engine.dispose()


def test_postgresql_schema_sql_is_renderable_offline(tmp_path):
    path = tmp_path / "postgresql.sql"
    with path.open("w") as output:
        config = migration_config()
        config.output_buffer = output
        config.attributes["url"] = "postgresql+psycopg://unused:unused@127.0.0.1/unused"
        command.upgrade(config, "head", sql=True)
    sql = path.read_text()
    assert "CREATE TABLE graphs" in sql
    assert "SERIAL" in sql and "FOREIGN KEY" in sql
    assert schema_head() in sql and sql.count("CREATE TABLE") == len(Base.metadata.tables) + 1
    assert "CREATE EXTENSION IF NOT EXISTS vector" in sql and "vector VECTOR" in sql


def test_postgres_url_uses_psycopg_and_explicit_sqlite_is_preserved():
    assert database_url("postgresql://user:p%40ss@localhost/db").startswith("postgresql+psycopg://")
    assert database_url("sqlite:///:memory:") == "sqlite:///:memory:"


def test_default_is_postgresql_and_env_file_does_not_override_shell(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "PROJECT_ROOT", tmp_path)
    monkeypatch.delenv("ARISTOTLE_DATABASE_URL", raising=False)
    assert database_url().startswith("postgresql+psycopg://")
    (tmp_path / ".env").write_text("ARISTOTLE_DATABASE_URL=postgresql://env-user:local@localhost/file_db\n")
    assert database_url().endswith("/file_db")
    monkeypatch.setenv("ARISTOTLE_DATABASE_URL", "postgresql://shell-user:local@localhost/shell_db")
    assert database_url().endswith("/shell_db")


def test_health_identifies_actual_database(client, app):
    assert client.get("/health").json()["database"] == app.state.engine.dialect.name


def test_old_eleven_table_source_can_be_imported_without_fabricating_new_records(tmp_path, test_database_url):
    path = tmp_path / "legacy.db"
    url = f"sqlite:///{path}"
    upgrade_database(url)
    engine, sessions = open_database(url)
    seed_demo(sessions)
    legacy = {
        "users",
        "login_sessions",
        "graphs",
        "questions",
        "annotations",
        "reviews",
        "tasks",
        "task_questions",
        "attempts",
        "materials",
        "audit",
    }
    with engine.begin() as con:
        for table in reversed(Base.metadata.sorted_tables):
            if table.name not in legacy:
                table.drop(con)
    engine.dispose()
    upgrade_database(test_database_url)
    counts = import_snapshot(path, test_database_url)
    assert counts["users"] == 3 and counts["questions"] == 12
    assert all(counts[name] == 0 for name in set(Base.metadata.tables) - legacy)


def test_foreign_key_constraints_are_enforced(test_database_url):
    upgrade_database(test_database_url)
    engine, sessions = open_database(test_database_url)
    try:
        with sessions() as db:
            db.add(Material(id="orphan", user_id="missing", title="x", text="x", knowledge_id="stack"))
            with pytest.raises(IntegrityError):
                db.commit()
    finally:
        engine.dispose()
