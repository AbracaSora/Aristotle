"""Known development credentials and demo seeding must not enter production mode."""

import pytest
from aristotle_backend.config import database_url
from aristotle_backend.db import User
from aristotle_backend.seed import seed_demo
from sqlalchemy import select


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://aristotle:aristotle-local@localhost/db",
        "postgresql://user@localhost/db",
        "sqlite:///:memory:",
    ],
)
def test_production_rejects_development_database_configuration(monkeypatch, url):
    monkeypatch.setenv("ARISTOTLE_ENV", "production")
    with pytest.raises(ValueError, match="Production"):
        database_url(url)


def test_production_accepts_explicit_non_demo_database_password(monkeypatch):
    monkeypatch.setenv("ARISTOTLE_ENV", "production")
    url = database_url("postgresql://fixture-user:fixture-non-demo@localhost/db")
    assert url.startswith("postgresql+psycopg://")


def test_demo_seed_is_blocked_in_production_without_changing_accounts(app, monkeypatch):
    with app.state.sessions() as db:
        before = list(db.scalars(select(User.id)))
    monkeypatch.setenv("ARISTOTLE_ENV", "production")
    with pytest.raises(RuntimeError, match="production"):
        seed_demo(app.state.sessions)
    with app.state.sessions() as db:
        assert list(db.scalars(select(User.id))) == before


def test_production_existing_default_accounts_are_rejected(app, monkeypatch):
    from aristotle_backend.deployment import validate_accounts

    monkeypatch.setenv("ARISTOTLE_ENV", "production")
    with pytest.raises(RuntimeError, match="public demo credential"):
        validate_accounts(app.state.sessions)


@pytest.mark.parametrize("entry", ["design", "resource"])
def test_other_demo_entrypoints_cannot_bypass_production_guard(app, monkeypatch, entry):
    from aristotle_backend.design_seed import seed_design_flow
    from aristotle_backend.resource_seed import import_resource_demo

    monkeypatch.setenv("ARISTOTLE_ENV", "production")
    with pytest.raises(RuntimeError, match="production"):
        (seed_design_flow if entry == "design" else import_resource_demo)(app.state.sessions)
