"""Filesystem locations for Utter state, plus frozen-vs-dev invocation knowledge.

Everything lives under %APPDATA%\\Utter (overridable with UTTER_HOME for tests).
"""

import os
import shutil
import sys
from functools import lru_cache
from pathlib import Path


def cli_command(*args: str) -> list[str]:
    """How to invoke the Utter CLI from THIS installation (frozen bundle or dev)."""
    if getattr(sys, "frozen", False):
        # both exes sit side by side in the onedir bundle; the console CLI is utter.exe
        return [str(Path(sys.executable).with_name("utter.exe")), *args]
    exe = shutil.which("utter")
    if exe:
        return [exe, *args]
    return [sys.executable, "-m", "utter", *args]


def daemon_run_value() -> str:
    """Registry Run-key command: always the WINDOWLESS daemon exe when frozen —
    a console exe at login would flash a terminal at the user."""
    if getattr(sys, "frozen", False):
        return f'"{Path(sys.executable).with_name("utterd.exe")}"'
    return " ".join(f'"{part}"' if " " in part else part for part in cli_command("start"))


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
