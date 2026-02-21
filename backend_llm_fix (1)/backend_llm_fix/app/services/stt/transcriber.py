from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional, Tuple, Any

try:
    from faster_whisper import WhisperModel, BatchedInferencePipeline
except ImportError:  # أمان لو نسخة faster-whisper ما فيها BatchedInferencePipeline
    from faster_whisper import WhisperModel  # type: ignore
    BatchedInferencePipeline = None  # type: ignore


@dataclass
class TranscribeResult:
    text: str
    language: Optional[str] = None


_model: WhisperModel | None = None
_pipe: Any = None
_device_used: str | None = None  # "cuda" or "cpu"


def _env(*names: str, default: str = "") -> str:
    """Return first non-empty env value from names."""
    for n in names:
        v = os.getenv(n)
        if v is not None and str(v).strip() != "":
            return str(v).strip()
    return default


def _env_int(*names: str, default: int) -> int:
    v = _env(*names, default=str(default))
    try:
        return int(v)
    except Exception:
        return default


def _truthy(v: str) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "y", "on")


def _compute_for(device: str, compute_pref: str) -> str:
    # auto: cuda -> float16, cpu -> int8
    if compute_pref and compute_pref.lower() != "auto":
        return compute_pref
    return "float16" if device == "cuda" else "int8"


def _build_model(device: str, model_name: str, compute_type: str, cpu_threads: int, num_workers: int) -> WhisperModel:
    # cpu_threads/num_workers مهمين للـ CPU، وعلى CUDA غالباً ما تضر
    return WhisperModel(
        model_name,
        device=device,
        compute_type=compute_type,
        cpu_threads=cpu_threads,
        num_workers=num_workers,
    )


def _get_model() -> WhisperModel:
    global _model, _device_used

    if _model is not None:
        return _model

    # ✅ ندعم STT_* (الجديد) + WHISPER_* (القديم)
    model_name = _env("STT_MODEL", "WHISPER_MODEL", default="small")
    device_pref = _env("STT_DEVICE", "WHISPER_DEVICE", default="auto").lower()
    compute_pref = _env("STT_COMPUTE_TYPE", "WHISPER_COMPUTE_TYPE", default="auto").lower()

    cpu_threads = _env_int("STT_CPU_THREADS", "WHISPER_CPU_THREADS", default=8)
    num_workers = _env_int("STT_NUM_WORKERS", "WHISPER_NUM_WORKERS", default=2)

    strict = _truthy(_env("STT_STRICT_DEVICE", default="0"))

    def try_cuda_then_cpu() -> WhisperModel:
        global _device_used
        # 1) CUDA
        try:
            ct = _compute_for("cuda", compute_pref)
            m = _build_model("cuda", model_name, ct, cpu_threads, num_workers)
            _device_used = "cuda"
            print(f"[STT] using CUDA (model={model_name}, compute={ct})")
            return m
        except Exception as e:
            print("[STT] CUDA unavailable, falling back to CPU:", repr(e))

        # 2) CPU fallback
        ct = _compute_for("cpu", compute_pref)
        m = _build_model("cpu", model_name, ct, cpu_threads, num_workers)
        _device_used = "cpu"
        print(f"[STT] using CPU (model={model_name}, compute={ct})")
        return m

    if device_pref in ("", "auto"):
        _model = try_cuda_then_cpu()
        return _model

    # forced device (cuda/cpu)
    forced = "cuda" if device_pref in ("cuda", "gpu") else "cpu"
    try:
        ct = _compute_for(forced, compute_pref)
        _model = _build_model(forced, model_name, ct, cpu_threads, num_workers)
        _device_used = forced
        print(f"[STT] using {forced.upper()} (model={model_name}, compute={ct})")
        return _model
    except Exception as e:
        if strict:
            raise
        print(f"[STT] forced {forced.upper()} failed, falling back to CPU:", repr(e))
        ct = _compute_for("cpu", compute_pref)
        _model = _build_model("cpu", model_name, ct, cpu_threads, num_workers)
        _device_used = "cpu"
        print(f"[STT] using CPU (model={model_name}, compute={ct})")
        return _model


def _get_pipe():
    global _pipe
    if BatchedInferencePipeline is None:
        return None
    if _pipe is None:
        _pipe = BatchedInferencePipeline(model=_get_model())
    return _pipe


def transcribe_file(audio_path: str, language_hint: str | None = "ar") -> TranscribeResult:
    model = _get_model()
    pipe = _get_pipe()

    lang = (language_hint or "").strip() or None

    batch_size = _env_int("STT_BATCH_SIZE", "WHISPER_BATCH_SIZE", default=16)

    # VAD: default "auto" -> CPU ON, CUDA OFF
    vad_pref = _env("STT_VAD", "WHISPER_VAD", default="auto").lower()
    if vad_pref == "auto":
        use_vad = (_device_used == "cpu")
    else:
        use_vad = _truthy(vad_pref)

    if pipe is not None:
        segments, info = pipe.transcribe(
            audio_path,
            language=lang,
            task="transcribe",
            beam_size=1,
            vad_filter=use_vad,
            batch_size=batch_size,
        )
    else:
        # fallback لو pipeline غير متاح
        segments, info = model.transcribe(
            audio_path,
            language=lang,
            task="transcribe",
            beam_size=1,
            vad_filter=use_vad,
            batch_size=batch_size,
        )

    text_parts = [seg.text.strip() for seg in segments if getattr(seg, "text", "").strip()]
    text = " ".join(text_parts).strip()
    return TranscribeResult(text=text, language=getattr(info, "language", None))