from __future__ import annotations

import os
import tempfile
import time
from typing import Any

from fastapi import APIRouter, File, UploadFile, HTTPException, Query
from backend.app.services.stt.transcriber import transcribe_file

router = APIRouter(tags=["transcribe"])

_MAX_MB = int(os.getenv("TRANSCRIBE_MAX_MB", "12"))  # safe default


@router.post("/transcribe")
async def transcribe(
    file: UploadFile = File(...),
    lang: str | None = Query("ar", description="Language hint, e.g. ar or en; set empty for auto-detect"),
    debug: bool = Query(False, description="If true, return timings"),
):
    if not file:
        raise HTTPException(status_code=400, detail="Missing audio file")

    ct = (file.content_type or "").lower()
    if not any(x in ct for x in ["audio", "webm", "ogg", "mpeg", "wav", "mp4"]):
        fn = (file.filename or "").lower()
        if not any(fn.endswith(ext) for ext in [".webm", ".ogg", ".mp3", ".wav", ".m4a", ".mp4"]):
            raise HTTPException(status_code=400, detail=f"Unsupported content type: {ct}")

    max_bytes = _MAX_MB * 1024 * 1024

    suffix = os.path.splitext(file.filename or "")[1] or ".webm"
    tmp_path: str | None = None
    bytes_written = 0

    try:
        # Stream to disk (avoid loading whole file into RAM)
        t_write0 = time.perf_counter()
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp_path = tmp.name

            while True:
                chunk = await file.read(1024 * 1024)  # 1MB chunks
                if not chunk:
                    break
                bytes_written += len(chunk)
                if bytes_written > max_bytes:
                    raise HTTPException(status_code=413, detail=f"Audio too large (> {_MAX_MB} MB)")
                tmp.write(chunk)

        write_ms = (time.perf_counter() - t_write0) * 1000

        # Transcribe timing (this is what we care about)
        t0 = time.perf_counter()
        res = transcribe_file(tmp_path, language_hint=((lang or "").strip() or None))
        transcribe_ms = (time.perf_counter() - t0) * 1000

        print(f"[STT] bytes={bytes_written} write_ms={write_ms:.0f} transcribe_ms={transcribe_ms:.0f} file={os.path.basename(tmp_path)}")

        out: dict[str, Any] = {"text": res.text, "language": res.language}
        if debug:
            out["timings"] = {
                "bytes": bytes_written,
                "write_ms": round(write_ms, 1),
                "transcribe_ms": round(transcribe_ms, 1),
            }
        return out

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Transcription failed: {type(e).__name__}")

    finally:
        try:
            await file.close()
        except Exception:
            pass
        if tmp_path:
            try:
                os.remove(tmp_path)
            except Exception:
                pass
