import os
from uuid import uuid4

import pytest
from aristotle_backend.app import create_app
from aristotle_backend.db import create_database_engine
from aristotle_backend.migrations import upgrade_database
from aristotle_backend.seed import seed_demo
from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url


@pytest.fixture
def test_database_url(tmp_path):
    url = os.getenv("ARISTOTLE_TEST_DATABASE_URL")
    if not url:
        yield f"sqlite:///{tmp_path / 'test.db'}"
        return
    parsed = make_url(url)
    if parsed.get_backend_name() != "postgresql":
        raise ValueError("ARISTOTLE_TEST_DATABASE_URL must point to a dedicated PostgreSQL test database")
    # Each test owns an isolated schema, never dropping shared/public tables.
    schema = "test_" + uuid4().hex
    engine = create_database_engine(url)
    with engine.begin() as con:
        con.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    options = (parsed.query.get("options", "") + f" -csearch_path={schema},public").strip()
    try:
        yield parsed.update_query_dict({"options": options}).render_as_string(hide_password=False)
    finally:
        with engine.begin() as con:
            con.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()


@pytest.fixture
def app(test_database_url):
    upgrade_database(test_database_url)
    application = create_app(test_database_url)
    seed_demo(application.state.sessions)
    try:
        yield application
    finally:
        application.state.engine.dispose()


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def login(client):
    def authenticate(username="student1"):
        response = client.post("/api/v1/auth/login", json={"username": username, "password": "demo-password"})
        assert response.status_code == 200, response.text
        return {"Authorization": "Bearer " + response.json()["access_token"]}

    return authenticate
