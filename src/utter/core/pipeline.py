"""Pipeline — orchestrates record → transcribe → format → inject (BUILD_PLAN §3).

Headless and importable: no GUI dependency. Formatter/injector/history are optional
hooks so Phase 1 runs the bare record→transcribe core and later phases plug in.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from utter.core.config import Config
from utter.core.recorder import AudioClip, RecorderService
from utter.core.transcription import FasterWhisperService, Transcript

log = logging.getLogger(__name__)

# below this, a clip is almost certainly an accidental double-toggle — Whisper would
# hallucinate text from the key-click/breath noise, and we must never paste that
MIN_CLIP_SECONDS = 0.35


class Pipeline:
    def __init__(
        self,
        cfg: Config,
        formatter: Callable[[str], str] | None = None,
        injector: Callable[[str], None] | None = None,
        on_result: Callable[[Transcript, str], None] | None = None,
    ) -> None:
        self.cfg = cfg
        self.recorder = RecorderService(
            sample_rate=cfg.audio.sample_rate, input_device=cfg.audio.input_device
        )
        self.transcriber = FasterWhisperService(
            beam_size=cfg.model.beam_size,
            language=cfg.model.language,
            vad_filter=cfg.model.vad_filter,
        )
        self.formatter = formatter
        self.injector = injector
        self.on_result = on_result
        self._load_lock = threading.Lock()

    def load(self) -> None:
        """Load the model once and keep it resident (§10). Includes warmup. Thread-safe."""
        with self._load_lock:
            if not self.transcriber.loaded:
                self.transcriber.load(
                    self.cfg.model.name, self.cfg.model.device, self.cfg.model.compute_type
                )

    def start_recording(self) -> None:
        self.recorder.start()

    def stop_and_process(self) -> tuple[Transcript, str] | None:
        """Stop recording, transcribe, format, inject. Returns None for too-short clips."""
        clip = self.recorder.stop()
        if clip.duration_s < MIN_CLIP_SECONDS:
            log.info("clip too short (%.2fs) — discarded as accidental toggle", clip.duration_s)
            return None
        return self.process_clip(clip)

    def process_clip(self, clip: AudioClip) -> tuple[Transcript, str]:
        self.load()
        transcript = self.transcriber.transcribe(clip)
        final = self.formatter(transcript.text) if self.formatter else transcript.text
        if self.injector and final:
            self.injector(final)
        if self.on_result:
            self.on_result(transcript, final)
        return transcript, final
