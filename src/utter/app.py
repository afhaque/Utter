"""Assemble the daemon with its UI layers (overlay now, tray in Phase 4)."""

from __future__ import annotations

import logging

from utter.core.config import Config
from utter.daemon import Daemon
from utter.ui.overlay import Overlay

log = logging.getLogger(__name__)


def build(cfg: Config) -> tuple[Daemon, Overlay | None]:
    daemon = Daemon(cfg)
    overlay: Overlay | None = None
    if cfg.general.overlay:
        overlay = Overlay()
        overlay.start()
        recorder = daemon.pipeline.recorder
        daemon.on_recording_started = lambda: overlay.show_recording(lambda: recorder.level)
        daemon.on_transcribing = overlay.show_transcribing
        daemon.on_idle = overlay.hide
    return daemon, overlay


def run(cfg: Config) -> None:
    daemon, _overlay = build(cfg)
    daemon.run_forever()
