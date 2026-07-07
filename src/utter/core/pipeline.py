"""Pipeline — orchestrates record → transcribe → format → inject (BUILD_PLAN §3).

Headless and importable: no GUI dependency. Formatter/injector/history are optional
hooks so Phase 1 runs the bare record→transcribe core and later phases plug in.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from utter.core.config import Config
from utter.core.recorder import AudioClip, RecorderService
from utter.core.transcription import FasterWhisperService, Transcript

log = logging.getLogger(__name__)


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
            beam_size=cfg.model.beam_size, language=cfg.model.language
        )
        self.formatter = formatter
        self.injector = injector
        self.on_result = on_result

    def load(self) -> None:
        """Load the model once and keep it resident (§10). Includes warmup."""
        if not self.transcriber.loaded:
            self.transcriber.load(
                self.cfg.model.name, self.cfg.model.device, self.cfg.model.compute_type
            )

    def start_recording(self) -> None:
        self.recorder.start()

    def stop_and_process(self) -> tuple[Transcript, str]:
        """Stop recording, transcribe, format, inject. Returns (transcript, final_text)."""
        clip = self.recorder.stop()
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
