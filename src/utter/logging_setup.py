"""Logging: console + rotating file at %APPDATA%\\Utter\\logs\\utter.log."""

import logging
import logging.handlers

from utter.paths import log_dir

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def setup(level: int = logging.INFO, console: bool = True) -> None:
    root = logging.getLogger()
    if root.handlers:  # already configured
        return
    root.setLevel(level)
    file_handler = logging.handlers.RotatingFileHandler(
        log_dir() / "utter.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(file_handler)
    if console:
        stream = logging.StreamHandler()
        stream.setFormatter(logging.Formatter(_FORMAT))
        root.addHandler(stream)
