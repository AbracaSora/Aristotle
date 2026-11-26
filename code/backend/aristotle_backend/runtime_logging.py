"""Private, rotating per-process logs for backend events, with credential redaction."""

import logging
import os
import re
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .config import PROJECT_ROOT

MAX_LOG_BYTES = 1_048_576
BACKUP_COUNT = 3
RETENTION_SECONDS = 14 * 86400


def redact(value):
    value = re.sub(r"(?i)\bBearer\s+\S+", "Bearer [redacted]", value)
    value = re.sub(r"\bsk-[A-Za-z0-9_-]{12,}", "[redacted]", value)
    return re.sub(r"([a-zA-Z][\w+.-]*://[^:/\s]+:)[^@\s]+(@)", r"\1[redacted]\2", value)


class SafeFormatter(logging.Formatter):
    def format(self, record):
        return redact(super().format(record))


class PrivateRotatingHandler(RotatingFileHandler):
    def _open(self):
        descriptor = os.open(self.baseFilename, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
        return os.fdopen(descriptor, self.mode, encoding=self.encoding, errors=self.errors)


def expire_logs(directory, active):
    cutoff = time.time() - RETENTION_SECONDS
    for path in directory.glob("aristotle-*.log*"):
        if path == active or path.is_symlink():
            continue
        if path.is_file() and path.stat().st_mtime < cutoff:
            path.unlink()


def configure_logging(service, directory=None):
    directory = Path(directory) if directory else PROJECT_ROOT / ".local" / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"aristotle-{service}-{os.getpid()}.log"
    logger = logging.getLogger("aristotle_backend")
    if any(getattr(handler, "baseFilename", None) == str(path.resolve()) for handler in logger.handlers):
        return path
    expire_logs(directory, path)
    path.touch(mode=0o600, exist_ok=True)
    path.chmod(0o600)
    handler = PrivateRotatingHandler(path, maxBytes=MAX_LOG_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8")
    handler.setFormatter(SafeFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    for previous in logger.handlers[:]:
        logger.removeHandler(previous)
        previous.close()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return path
