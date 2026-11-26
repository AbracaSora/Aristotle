"""Actual PDF bytes, no OCR or paid model calls."""

from io import BytesIO

import pytest
from aristotle_backend.design_seed import seed_design_flow
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject


def pdf_bytes(text="A stack follows LIFO.", *, encrypted=False):
    writer = PdfWriter()
    page = writer.add_blank_page(400, 400)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
    )
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 12 Tf 20 300 Td ({text}) Tj ET".encode())
    page[NameObject("/Contents")] = writer._add_object(stream)
    if encrypted:
        writer.encrypt("fixture-password")
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def test_pdf_upload_extracts_real_pages_requires_confirmation(app, client, login):
    seed_design_flow(app.state.sessions)
    headers = login()
    client.patch("/api/v1/learning-scope", headers=headers, json={"scope_id": "stack"})
    result = client.post(
        "/api/v1/material-imports/pdf",
        headers=headers,
        files={"file": ("lecture.pdf", pdf_bytes(), "application/pdf")},
        data={"title": "自编 PDF"},
    )
    assert result.status_code == 202, result.text
    job = client.post("/api/v1/jobs/" + result.json()["id"] + "/run", headers=headers)
    assert job.status_code == 200, job.text
    assert job.json()["status"] == "succeeded"
    assert job.json()["result"]["requires_confirmation"] is True
    assert job.json()["result"]["implementation"] == "pypdf-text"


@pytest.mark.parametrize(
    "payload",
    [b"not a PDF", pdf_bytes(encrypted=True), pdf_bytes(text="")],
    ids=["invalid", "encrypted", "image-only"],
)
def test_pdf_rejects_invalid_encrypted_or_image_only(app, client, login, payload):
    seed_design_flow(app.state.sessions)
    headers = login()
    client.patch("/api/v1/learning-scope", headers=headers, json={"scope_id": "stack"})
    result = client.post(
        "/api/v1/material-imports/pdf",
        headers=headers,
        files={"file": ("lecture.pdf", payload, "application/pdf")},
    )
    if payload == b"not a PDF":
        assert result.status_code == 422, result.text
    else:
        assert result.status_code == 202, result.text
        job = client.post("/api/v1/jobs/" + result.json()["id"] + "/run", headers=headers).json()
        assert job["status"] == "failed" and job["result"]["status_code"] == 422


def test_pdf_size_and_page_limits():
    from aristotle_backend.material_imports import MAX_PDF_BYTES, extract_pdf
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as over_bytes:
        extract_pdf(b"%PDF-" + b"0" * MAX_PDF_BYTES)
    assert over_bytes.value.status_code == 413
    writer = PdfWriter()
    for _ in range(101):
        writer.add_blank_page(10, 10)
    data = BytesIO()
    writer.write(data)
    with pytest.raises(HTTPException) as over_pages:
        extract_pdf(data.getvalue())
    assert over_pages.value.status_code == 413


def test_pdf_upload_returns_queued_before_extraction(app, client, login, monkeypatch):
    seed_design_flow(app.state.sessions)
    headers = login()
    client.patch("/api/v1/learning-scope", headers=headers, json={"scope_id": "stack"})

    def forbidden(*args, **kwargs):
        raise AssertionError("PDF extraction must run after the queued response")

    monkeypatch.setattr("aristotle_backend.material_imports.PdfReader", forbidden)
    response = client.post(
        "/api/v1/material-imports/pdf",
        headers=headers,
        files={"file": ("queued.pdf", pdf_bytes(), "application/pdf")},
    )
    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    assert "pdf_base64" not in response.text


def enqueue_pdf(app, client, login):
    seed_design_flow(app.state.sessions)
    headers = login()
    client.patch("/api/v1/learning-scope", headers=headers, json={"scope_id": "stack"})
    response = client.post(
        "/api/v1/material-imports/pdf",
        headers=headers,
        files={"file": ("worker.pdf", pdf_bytes(), "application/pdf")},
    )
    assert response.status_code == 202
    return headers, response.json()["id"]


def test_import_worker_claims_once_without_manual_run(app, client, login):
    from concurrent.futures import ThreadPoolExecutor

    from aristotle_backend import import_jobs
    from aristotle_backend.db import Material, ServiceJob
    from sqlalchemy import select

    headers, job_id = enqueue_pdf(app, client, login)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: import_jobs.run_import(app.state.sessions, job_id), range(2)))
    result = client.get("/api/v1/jobs/" + job_id, headers=headers).json()
    assert result["status"] == "succeeded"
    assert result["result"]["requires_confirmation"] is True
    with app.state.sessions() as db:
        assert len(list(db.scalars(select(Material)))) == 1
        job = db.get(ServiceJob, job_id)
        assert "pdf_base64" not in job.params
        assert not db.get(Material, job.result["material_id"]).confirmed
    assert import_jobs.run_import(app.state.sessions, job_id) is None


def test_import_worker_recovers_interrupted_job_without_replaying(app, client, login):
    from aristotle_backend import import_jobs
    from aristotle_backend.db import ServiceJob

    headers, job_id = enqueue_pdf(app, client, login)
    with app.state.sessions() as db:
        job = db.get(ServiceJob, job_id)
        job.status = "running"
        job.result = {"claim_id": "interrupted", "started_at": 1}
        db.commit()
    assert import_jobs.expire_imports(app.state.sessions, now=1000) == 1
    result = client.get("/api/v1/jobs/" + job_id, headers=headers).json()
    assert result["status"] == "failed"
    assert result["result"]["error_code"] == "interrupted"
    with app.state.sessions() as db:
        assert "pdf_base64" not in db.get(ServiceJob, job_id).params
    assert import_jobs.run_import(app.state.sessions, job_id) is None


