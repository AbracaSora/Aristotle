from uuid import uuid4

import pytest
from aristotle_backend.db import create_database_engine, open_database
from aristotle_backend.migrations import upgrade_database
from sqlalchemy.engine import make_url


def test_alembic_revision_cannot_fall_back_to_another_schema(test_database_url):
    parsed = make_url(test_database_url)
    if parsed.get_backend_name() != "postgresql":
        pytest.skip("PostgreSQL schema isolation")
    upgrade_database(test_database_url)
    engine = create_database_engine(test_database_url)
    empty = "empty_" + uuid4().hex
    with engine.begin() as con:
        con.exec_driver_sql(f'CREATE SCHEMA "{empty}"')
        existing = con.exec_driver_sql("SELECT current_schema()").scalar_one()
    url = parsed.update_query_dict({"options": f"-csearch_path={empty},{existing},public"}).render_as_string(
        hide_password=False
    )
    try:
        with pytest.raises(RuntimeError, match="not migrated"):
            open_database(url)
    finally:
        with engine.begin() as con:
            con.exec_driver_sql(f'DROP SCHEMA "{empty}" CASCADE')
        engine.dispose()
