"""RecorderService — mic capture at 16 kHz mono float32 (Whisper-native, BUILD_PLAN §12.2)."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

import numpy as np
import sounddevice as sd

log = logging.getLogger(__name__)


@dataclass
class AudioClip:
    samples: np.ndarray  # mono float32
    sample_rate: int

    @property
    def duration_s(self) -> float:
        return len(self.samples) / self.sample_rate


def _resolve_device(input_device: str) -> int | str | None:
    if input_device in ("default", ""):
        return None
    if input_device.isdigit():
        return int(input_device)
    return input_device


class RecorderService:
    """Capture mic audio into an internal buffer between start() and stop()."""

    def __init__(self, sample_rate: int = 16000, input_device: str = "default") -> None:
        self._sample_rate = sample_rate
        self._device = _resolve_device(input_device)
        self._chunks: list[np.ndarray] = []
        self._lock = threading.Lock()
        self._stream: sd.InputStream | None = None
        self._level = 0.0

    @property
    def recording(self) -> bool:
        return self._stream is not None

    @property
    def level(self) -> float:
        """Rough live input level (0..1) for the overlay animation."""
        return self._level

    def start(self) -> None:
        if self._stream is not None:
            return

        def callback(indata, _frames, _time, status) -> None:
            if status:
                log.warning("audio status: %s", status)
            with self._lock:
                self._chunks.append(indata[:, 0].copy())
            self._level = min(1.0, float(np.abs(indata).max()) * 4)

        self._chunks = []
        self._stream = sd.InputStream(
            samplerate=self._sample_rate,
            channels=1,
            dtype="float32",
            device=self._device,
            callback=callback,
        )
        self._stream.start()
        log.info(
            "recording started (device=%s, %d Hz)", self._device or "default", self._sample_rate
        )

    def stop(self) -> AudioClip:
        if self._stream is None:
            return AudioClip(np.zeros(0, dtype=np.float32), self._sample_rate)
        self._stream.stop()
        self._stream.close()
        self._stream = None
        self._level = 0.0
        with self._lock:
            samples = (
                np.concatenate(self._chunks)
                if self._chunks
                else np.zeros(0, dtype=np.float32)
            )
            self._chunks = []
        clip = AudioClip(samples, self._sample_rate)
        log.info("recording stopped: %.2fs captured", clip.duration_s)
        return clip


def load_wav(path: str) -> AudioClip:
    """Load a 16-bit PCM WAV as a mono float32 clip (for --input-file and tests)."""
    import wave

    with wave.open(path, "rb") as w:
        rate = w.getframerate()
        frames = w.readframes(w.getnframes())
        data = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
        if w.getnchannels() > 1:
            data = data.reshape(-1, w.getnchannels()).mean(axis=1)
    return AudioClip(data, rate)
