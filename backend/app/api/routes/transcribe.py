from __future__ import annotations

import os
import time
import tempfile
from typing import Optional

from fastapi import APIRouter, UploadFile, File, Query, HTTPException

from backend.app.services.stt.transcriber import transcribe_file

router = APIRouter(tags=["stt"])


def _truthy(v: str | None) -> bool:
    return (v or "").strip().lower() in ("1", "true", "yes", "y", "on")


@router.post("/transcribe")
async def transcribe_endpoint(
    file: UploadFile = File(...),
    lang: Optional[str] = Query("ar"),
    debug: int = Query(0),
):
    if not _truthy(os.getenv("STT_ENABLED", "0")):
        raise HTTPException(status_code=503, detail="STT is disabled")

    t0 = time.perf_counter()

    suffix = os.path.splitext(file.filename or "")[1] or ".webm"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        data = await file.read()
        if not data or len(data) < 200:
            return {"text": "", "language": lang or "ar"}
        tmp.write(data)
        tmp_path = tmp.name

    write_ms = int((time.perf_counter() - t0) * 1000)

    t1 = time.perf_counter()
    try:
        result = transcribe_file(tmp_path, language_hint=lang)
    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass

    transcribe_ms = int((time.perf_counter() - t1) * 1000)

    payload = {"text": result.text, "language": result.language}
    if debug:
        payload["timings"] = {"bytes": len(data), "write_ms": write_ms, "transcribe_ms": transcribe_ms}
    return payload
