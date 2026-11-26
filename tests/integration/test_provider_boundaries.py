"""Transport, quota, output and deadline failures never call real model services."""

from dataclasses import replace

import httpx
import pytest
from aristotle_backend import providers
from aristotle_backend.db import ModelCall, User
from aristotle_backend.providers import GenerationPrompt, ModelContext, ModelRequest
from sqlalchemy import select


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(providers, "load_dotenv", lambda *args, **kwargs: None)
    for kind in ("LLM", "EMBEDDING"):
        monkeypatch.setenv(f"ARISTOTLE_{kind}_BASE_URL", "https://fixture.invalid/v1")
        monkeypatch.setenv(f"ARISTOTLE_{kind}_MODEL", "fixture")
        monkeypatch.setenv(f"ARISTOTLE_{kind}_API_KEY", "fixture-key")
    monkeypatch.setenv("ARISTOTLE_MODEL_RETRIES", "0")
    monkeypatch.setenv("ARISTOTLE_MODEL_TIMEOUT", "30")
    monkeypatch.setenv("ARISTOTLE_MODEL_DAILY_LIMIT", "200")
    monkeypatch.setenv("ARISTOTLE_LLM_TOKEN_FIELD", "max_tokens")
    monkeypatch.setenv("ARISTOTLE_EMBEDDING_DIMENSIONS", "3")


@pytest.mark.parametrize(
    "variable,value",
    [
        ("ARISTOTLE_MODEL_TIMEOUT", "0"),
        ("ARISTOTLE_MODEL_RETRIES", "2"),
        ("ARISTOTLE_MODEL_DAILY_LIMIT", "0"),
        ("ARISTOTLE_LLM_TOKEN_FIELD", "unknown"),
        ("ARISTOTLE_LLM_BASE_URL", "https://user:password@fixture.invalid/v1"),
        ("ARISTOTLE_LLM_BASE_URL", "ftp://fixture.invalid/v1"),
    ],
)
def test_invalid_model_config_is_redacted(configured, monkeypatch, variable, value):
    monkeypatch.setenv(variable, value)
    with pytest.raises(providers.ProviderFailure) as caught:
        providers.provider_config("generation")
    assert caught.value.code == "invalid_config"
    assert value not in str(caught.value)


def call(db, transport, *, cfg=None):
    cfg = cfg or providers.ProviderConfig(
        "generation", "https://fixture.invalid/v1", "fixture", "fixture-key"
    )
    user = db.scalar(select(User))
    return providers.request_model(
        ModelContext(db, user.id, transport), "annotation", cfg, ModelRequest({}, lambda body: body)
    )


@pytest.mark.parametrize(
    "status,body,expected",
    [
        (401, {}, "request_rejected"),
        (503, {}, "unavailable"),
        (429, {}, "rate_limited"),
        (200, [], "invalid_output"),
        (200, {"usage": []}, "invalid_output"),
    ],
)
def test_http_failure_is_durable_and_redacted(app, status, body, expected):
    with app.state.sessions() as db:
        with pytest.raises(providers.ProviderFailure) as caught:
            call(db, httpx.MockTransport(lambda request: httpx.Response(status, json=body)))
        assert caught.value.code == expected
        record = db.scalar(select(ModelCall))
        assert record.status == "failed" and record.error_code == expected
        assert record.external_calls == 1
        assert record.usage == {}


def test_transport_protocol_error_and_response_limit_are_recorded(app):
    def broken(request):
        raise httpx.RemoteProtocolError("fixture internal network detail")

    with app.state.sessions() as db:
        with pytest.raises(providers.ProviderFailure) as caught:
            call(db, httpx.MockTransport(broken))
        assert caught.value.code == "network_error"
        assert "internal network detail" not in str(caught.value)
        with pytest.raises(providers.ProviderFailure) as too_big:
            call(db, httpx.MockTransport(lambda request: httpx.Response(200, content=b"x" * 4_000_001)))
        assert too_big.value.code == "invalid_output"
        assert all(row.status == "failed" for row in db.scalars(select(ModelCall)))


def test_timeout_retries_only_reserved_number_of_calls(app):
    calls = []

    def timeout(request):
        calls.append(1)
        raise httpx.ReadTimeout("fixture timeout")

    cfg = providers.ProviderConfig(
        "generation", "https://fixture.invalid/v1", "fixture", "fixture-key", retries=1
    )
    with app.state.sessions() as db:
        with pytest.raises(providers.ProviderFailure) as caught:
            call(db, httpx.MockTransport(timeout), cfg=cfg)
        assert caught.value.code == "timeout" and len(calls) == 2
        record = db.scalar(select(ModelCall))
        assert record.external_calls == record.reserved_requests == 2


def test_elapsed_response_and_expired_shared_deadline_do_not_succeed(app, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(providers.time, "monotonic", lambda: clock[0])

    class SlowBody(httpx.SyncByteStream):
        def __iter__(self):
            clock[0] = 70
            yield b"{}"

    with app.state.sessions() as db:
        transport = httpx.MockTransport(lambda request: httpx.Response(200, stream=SlowBody()))
        with pytest.raises(providers.ProviderFailure) as caught:
            call(db, transport)
        assert caught.value.code == "timeout"
        db.info["model_deadline"] = 60
        with pytest.raises(providers.ProviderFailure) as expired:
            call(db, transport)
        assert expired.value.code == "timeout"
        assert len(list(db.scalars(select(ModelCall)))) == 1


def test_personal_quota_and_unconfigured_service_do_not_send_request(app):
    calls = []
    transport = httpx.MockTransport(lambda request: calls.append(1) or httpx.Response(200, json={}))
    cfg = providers.ProviderConfig(
        "generation", "https://fixture.invalid/v1", "fixture", "fixture-key", personal_limit=1
    )
    with app.state.sessions() as db:
        call(db, transport, cfg=cfg)
        with pytest.raises(providers.ProviderFailure) as exhausted:
            call(db, transport, cfg=cfg)
        assert exhausted.value.code == "quota_exceeded"
        with pytest.raises(providers.ProviderFailure) as missing:
            call(db, transport, cfg=replace(cfg, model=""))
        assert missing.value.code == "not_configured" and len(calls) == 1


@pytest.mark.parametrize("vector", [[], [1, 2], [float("nan"), 0, 1]])
def test_embedding_rejects_invalid_vector(configured, app, vector):
    with app.state.sessions() as db:
        user = db.scalar(select(User))
        transport = httpx.MockTransport(
            lambda request: httpx.Response(200, json={"data": [{"index": 0, "embedding": vector}]})
        )
        with pytest.raises(providers.ProviderFailure) as caught:
            providers.embed(ModelContext(db, user.id, transport), ["public fixture"])
        assert caught.value.code == "invalid_output"


def test_generation_fenced_json_and_non_text_output(configured, app):
    with app.state.sessions() as db:
        user = db.scalar(select(User))

        def transport(content):
            return httpx.MockTransport(
                lambda request: httpx.Response(200, json={"choices": [{"message": {"content": content}}]})
            )

        value, _ = providers.generate(
            ModelContext(db, user.id, transport('```json\n{"ok":true}\n```')),
            GenerationPrompt("annotation", "fixture", {}),
            lambda body: body,
        )
        assert value == {"ok": True}
        with pytest.raises(providers.ProviderFailure) as caught:
            providers.generate(
                ModelContext(db, user.id, transport(None)),
                GenerationPrompt("annotation", "fixture", {}),
                lambda body: body,
            )
        assert caught.value.code == "invalid_output"
