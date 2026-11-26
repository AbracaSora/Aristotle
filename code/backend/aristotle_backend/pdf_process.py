"""Bound text extraction to a child process with a wall-clock deadline."""

import json
import os
import subprocess
import sys

from fastapi import HTTPException

PDF_TIMEOUT = 30


def extract_isolated(data):
    try:
        result = subprocess.run(
            [sys.executable, "-m", "aristotle_backend.pdf_extract_worker"],
            input=data,
            capture_output=True,
            check=False,
            timeout=PDF_TIMEOUT,
            env={"PATH": os.defpath, "PYTHONIOENCODING": "utf-8"},
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(408, "PDF 抽取超过30秒，任务已终止，请检查文件后重新上传") from None
    if result.returncode:
        raise HTTPException(422, "PDF 抽取进程失败或超出资源限制，未保存资料")
    try:
        body = json.loads(result.stdout)
        if "error" in body:
            raise HTTPException(body["error"]["status_code"], body["error"]["message"])
        pages = body["pages"]
        if not isinstance(pages, list) or not pages:
            raise ValueError()
        return pages
    except (ValueError, KeyError, TypeError):
        raise HTTPException(422, "PDF 抽取进程未返回有效文本，未保存资料") from None
