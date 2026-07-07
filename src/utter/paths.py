"""Filesystem locations for Utter state.

Everything lives under %APPDATA%\\Utter (overridable with UTTER_HOME for tests).
"""

import os
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=8)  # keyed on the resolved path: mkdir once, not per lookup
def _ensure_dir(path_str: str) -> Path:
    home = Path(path_str)
    home.mkdir(parents=True, exist_ok=True)
    return home


def utter_home() -> Path:
    override = os.environ.get("UTTER_HOME")
    if override:
        return _ensure_dir(override)
    return _ensure_dir(str(Path(os.environ.get("APPDATA", Path.home())) / "Utter"))


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
