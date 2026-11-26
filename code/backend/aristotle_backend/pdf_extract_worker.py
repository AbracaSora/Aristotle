"""One stdin PDF per process; never starts an API server or reads provider config."""

import json
import resource
import sys


def resource_limits():
    resource.setrlimit(resource.RLIMIT_CPU, (30, 30))
    # Darwin does not reliably enforce address-space limits; wall/CPU caps still apply.
    if sys.platform.startswith("linux"):
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))


def main():
    resource_limits()
    from fastapi import HTTPException

    from .material_imports import MAX_PDF_BYTES, extract_pdf

    data = sys.stdin.buffer.read(MAX_PDF_BYTES + 1)
    try:
        body = {"pages": extract_pdf(data)}
    except HTTPException as exc:
        body = {"error": {"status_code": exc.status_code, "message": str(exc.detail)}}
    except (MemoryError, OSError):
        body = {"error": {"status_code": 422, "message": "PDF抽取超出资源限制或读取失败"}}
    sys.stdout.write(json.dumps(body, ensure_ascii=False))


if __name__ == "__main__":
    main()
