"""System tray icon + menu (pystray). Owns the main thread per ADR 0001."""

from __future__ import annotations

import logging
import os
import subprocess

import pystray
from PIL import Image, ImageDraw

from utter.daemon import Daemon
from utter.paths import cli_command, config_path

log = logging.getLogger(__name__)


def _icon_image(size: int = 64) -> Image.Image:
    """The otter logo, center-cropped square; falls back to a drawn mic glyph."""
    try:
        from importlib import resources

        with resources.files("utter").joinpath("assets/logo.jpg").open("rb") as f:
            img = Image.open(f).convert("RGBA")
        side = min(img.size)
        left = (img.width - side) // 2
        top = (img.height - side) // 2
        return img.crop((left, top, left + side, top + side)).resize(
            (size, size), Image.LANCZOS
        )
    except Exception:
        log.warning("logo asset unavailable — using drawn mic glyph")
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((2, 2, size - 2, size - 2), radius=14, fill=(22, 22, 30, 255))
    d.rounded_rectangle((24, 10, 40, 36), radius=8, fill=(122, 162, 247, 255))
    d.arc((18, 22, 46, 46), start=0, end=180, fill=(169, 177, 214, 255), width=3)
    d.line((32, 46, 32, 54), fill=(169, 177, 214, 255), width=3)
    return img


class Tray:
    def __init__(self, daemon: Daemon) -> None:
        self.daemon = daemon
        self.icon = pystray.Icon(
            "utter",
            icon=_icon_image(),
            title="Utter — local dictation",
            menu=pystray.Menu(
                pystray.MenuItem(self._pause_label, self._toggle_pause),
                pystray.MenuItem("Open Dashboard", self._open_dashboard),
                pystray.MenuItem("Settings", self._open_settings),
                pystray.MenuItem("Quit", self._quit),
            ),
        )

    def _pause_label(self, _item) -> str:
        return "Resume dictation" if self.daemon.paused else "Pause dictation"

    def _toggle_pause(self, _icon, _item) -> None:
        self.daemon.set_paused(not self.daemon.paused)

    def _open_dashboard(self, _icon, _item) -> None:
        subprocess.Popen(cli_command("dashboard"), creationflags=subprocess.CREATE_NEW_CONSOLE)
        log.info("dashboard launched")

    def _open_settings(self, _icon, _item) -> None:
        os.startfile(config_path())  # noqa: S606 — open in the user's editor

    def _quit(self, icon, _item) -> None:
        log.info("quit requested from tray")
        self.daemon.shutdown()
        icon.stop()

    def run(self) -> None:
        """Blocks the main thread until Quit."""
        self.icon.run()
