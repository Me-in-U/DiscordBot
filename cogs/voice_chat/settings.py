from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping


CPU_WHISPER_MODEL = "tiny"
CPU_WHISPER_COMPUTE_TYPE = "int8"
CUDA_WHISPER_MODEL = "deepdml/faster-whisper-large-v3-turbo-ct2"
CUDA_WHISPER_COMPUTE_TYPE = "float16"
SUPPORTED_WHISPER_DEVICES = frozenset({"cpu", "cuda"})


@dataclass(frozen=True)
class WhisperSettings:
    model: str
    device: str
    compute_type: str


def resolve_whisper_settings(
    environ: Mapping[str, str] | None = None,
) -> WhisperSettings:
    """Resolve voice STT settings with a lightweight CPU-safe default."""
    source = os.environ if environ is None else environ
    device = source.get("VOICE_CHAT_WHISPER_DEVICE", "cpu").strip().lower()
    if device not in SUPPORTED_WHISPER_DEVICES:
        device = "cpu"

    default_model = CPU_WHISPER_MODEL if device == "cpu" else CUDA_WHISPER_MODEL
    default_compute_type = (
        CPU_WHISPER_COMPUTE_TYPE
        if device == "cpu"
        else CUDA_WHISPER_COMPUTE_TYPE
    )
    model = source.get("VOICE_CHAT_WHISPER_MODEL", "").strip() or default_model
    compute_type = (
        source.get("VOICE_CHAT_WHISPER_COMPUTE_TYPE", "").strip()
        or default_compute_type
    )
    return WhisperSettings(
        model=model,
        device=device,
        compute_type=compute_type,
    )


def cpu_fallback_settings() -> WhisperSettings:
    return WhisperSettings(
        model=CPU_WHISPER_MODEL,
        device="cpu",
        compute_type=CPU_WHISPER_COMPUTE_TYPE,
    )
