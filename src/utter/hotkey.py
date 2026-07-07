"""HotkeyController — global hotkey via Win32 RegisterHotKey (BUILD_PLAN §12.3 fallback).

pynput was the planned primary, but its GlobalHotKeys failed to match combos on the
target machine (canonicalization regression: canonical(Key.space) yields a raw vk
KeyCode that never equals the parsed <space>). RegisterHotKey is the sanctioned robust
fallback: no admin needed, layout-independent, and it suppresses the combo from reaching
other apps — which is what a dictation toggle wants anyway.

The hotkey lives on a dedicated message-loop thread (RegisterHotKey with a NULL hwnd is
thread-scoped; WM_HOTKEY lands in that thread's queue). The callback must return fast —
callers hand in an on_toggle that only enqueues an event (ADR 0001).
"""

from __future__ import annotations

import ctypes
import logging
import threading
from collections.abc import Callable
from ctypes import wintypes

log = logging.getLogger(__name__)

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
_HOTKEY_ID = 1

_MODS = {"ctrl": MOD_CONTROL, "alt": MOD_ALT, "shift": MOD_SHIFT, "win": MOD_WIN}
_NAMED_VKS = {
    "space": 0x20, "tab": 0x09, "enter": 0x0D, "esc": 0x1B, "backspace": 0x08,
    "home": 0x24, "end": 0x23, "insert": 0x2D, "delete": 0x2E,
    "page_up": 0x21, "page_down": 0x22,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    **{f"f{n}": 0x6F + n for n in range(1, 25)},
}


def parse_combo(combo: str) -> tuple[int, int]:
    """'ctrl+alt+space' -> (MOD_CONTROL|MOD_ALT, VK_SPACE). Exactly one non-modifier key."""
    mods = 0
    vk: int | None = None
    for raw in combo.split("+"):
        part = raw.strip().lower()
        if not part:
            continue
        if part in _MODS:
            mods |= _MODS[part]
        elif part in _NAMED_VKS:
            if vk is not None:
                raise ValueError(f"multiple non-modifier keys in combo: {combo!r}")
            vk = _NAMED_VKS[part]
        elif len(part) == 1 and (part.isalnum()):
            if vk is not None:
                raise ValueError(f"multiple non-modifier keys in combo: {combo!r}")
            vk = ord(part.upper())
        else:
            raise ValueError(f"unknown key {part!r} in combo {combo!r}")
    if vk is None:
        raise ValueError(f"combo has no non-modifier key: {combo!r}")
    return mods, vk


class HotkeyController:
    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._ready = threading.Event()
        self._error: str | None = None
        self.combo: str = ""

    def register(self, combo: str, on_toggle: Callable[[], None]) -> None:
        self.unregister()
        mods, vk = parse_combo(combo)
        self._ready.clear()
        self._error = None
        self._thread = threading.Thread(
            target=self._run, args=(mods, vk, on_toggle), name="utter-hotkey", daemon=True
        )
        self._thread.start()
        self._ready.wait(timeout=5)
        if self._error:
            raise RuntimeError(f"could not register hotkey {combo!r}: {self._error}")
        self.combo = combo
        log.info("hotkey registered: %s", combo)

    def _run(self, mods: int, vk: int, on_toggle: Callable[[], None]) -> None:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        self._thread_id = kernel32.GetCurrentThreadId()
        if not user32.RegisterHotKey(None, _HOTKEY_ID, mods | MOD_NOREPEAT, vk):
            self._error = str(ctypes.WinError())
            self._ready.set()
            return
        self._ready.set()
        try:
            msg = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY and msg.wParam == _HOTKEY_ID:
                    try:
                        on_toggle()
                    except Exception:
                        log.exception("hotkey callback failed")
        finally:
            user32.UnregisterHotKey(None, _HOTKEY_ID)

    def unregister(self) -> None:
        if self._thread is not None and self._thread.is_alive() and self._thread_id:
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
            self._thread.join(timeout=5)
            log.info("hotkey unregistered: %s", self.combo)
        self._thread = None
        self._thread_id = None
