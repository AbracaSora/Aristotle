"""Operational logs must rotate, remain private and redact common credentials."""

import logging
import os
import time


def test_log_redacts_credentials_and_has_private_permissions(tmp_path):
    from aristotle_backend.runtime_logging import configure_logging

    path = configure_logging("test", tmp_path)
    logger = logging.getLogger("aristotle_backend.test")
    logger.warning(
        "Bearer %s database=%s", "fixture-sensitive-token", "postgresql://user:fixture-password@localhost/db"
    )
    for handler in logging.getLogger("aristotle_backend").handlers:
        handler.flush()
    content = path.read_text()
    assert "fixture-sensitive-token" not in content
    assert "fixture-password" not in content
    assert "[redacted]" in content
    assert os.stat(path).st_mode & 0o777 == 0o600


def test_log_retention_removes_only_old_owned_logs(tmp_path):
    from aristotle_backend.runtime_logging import configure_logging

    old = tmp_path / "aristotle-api-previous.log.1"
    old.write_text("old log")
    earlier = time.time() - 15 * 86400
    os.utime(old, (earlier, earlier))
    unrelated = tmp_path / "user-notes.txt"
    unrelated.write_text("preserve")
    path = configure_logging("retention", tmp_path)
    assert not old.exists()
    assert unrelated.read_text() == "preserve"
    assert path.exists()


def test_rotated_logs_keep_private_permissions(tmp_path):
    from aristotle_backend.runtime_logging import configure_logging

    configure_logging("rotation", tmp_path)
    logger = logging.getLogger("aristotle_backend")
    handler = logger.handlers[0]
    handler.maxBytes = 128
    for _ in range(12):
        logger.info("bounded fixture event %s", "x" * 70)
    handler.flush()
    files = list(tmp_path.glob("aristotle-rotation-*.log*"))
    assert 1 < len(files) <= 4
    assert all(os.stat(path).st_mode & 0o777 == 0o600 for path in files)
