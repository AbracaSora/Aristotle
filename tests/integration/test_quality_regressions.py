"""Failure-first checks for production configuration and quota boundaries."""

from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest
from aristotle_backend.db import ModelCall, SystemSetting, User
from aristotle_backend.providers import (
    ModelContext,
    ModelRequest,
    ProviderConfig,
    ProviderFailure,
    request_model,
)
from sqlalchemy import select


def config():
    return ProviderConfig("generation", "https://fixture.invalid/v1", "fixture", "fixture-key")


def test_administrator_retry_settings_control_real_adapter(app):
    calls = []

    def reply(request):
        calls.append(request)
        return httpx.Response(503) if len(calls) == 1 else httpx.Response(200, json={"value": 7})

    with app.state.sessions() as db:
        user = db.scalar(select(User))
        db.add(
            SystemSetting(
                key="provider",
                data={
                    "mode": "live",
                    "retries": 1,
                    "timeout_seconds": 2,
                    "total_budget_seconds": 3,
                    "daily_annotation_limit": 200,
                },
            )
        )
        db.commit()
        value, _ = request_model(
            ModelContext(db, user.id, httpx.MockTransport(reply)),
            "annotation",
            config(),
            ModelRequest({}, lambda body: body["value"]),
        )
        assert value == 7 and len(calls) == 2
        assert calls[0].extensions["timeout"]["read"] <= 2


def test_disabled_adapter_cannot_be_bypassed_by_direct_call(app):
    with app.state.sessions() as db:
        user = db.scalar(select(User))
        db.add(SystemSetting(key="provider", data={"mode": "disabled"}))
        db.commit()
        with pytest.raises(ProviderFailure, match="禁用"):
            request_model(
                ModelContext(db, user.id, httpx.MockTransport(lambda r: httpx.Response(200, json={}))),
                "annotation",
                config(),
                ModelRequest({}, lambda body: body),
            )
        assert db.scalar(select(ModelCall.id)) is None


def test_quota_day_uses_shanghai_midnight(app, monkeypatch):
    # UTC yesterday, but Shanghai today: this reservation MUST count toward today's cap.
    now = datetime(2026, 11, 24, 1, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp()
    monkeypatch.setattr("aristotle_backend.providers.time.time", lambda: now)
    with app.state.sessions() as db:
        user = db.scalar(select(User))
        cfg = replace(config(), daily_limit=1)
        transport = httpx.MockTransport(lambda r: httpx.Response(200, json={}))
        request_model(
            ModelContext(db, user.id, transport), "annotation", cfg, ModelRequest({}, lambda body: body)
        )
        with pytest.raises(ProviderFailure, match="配额"):
            request_model(
                ModelContext(db, user.id, transport), "annotation", cfg, ModelRequest({}, lambda body: body)
            )


def test_annotation_input_carries_versioned_rules_and_no_student_data():
    from types import SimpleNamespace

    from aristotle_backend.model_jobs import _question_content

    question = SimpleNamespace(
        question_id="q",
        version=1,
        knowledge_id="stack",
        prompt="题干",
        options=["A", "B"],
        answer="A",
        explanation="解析",
    )
    content = _question_content(question)
    assert content["knowledge_id"] == "stack"
    assert content["rule_version"] == "bloom-required-process-1"
    assert set(content["classification_rules"]) == {
        "remember",
        "understand",
        "apply",
        "analyze",
        "evaluate",
        "create",
        "decision",
    }
    assert "user_id" not in content and "materials" not in content
