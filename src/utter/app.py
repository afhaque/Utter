"""Assemble the daemon with its UI layers (overlay + tray)."""

from __future__ import annotations

import logging
import shutil
import sys
import winreg

from utter.core.config import Config
from utter.daemon import Daemon
from utter.ui.overlay import Overlay

log = logging.getLogger(__name__)

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def apply_launch_on_startup(enabled: bool) -> None:
    """Sync the HKCU Run entry with [general].launch_on_startup."""
    if getattr(sys, "frozen", False):
        cmd = f'"{sys.executable}" start'
    else:
        exe = shutil.which("utter")
        cmd = f'"{exe}" start' if exe else f'"{sys.executable}" -m utter start'
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, "Utter", 0, winreg.REG_SZ, cmd)
                log.info("launch-on-startup enabled: %s", cmd)
            else:
                try:
                    winreg.DeleteValue(key, "Utter")
                    log.info("launch-on-startup disabled")
                except FileNotFoundError:
                    pass
    except OSError:
        log.exception("could not update launch-on-startup registry entry")


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
    from utter.ui.tray import Tray

    apply_launch_on_startup(cfg.general.launch_on_startup)
    daemon, _overlay = build(cfg)
    daemon.start()
    tray = Tray(daemon)
    try:
        tray.run()  # pystray owns the main thread (ADR 0001); returns on Quit
    finally:
        daemon.shutdown()
