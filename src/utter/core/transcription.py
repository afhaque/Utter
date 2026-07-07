"""TranscriptionService interface + FasterWhisperService (BUILD_PLAN §4).

IMPORTANT: utter.gpu.register_dlls() must run before faster_whisper/ctranslate2 import —
that is why the import lives inside load(), after the shim call.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from time import perf_counter
from typing import Protocol

from utter import gpu
from utter.core.recorder import AudioClip, silence_clip

log = logging.getLogger(__name__)


def _weights_cached(model: str) -> bool:
    """Best-effort check whether a standard Whisper size is already in the HF cache."""
    import os
    from pathlib import Path

    if os.path.isdir(model):  # local model path — nothing to download
        return True
    cache = Path(
        os.environ.get("HF_HUB_CACHE")
        or Path(os.environ.get("HF_HOME") or Path.home() / ".cache" / "huggingface") / "hub"
    )
    return (cache / f"models--Systran--faster-whisper-{model}").is_dir()


@dataclass
class Transcript:
    text: str
    language: str
    latency_ms: float
    segments: list[str] = field(default_factory=list)


class TranscriptionService(Protocol):
    def load(self, model: str, device: str, compute_type: str) -> None: ...
    def transcribe(self, clip: AudioClip) -> Transcript: ...


class FasterWhisperService:
    """faster-whisper (CTranslate2) implementation. Keeps the model resident (§10)."""

    def __init__(
        self, beam_size: int = 5, language: str = "auto", vad_filter: bool = True
    ) -> None:
        self._model = None
        self.beam_size = beam_size
        self.language = language
        self.vad_filter = vad_filter
        self.device = "unloaded"
        self.model_name = ""

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def load(self, model: str, device: str, compute_type: str) -> None:
        gpu.register_dlls()  # before any ctranslate2 touch (§12.1)
        from faster_whisper import WhisperModel

        if not _weights_cached(model):
            # §12.6: first run downloads gigabytes — say so instead of silently hanging
            # (faster-whisper deliberately disables its tqdm progress bars)
            log.info(
                "model weights for %r not cached — downloading from Hugging Face now; "
                "this can take several minutes (~3 GB for large-v3) and only happens once",
                model,
            )
        actual = gpu.resolve_device(device)
        if actual == "cpu" and compute_type in ("float16", "int8_float16"):
            compute_type = "int8"  # float16 unsupported on CPU
        t0 = perf_counter()
        self._model = WhisperModel(model, device=actual, compute_type=compute_type)
        load_ms = (perf_counter() - t0) * 1000
        self.device = actual
        self.model_name = model
        log.info("model %s loaded on %s/%s in %.0f ms", model, actual, compute_type, load_ms)
        self._warmup()

    def _warmup(self) -> None:
        """First CUDA call pays kernel JIT/lazy-load cost (§10) — amortize it at startup."""
        t0 = perf_counter()
        self._transcribe_raw(silence_clip(), beam_size=1)
        log.info("warmup inference done in %.0f ms", (perf_counter() - t0) * 1000)

    def _transcribe_raw(self, clip: AudioClip, beam_size: int) -> tuple[list, object]:
        language = None if self.language in ("auto", "") else self.language
        segments, info = self._model.transcribe(
            clip.samples, beam_size=beam_size, language=language, vad_filter=self.vad_filter
        )
        return list(segments), info  # consume the generator — decoding happens here

    def transcribe(self, clip: AudioClip) -> Transcript:
        if self._model is None:
            raise RuntimeError("call load() first")
        t0 = perf_counter()
        segments, info = self._transcribe_raw(clip, self.beam_size)
        latency_ms = (perf_counter() - t0) * 1000
        texts = [s.text.strip() for s in segments]
        text = " ".join(t for t in texts if t).strip()
        log.info(
            "transcribed %.2fs of audio in %.0f ms (warm, model=%s, device=%s)",
            clip.duration_s, latency_ms, self.model_name, self.device,
        )
        return Transcript(text=text, language=info.language, latency_ms=latency_ms, segments=texts)
