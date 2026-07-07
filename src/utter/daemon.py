"""The Utter daemon — hotkey-driven dictation loop (ADR 0001).

Threading model: the hotkey callback only enqueues toggle events; a dedicated worker
thread runs the blocking record→transcribe→format→inject chain. UI layers (overlay,
tray) attach via optional hooks so this stays headless-testable.
"""

from __future__ import annotations

import ctypes
import json
import logging
import os
import queue
import shutil
import subprocess
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

_STOP = object()  # worker-queue sentinel


class Daemon:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.injector = Injector(cfg_getter=lambda: self.cfg.injection)
        self.history = HistoryStore()
        self.pipeline = Pipeline(
            cfg, formatter=self._format, injector=self._inject, on_result=self._record
        )
        self.hotkey = HotkeyController()
        self._paused = False
        self.last_error: str = ""
        self._target_hwnd: int | None = None  # focused window when recording started
        self._events: queue.Queue[object] = queue.Queue()
        self._worker = threading.Thread(target=self._run_worker, name="utter-worker", daemon=True)
        self._stop = threading.Event()
        # UI hooks (set by overlay/tray layers)
        self.on_recording_started = None
        self.on_transcribing = None
        self.on_idle = None

    # -- pipeline hooks -------------------------------------------------------------------
    def _format(self, text: str) -> str:
        return format_text(text, self.cfg.formatting)  # reads live cfg: survives hot-reload

    def _inject(self, text: str) -> None:
        self.injector.paste(text, target_hwnd=self._target_hwnd)

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

    # -- pause (owned here so status.json can never go stale — UI layers call this) --------
    @property
    def paused(self) -> bool:
        return self._paused

    def set_paused(self, paused: bool) -> None:
        self._paused = paused
        if paused and self.pipeline.recorder.recording:
            # privacy: pausing must never leave the mic open; discard, don't paste
            clip = self.pipeline.recorder.stop()
            log.info("pause discarded an active %.1fs recording", clip.duration_s)
            self._notify(self.on_idle)
        self.publish_status()
        log.info("dictation %s", "paused" if paused else "resumed")

    # -- daemon -> TUI status (ADR 0001 file-based IPC) -----------------------------------
    def publish_status(self, running: bool = True) -> None:
        status = {
            "running": running,
            "pid": os.getpid(),
            "model": self.cfg.model.name,
            "device": self.pipeline.transcriber.device,
            "vram": _vram_usage(),
            "hotkey": self.cfg.general.hotkey,
            "paused": self._paused,
            "error": self.last_error,
            "updated": datetime.now(UTC).isoformat(),
        }
        try:
            status_path().write_text(json.dumps(status, indent=2), encoding="utf-8")
        except OSError:
            log.exception("could not write status.json")

    # -- config hot-reload (TUI writes config.toml; we watch its mtime) -------------------
    def _watch_config(self) -> None:
        from utter.core import config as config_store

        path = config_path()
        last = path.stat().st_mtime if path.exists() else 0.0
        while not self._stop.wait(1.0):
            try:
                mtime = path.stat().st_mtime if path.exists() else 0.0
                if mtime != last:
                    self.reload_config(config_store.load())
                    last = mtime  # only advance after a successful reload — retry torn reads
            except Exception:
                log.exception("config watch failed")

    def reload_config(self, cfg: Config) -> None:
        """Hot-reload: re-register hotkey and swap live prefs. A bad hotkey is rejected
        without losing the working one (HotkeyController rolls back internally)."""
        old_hotkey = self.cfg.general.hotkey
        if cfg.general.hotkey != old_hotkey:
            try:
                self.hotkey.register(cfg.general.hotkey, self.toggle)
                log.info("hotkey re-registered: %s -> %s", old_hotkey, cfg.general.hotkey)
            except (ValueError, RuntimeError) as exc:
                log.error("rejected hotkey %r: %s — keeping %r",
                          cfg.general.hotkey, exc, old_hotkey)
                cfg.general.hotkey = old_hotkey
        from utter.startup import sync_launch_on_startup

        cfg = sync_launch_on_startup(cfg)  # TUI startup switch takes effect without restart
        self.cfg = cfg  # formatter/injector read this live — nothing else to plumb
        self.pipeline.cfg = cfg
        self.publish_status()
        log.info("config hot-reloaded")

    # -- hotkey side (must return fast) -------------------------------------------------
    def toggle(self) -> None:
        self._events.put("toggle")

    # -- worker side ---------------------------------------------------------------------
    def _run_worker(self) -> None:
        while True:
            event = self._events.get()
            if event is _STOP:
                return
            # while paused, still allow STOPPING an active recording — a swallowed stop
            # would leave the mic open and buffer growing while the user believes it's off
            if self._paused and not self.pipeline.recorder.recording:
                continue
            try:
                self._handle_toggle()
                self.last_error = ""
            except Exception as exc:
                log.exception("dictation cycle failed")
                self.last_error = f"dictation failed: {exc}"
                self.publish_status()
                self._notify(self.on_idle)

    def _handle_toggle(self) -> None:
        if not self.pipeline.recorder.recording:
            self._target_hwnd = ctypes.windll.user32.GetForegroundWindow()
            self.pipeline.start_recording()
            self._notify(self.on_recording_started)
        else:
            self._notify(self.on_transcribing)
            result = self.pipeline.stop_and_process()
            if result is not None:
                transcript, final = result
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
        """Register the hotkey and watcher immediately; load the model in the background
        (first toggle simply waits on the load lock if it wins the race)."""
        self._worker.start()
        self.hotkey.register(self.cfg.general.hotkey, self.toggle)
        threading.Thread(target=self._watch_config, name="utter-cfgwatch", daemon=True).start()
        self.publish_status()
        threading.Thread(target=self._load_model, name="utter-modelload", daemon=True).start()
        log.info("daemon ready — press %s to dictate", self.cfg.general.hotkey)

    def _load_model(self) -> None:
        try:
            self.pipeline.load()
            self.last_error = ""
            self.publish_status()  # device is now concrete (cuda/cpu)
        except Exception as exc:
            log.exception("model load failed")
            self.last_error = f"model load failed: {exc}"
            self.publish_status()

    def shutdown(self) -> None:
        self._stop.set()
        self._events.put(_STOP)
        self.hotkey.unregister()
        if self.pipeline.recorder.recording:
            self.pipeline.recorder.stop()  # release the mic
        if self._worker.is_alive():
            self._worker.join(timeout=10)
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


_NVIDIA_SMI = shutil.which("nvidia-smi")


def _vram_usage() -> str:
    """Best-effort 'used/total MiB' via nvidia-smi; empty string when unavailable."""
    if not _NVIDIA_SMI:
        return ""
    try:
        out = subprocess.run(
            [_NVIDIA_SMI, "--query-gpu=memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        used, total = out.stdout.strip().splitlines()[0].split(",")
        return f"{used.strip()}/{total.strip()} MiB"
    except Exception:
        return ""
