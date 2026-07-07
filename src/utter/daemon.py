"""The Utter daemon — hotkey-driven dictation loop (ADR 0001).

Threading model: the pynput hotkey callback only enqueues toggle events; a dedicated
worker thread runs the blocking record→transcribe→format→inject chain. UI layers
(overlay Phase 3, tray Phase 4) attach via optional hooks so this stays headless-testable.
"""

from __future__ import annotations

import logging
import queue
import threading

from utter.core.config import Config
from utter.core.injector import Injector
from utter.core.pipeline import Pipeline
from utter.hotkey import HotkeyController

log = logging.getLogger(__name__)


class Daemon:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.injector = Injector(
            method=cfg.injection.method, pre_paste_delay_ms=cfg.injection.pre_paste_delay_ms
        )
        self.pipeline = Pipeline(cfg, injector=self.injector.paste)
        self.hotkey = HotkeyController()
        self.paused = False
        self._events: queue.Queue[str] = queue.Queue()
        self._worker = threading.Thread(target=self._run_worker, name="utter-worker", daemon=True)
        self._stop = threading.Event()
        # UI hooks (set by overlay/tray layers)
        self.on_recording_started = None
        self.on_transcribing = None
        self.on_idle = None

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
        """Load the model, start the worker, and register the hotkey."""
        self.pipeline.load()
        self._worker.start()
        self.hotkey.register(self.cfg.general.hotkey, self.toggle)
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
        log.info("config hot-reloaded")

    def shutdown(self) -> None:
        self._stop.set()
        self.hotkey.unregister()
        if self.pipeline.recorder.recording:
            self.pipeline.recorder.stop()  # release the mic
        log.info("daemon shut down cleanly")

    def run_forever(self) -> None:
        self.start()
        try:
            self._stop.wait()
        except KeyboardInterrupt:
            pass
        finally:
            self.shutdown()