def test_import_worker_revoked_role_prevents_material_creation(app, client, login):
    from aristotle_backend import import_jobs
    from aristotle_backend.db import Material, ServiceJob, User
    from sqlalchemy import select

    _, job_id = enqueue_pdf(app, client, login)
    with app.state.sessions() as db:
        user = db.scalar(select(User).where(User.username == "student1"))
        user.role = "maintainer"
        db.commit()
    import_jobs.run_import(app.state.sessions, job_id)
    with app.state.sessions() as db:
        assert db.get(ServiceJob, job_id).result["error_code"] == "role_changed"
        assert db.scalar(select(Material.id)) is None


def test_pdf_process_timeout_is_visible_and_cleans_source(app, client, login, monkeypatch):
    import subprocess

    from aristotle_backend import import_jobs, pdf_process
    from aristotle_backend.db import Material, ServiceJob
    from sqlalchemy import select

    _, job_id = enqueue_pdf(app, client, login)

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("pdf fixture process", 30)

    monkeypatch.setattr(pdf_process.subprocess, "run", timeout)
    import_jobs.run_import(app.state.sessions, job_id)
    with app.state.sessions() as db:
        job = db.get(ServiceJob, job_id)
        assert job.status == "failed" and job.result["error_code"] == "timeout"
        assert "pdf_base64" not in job.params
        assert db.scalar(select(Material.id)) is None


def test_worker_does_not_consume_mock_jobs_and_expires_old_uploads(app, client, login):
    from aristotle_backend import import_jobs
    from aristotle_backend.db import ServiceJob

    headers, job_id = enqueue_pdf(app, client, login)
    mock = client.post(
        "/api/v1/material-imports", headers=headers, json={"source_type": "pdf_mock", "title": "显式演示"}
    ).json()
    with app.state.sessions() as db:
        job = db.get(ServiceJob, job_id)
        job.created_at = 1
        db.commit()
    assert import_jobs.expire_imports(app.state.sessions, now=90_000) == 1
    assert import_jobs.run_import(app.state.sessions) is None
    with app.state.sessions() as db:
        assert db.get(ServiceJob, mock["id"]).status == "queued"
        assert db.get(ServiceJob, job_id).result["error_code"] == "expired"
        assert "pdf_base64" not in db.get(ServiceJob, job_id).params


def test_worker_once_imports_and_closes_engine(app, client, login, monkeypatch):
    from aristotle_backend import import_worker
    from aristotle_backend.db import ServiceJob

    _, job_id = enqueue_pdf(app, client, login)

    class Engine:
        closed = False

        def dispose(self):
            self.closed = True

    engine = Engine()
    monkeypatch.setattr(import_worker, "open_database", lambda url: (engine, app.state.sessions))
    monkeypatch.setattr("sys.argv", ["import-worker", "--once"])
    import_worker.main()
    assert engine.closed
    with app.state.sessions() as db:
        assert db.get(ServiceJob, job_id).status == "succeeded"


def test_pdf_role_revoked_during_extraction_cannot_publish(app, client, login, monkeypatch):
    from aristotle_backend import import_jobs
    from aristotle_backend.db import Material, ServiceJob, User
    from sqlalchemy import select

    _, job_id = enqueue_pdf(app, client, login)
    original = import_jobs.import_segments

    def revoke(params):
        result = original(params)
        with app.state.sessions() as db:
            user = db.scalar(select(User).where(User.username == "student1"))
            user.role = "maintainer"
            db.commit()
        return result

    monkeypatch.setattr(import_jobs, "import_segments", revoke)
    import_jobs.run_import(app.state.sessions, job_id)
    with app.state.sessions() as db:
        assert db.get(ServiceJob, job_id).status == "failed"
        assert db.get(ServiceJob, job_id).result["error_code"] == "role_changed"
        assert db.scalar(select(Material.id)) is None


@pytest.mark.parametrize("encrypted", [False, True])
def test_extraction_entrypoint_reports_json_and_applies_limits(monkeypatch, encrypted):
    import io
    import json
    import sys

    from aristotle_backend import pdf_extract_worker

    calls = []
    monkeypatch.setattr(
        pdf_extract_worker.resource, "setrlimit", lambda key, value: calls.append((key, value))
    )
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(pdf_bytes(encrypted=encrypted))))
    output = io.StringIO()
    monkeypatch.setattr(sys, "stdout", output)
    pdf_extract_worker.main()
    body = json.loads(output.getvalue())
    assert (pdf_extract_worker.resource.RLIMIT_CPU, (30, 30)) in calls
    if sys.platform.startswith("linux"):
        assert any(key == pdf_extract_worker.resource.RLIMIT_AS for key, _ in calls)
    if encrypted:
        assert body["error"]["status_code"] == 422
    else:
        assert "LIFO" in body["pages"][0]["text"]
        assert body["pages"][0]["location"] == "第 1 页"


@pytest.mark.parametrize("status,payload", [(-9, b""), (0, b"invalid-json"), (0, b'{"pages":[]}')])
def test_extractor_process_crash_or_invalid_output_is_rejected(monkeypatch, status, payload):
    from types import SimpleNamespace

    from aristotle_backend import pdf_process
    from fastapi import HTTPException

    monkeypatch.setattr(
        pdf_process.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=status, stdout=payload),
    )
    with pytest.raises(HTTPException) as caught:
        pdf_process.extract_isolated(b"%PDF-fixture")
    assert caught.value.status_code == 422
