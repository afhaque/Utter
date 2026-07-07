"""Filesystem locations for Utter state.

Everything lives under %APPDATA%\\Utter (overridable with UTTER_HOME for tests).
"""

import os
from pathlib import Path


def utter_home() -> Path:
    override = os.environ.get("UTTER_HOME")
    if override:
        home = Path(override)
    else:
        home = Path(os.environ.get("APPDATA", Path.home())) / "Utter"
    home.mkdir(parents=True, exist_ok=True)
    return home


def config_path() -> Path:
    return utter_home() / "config.toml"


def history_db_path() -> Path:
    return utter_home() / "history.db"


def status_path() -> Path:
    return utter_home() / "status.json"


def log_dir() -> Path:
    d = utter_home() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def lock_name() -> str:
    """Name of the Win32 mutex used by the single-instance guard.

    Derived from the (possibly overridden) home dir so tests can run a guarded
    daemon without colliding with a real one.
    """
    safe = str(utter_home()).replace("\\", "_").replace(":", "")
    return f"Local\\UtterDaemon_{safe}"
