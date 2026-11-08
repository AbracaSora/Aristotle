"""OpenAI-compatible HTTP adapters with validation, durable budgets and redacted failures."""

import hashlib
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from dotenv import load_dotenv
from sqlalchemy import func, select, text

from .config import PROJECT_ROOT
from .db import ModelCall
from .vector_type import checked_vector

_budget_lock = Lock()


class ProviderFailure(Exception):
    def __init__(self, code, message, retryable=False):
        super().__init__(message)
        self.code, self.retryable = code, retryable


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


@dataclass(frozen=True)
class ProviderConfig:
    kind: str
    base_url: str
    model: str
    api_key: str
    dimensions: int = 0
    timeout: float = 30
    retries: int = 0
    daily_limit: int = 200
    proxy: str | None = None
    local: bool = False
    token_field: str = "max_tokens"

    @property
    def configured(self):
        return bool(self.base_url and self.model and (self.api_key or self.local))

    @property
    def namespace(self):
        return fingerprint([self.kind, self.base_url, self.model, self.dimensions])


def provider_config(kind: str) -> ProviderConfig:
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    prefix = "ARISTOTLE_EMBEDDING" if kind == "embedding" else "ARISTOTLE_LLM"
    try:
        cfg = ProviderConfig(
            kind=kind,
            base_url=os.getenv(prefix + "_BASE_URL", "").rstrip("/"),
            model=os.getenv(prefix + "_MODEL", ""),
            api_key=os.getenv(prefix + "_API_KEY", ""),
            dimensions=int(os.getenv("ARISTOTLE_EMBEDDING_DIMENSIONS", "0")) if kind == "embedding" else 0,
            timeout=float(os.getenv("ARISTOTLE_MODEL_TIMEOUT", "30")),
            retries=int(os.getenv("ARISTOTLE_MODEL_RETRIES", "0")),
            daily_limit=int(os.getenv("ARISTOTLE_MODEL_DAILY_LIMIT", "200")),
            proxy=os.getenv("ARISTOTLE_MODEL_PROXY") or None,
            local=os.getenv(prefix + "_LOCAL", "0") == "1",
            token_field=os.getenv("ARISTOTLE_LLM_TOKEN_FIELD", "max_tokens"),
        )
        if not 1 <= cfg.timeout <= 30 or cfg.retries not in (0, 1) or not 1 <= cfg.daily_limit <= 2000:
            raise ValueError()
        if not 0 <= cfg.dimensions <= 4096 or cfg.token_field not in ("max_tokens", "max_completion_tokens"):
            raise ValueError()
        if cfg.base_url:
            url = urlparse(cfg.base_url)
            if (
                url.scheme not in ("https", "http")
                or not url.hostname
                or url.username
                or url.password
                or url.query
                or url.fragment
            ):
                raise ValueError()
        return cfg
    except (ValueError, TypeError):
        raise ProviderFailure("invalid_config", "模型服务配置无效，请管理员检查后端环境变量。") from None


def reserve_call(db, user_id, purpose, cfg, payload):
    now = time.time()
    midnight = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    with _budget_lock:
        if db.bind.dialect.name == "postgresql":
            lock_id = int(fingerprint(["model-budget", midnight])[:15], 16)
            db.execute(text("SELECT pg_advisory_xact_lock(:id)"), {"id": lock_id})
        used = db.scalar(
            select(func.coalesce(func.sum(ModelCall.reserved_requests), 0)).where(
                ModelCall.created_at >= midnight
            )
        )
        personal = db.scalar(
            select(func.coalesce(func.sum(ModelCall.reserved_requests), 0)).where(
                ModelCall.user_id == user_id, ModelCall.created_at >= midnight
            )
        )
        if used + cfg.retries + 1 > cfg.daily_limit or personal + cfg.retries + 1 > min(60, cfg.daily_limit):
            db.rollback()
            raise ProviderFailure("quota_exceeded", "今日模型调用配额已用尽；已发布内容的学习仍可继续。")
        row = ModelCall(
            id=str(uuid4()),
            user_id=user_id,
            purpose=purpose,
            namespace=cfg.namespace,
            model=cfg.model,
            input_hash=fingerprint(payload),
            status="reserved",
            reserved_requests=cfg.retries + 1,
            external_calls=0,
            usage={},
            error_code="",
            duration_seconds=0,
            created_at=now,
        )
        db.add(row)
        db.commit()
        return row


