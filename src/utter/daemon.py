"""The Utter daemon — hotkey-driven dictation loop (ADR 0001).

Threading model: the pynput hotkey callback only enqueues toggle events; a dedicated
worker thread runs the blocking record→transcribe→format→inject chain. UI layers
(overlay Phase 3, tray Phase 4) attach via optional hooks so this stays headless-testable.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import threading
from datetime import UTC, datetime

from utter.core.config import Config
from utter.core.formatting import format_text
from utter.core.history import HistoryStore
from utter.core.injector import Injector
from utter.core.pipeline import Pipeline
from utter.core.transcription import Transcript
from utter.hotkey import HotkeyController
from utter.paths import config_path, status_path

log = logging.getLogger(__name__)


class Daemon:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.injector = Injector(
            method=cfg.injection.method, pre_paste_delay_ms=cfg.injection.pre_paste_delay_ms
        )
        self.history = HistoryStore()
        self.pipeline = Pipeline(
            cfg, formatter=self._format, injector=self.injector.paste, on_result=self._record
        )
        self.hotkey = HotkeyController()
        self.paused = False
        self._events: queue.Queue[str] = queue.Queue()
        self._worker = threading.Thread(target=self._run_worker, name="utter-worker", daemon=True)
        self._stop = threading.Event()
        # UI hooks (set by overlay/tray layers)
        self.on_recording_started = None
        self.on_transcribing = None
        self.on_idle = None

    # -- pipeline hooks -------------------------------------------------------------------
    def _format(self, text: str) -> str:
        return format_text(text, self.cfg.formatting)  # reads live cfg: survives hot-reload

    def _record(self, transcript: Transcript, final: str) -> None:
        if self.cfg.privacy.save_history:
            self.history.add(
                raw=transcript.text,
                final=final,
                latency_ms=transcript.latency_ms,
                model=self.cfg.model.name,
                language=transcript.language,
            )
        self.publish_status()

    # -- daemon -> TUI status (ADR 0001 file-based IPC) -----------------------------------
    def publish_status(self, running: bool = True) -> None:
        status = {
            "running": running,
            "pid": os.getpid(),
            "model": self.cfg.model.name,
            "device": self.transcriber_device,
            "hotkey": self.cfg.general.hotkey,
            "paused": self.paused,
            "updated": datetime.now(UTC).isoformat(),
        }
        try:
            status_path().write_text(json.dumps(status, indent=2), encoding="utf-8")
        except OSError:
            log.exception("could not write status.json")

    @property
    def transcriber_device(self) -> str:
        return self.pipeline.transcriber.device

    # -- config hot-reload (TUI writes config.toml; we watch its mtime) -------------------
    def _watch_config(self) -> None:
        from utter.core import config as config_store

        path = config_path()
        last = path.stat().st_mtime if path.exists() else 0.0
        while not self._stop.wait(1.0):
            try:
                mtime = path.stat().st_mtime if path.exists() else 0.0
                if mtime != last:
                    last = mtime
                    self.reload_config(config_store.load())
            except Exception:
                log.exception("config watch failed")

    # -- hotkey side (must return fast) -------------------------------------------------
    def toggle(self) -> None:
        self._events.put("toggle")

    # -- worker side ---------------------------------------------------------------------
    def _run_worker(self) -> None:
        while not self._stop.is_set():
            try:
                event = self._events.get(timeout=0.25)
            except queue.Empty:
                continue
            if event != "toggle" or self.paused:
                continue
            try:
                self._handle_toggle()
            except Exception:
                log.exception("dictation cycle failed")
                self._notify(self.on_idle)

    def _handle_toggle(self) -> None:
        if not self.pipeline.recorder.recording:
            self.pipeline.start_recording()
            self._notify(self.on_recording_started)
        else:
            self._notify(self.on_transcribing)
            transcript, final = self.pipeline.stop_and_process()
            log.info("dictated: %r (%.0f ms)", final, transcript.latency_ms)
            self._notify(self.on_idle)

    @staticmethod
    def _notify(hook) -> None:
        if hook:
            try:
                hook()
            except Exception:
                log.exception("UI hook failed")

    # -- lifecycle -----------------------------------------------------------------------
    def start(self) -> None:
        """Load the model, start the worker, register the hotkey, watch the config."""
        self.pipeline.load()
        self._worker.start()
        self.hotkey.register(self.cfg.general.hotkey, self.toggle)
        threading.Thread(target=self._watch_config, name="utter-cfgwatch", daemon=True).start()
        self.publish_status()
        log.info("daemon ready — press %s to dictate", self.cfg.general.hotkey)

    def reload_config(self, cfg: Config) -> None:
        """Hot-reload: re-register hotkey and refresh injection prefs (Phase 6 IPC)."""
        old = self.cfg
        self.cfg = cfg
        self.pipeline.cfg = cfg
        if cfg.general.hotkey != old.general.hotkey:
            self.hotkey.register(cfg.general.hotkey, self.toggle)
            log.info("hotkey re-registered: %s -> %s", old.general.hotkey, cfg.general.hotkey)
        self.injector.method = cfg.injection.method
        self.injector.pre_paste_delay_ms = cfg.injection.pre_paste_delay_ms
        self.publish_status()
        log.info("config hot-reloaded")

    def shutdown(self) -> None:
        self._stop.set()
        self.hotkey.unregister()
        if self.pipeline.recorder.recording:
            self.pipeline.recorder.stop()  # release the mic
        self.publish_status(running=False)
        log.info("daemon shut down cleanly")

    def run_forever(self) -> None:
        self.start()
        try:
            self._stop.wait()
        except KeyboardInterrupt:
            pass
        finally:
            self.shutdown()
