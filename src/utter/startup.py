"""Launch-on-startup: reconcile config with the HKCU Run registry entry.

Reconcile rules (both directions, so an installer-written entry survives):
- Run key exists but config says false  -> the user enabled it EXTERNALLY (e.g. the
  installer's checkbox); adopt it into config instead of deleting their choice.
- config true  -> (re)write the key, so it always points at the current install.
- config false and no key -> nothing to do.
"""

from __future__ import annotations

import logging
import winreg

from utter.core import config as config_store
from utter.core.config import Config
from utter.paths import daemon_run_value

log = logging.getLogger(__name__)

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_VALUE_NAME = "Utter"


def _read_existing() -> str | None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            return winreg.QueryValueEx(key, _VALUE_NAME)[0]
    except OSError:
        return None


def sync_launch_on_startup(cfg: Config, adopt_external: bool = False) -> Config:
    """Bring config and registry into agreement. Returns the (possibly updated) cfg.

    adopt_external=True is for daemon STARTUP only: a Run key that exists while config
    says false means someone enabled it outside Utter (the installer checkbox) — honor
    it. During hot-reload it must be False, otherwise switching the TUI toggle off
    would instantly re-adopt the not-yet-deleted key back to on.
    """
    try:
        existing = _read_existing()
        if adopt_external and existing is not None and not cfg.general.launch_on_startup:
            cfg.general.launch_on_startup = True
            config_store.save(cfg)
            log.info("adopted externally-enabled launch-on-startup (installer/registry)")
            return cfg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if cfg.general.launch_on_startup:
                value = daemon_run_value()
                if existing != value:
                    winreg.SetValueEx(key, _VALUE_NAME, 0, winreg.REG_SZ, value)
                    log.info("launch-on-startup enabled: %s", value)
            elif existing is not None:
                winreg.DeleteValue(key, _VALUE_NAME)
                log.info("launch-on-startup disabled")
    except OSError:
        log.exception("could not sync launch-on-startup registry entry")
    return cfg