def request_model(db, user_id, purpose, cfg, payload, decode, transport=None):
    if not cfg.configured:
        raise ProviderFailure("not_configured", "模型服务尚未配置，请管理员填写后端服务地址、模型名和密钥。")
    row = reserve_call(db, user_id, purpose, cfg, payload)
    started = time.monotonic()
    endpoint = "/embeddings" if cfg.kind == "embedding" else "/chat/completions"
    headers = {"Authorization": "Bearer " + cfg.api_key} if cfg.api_key else {}
    try:
        with httpx.Client(
            timeout=cfg.timeout,
            transport=transport,
            proxy=cfg.proxy if transport is None else None,
            trust_env=False,
            follow_redirects=False,
        ) as client:
            for attempt in range(cfg.retries + 1):
                try:
                    remaining = 65 - (time.monotonic() - started)
                    if remaining <= 0:
                        raise ProviderFailure("timeout", "模型处理超过时间预算，请稍后重试。", True)
                    row.external_calls += 1
                    response = client.post(
                        cfg.base_url + endpoint,
                        json={"model": cfg.model, **payload},
                        headers=headers,
                        timeout=min(cfg.timeout, remaining),
                    )
                    if response.status_code == 429 or response.status_code >= 500:
                        raise ProviderFailure(
                            "rate_limited" if response.status_code == 429 else "unavailable",
                            "模型服务暂时繁忙，请稍后重试。",
                            True,
                        )
                    if not response.is_success:
                        raise ProviderFailure(
                            "request_rejected", "模型服务拒绝了请求，请管理员核对模型名、鉴权和接口格式。"
                        )
                    if len(response.content) > 4_000_000:
                        raise ProviderFailure("invalid_output", "模型响应超出允许大小，已拒绝使用。")
                    try:
                        body = response.json()
                        if not isinstance(body, dict) or not isinstance(body.get("usage", {}), dict):
                            raise ValueError()
                        raw_usage = body.get("usage", {})
                        row.usage = {
                            k: raw_usage[k]
                            for k in ("prompt_tokens", "completion_tokens", "total_tokens")
                            if isinstance(raw_usage.get(k), int)
                            and not isinstance(raw_usage[k], bool)
                            and raw_usage[k] >= 0
                        }
                        value = decode(body)
                    except (ValueError, KeyError, IndexError, TypeError):
                        raise ProviderFailure(
                            "invalid_output", "模型返回格式或内容校验失败，未写入学习或发布状态。"
                        ) from None
                    row.status = "succeeded"
                    row.duration_seconds = time.monotonic() - started
                    db.commit()
                    return value, {
                        "call_id": row.id,
                        "model": cfg.model,
                        "namespace": cfg.namespace,
                        "usage": row.usage,
                        "external_calls": row.external_calls,
                    }
                except (httpx.TimeoutException, httpx.NetworkError):
                    failure = ProviderFailure("timeout", "无法在时间预算内连接模型服务。", True)
                except ProviderFailure as failure:
                    if not failure.retryable or attempt == cfg.retries:
                        raise
                if attempt == cfg.retries:
                    raise failure
    except ProviderFailure as exc:
        row.status, row.error_code = "failed", exc.code
        row.duration_seconds = time.monotonic() - started
        db.commit()
        raise
    except httpx.HTTPError:
        row.status, row.error_code = "failed", "network_error"
        row.duration_seconds = time.monotonic() - started
        db.commit()
        raise ProviderFailure("network_error", "模型网络连接失败，已保留失败状态。", True) from None


def embed(db, user_id, texts, transport=None):
    cfg = provider_config("embedding")

    def decode(body):
        data = body["data"]
        if len(data) != len(texts) or sorted(d["index"] for d in data) != list(range(len(texts))):
            raise ValueError()
        vectors = [checked_vector(d["embedding"]) for d in sorted(data, key=lambda d: d["index"])]
        if len({len(v) for v in vectors}) != 1 or (cfg.dimensions and len(vectors[0]) != cfg.dimensions):
            raise ValueError()
        return vectors

    payload = {"input": texts, "encoding_format": "float"}
    return request_model(db, user_id, "embedding", cfg, payload, decode, transport)


def generate(db, user_id, purpose, system, content, decode, transport=None):
    cfg = provider_config("generation")

    def parse(body):
        value = body["choices"][0]["message"]["content"]
        if not isinstance(value, str) or not value.strip():
            raise ValueError()
        if value.strip().startswith("```json") and value.strip().endswith("```"):
            value = value.strip()[7:-3]
        return decode(json.loads(value))

    return request_model(
        db,
        user_id,
        purpose,
        cfg,
        {
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(content, ensure_ascii=False)},
            ],
            cfg.token_field: 1600,
        },
        parse,
        transport,
    )
