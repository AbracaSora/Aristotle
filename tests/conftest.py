import pytest
from aristotle_backend.app import create_app
from aristotle_backend.seed import seed_demo
from fastapi.testclient import TestClient


@pytest.fixture
def app(tmp_path):
    application = create_app(f"sqlite:///{tmp_path / 'test.db'}")
    seed_demo(application.state.sessions)
    return application


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
