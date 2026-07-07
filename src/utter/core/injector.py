"""Injector — deliver text into the focused app (BUILD_PLAN §7).

Default path: save clipboard -> set clipboard -> Ctrl+V -> restore clipboard.
Fallback path (config [injection].method = "sendinput"): Win32 SendInput
KEYEVENTF_UNICODE typing for paste-hostile apps.

Known limitation (documented in §7): clipboard save/restore is text-only via pyperclip —
non-text clipboard contents (images, files) are not preserved.
"""

from __future__ import annotations

import ctypes
import logging
import time
from ctypes import wintypes

import pyperclip
from pynput.keyboard import Controller, Key

log = logging.getLogger(__name__)

# Modifier virtual-key codes: shift/ctrl/alt (+L/R variants) and win keys (§7 modifier bleed)
_MODIFIER_VKS = (0x10, 0x11, 0x12, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5, 0x5B, 0x5C)

KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_KEYUP = 0x0002
INPUT_KEYBOARD = 1

ULONG_PTR = ctypes.c_size_t


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT)]


class _INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


def wait_modifiers_released(timeout_s: float = 1.0) -> bool:
    """Block until no modifier key is physically down, so Ctrl+V isn't Ctrl+Alt+V."""
    user32 = ctypes.windll.user32
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if not any(user32.GetAsyncKeyState(vk) & 0x8000 for vk in _MODIFIER_VKS):
            log.debug("modifiers released")
            return True
        time.sleep(0.02)
    log.warning("modifiers still held after %.1fs — pasting anyway", timeout_s)
    return False


def send_unicode(text: str) -> None:
    """Type text directly via SendInput KEYEVENTF_UNICODE (paste-hostile apps)."""
    user32 = ctypes.windll.user32
    units = text.encode("utf-16-le")
    inputs = []
    for i in range(0, len(units), 2):
        code = int.from_bytes(units[i : i + 2], "little")
        for flags in (KEYEVENTF_UNICODE, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP):
            inp = _INPUT(type=INPUT_KEYBOARD)
            inp.ki = _KEYBDINPUT(0, code, flags, 0, 0)
            inputs.append(inp)
    array = (_INPUT * len(inputs))(*inputs)
    sent = user32.SendInput(len(inputs), array, ctypes.sizeof(_INPUT))
    if sent != len(inputs):
        raise ctypes.WinError()


class Injector:
    def __init__(self, method: str = "paste", pre_paste_delay_ms: int = 150) -> None:
        self.method = method
        self.pre_paste_delay_ms = pre_paste_delay_ms
        self._kb = Controller()

    def paste(self, text: str) -> None:
        if not text:
            return
        # small delay so the target window regains focus (overlay may just have closed)
        time.sleep(self.pre_paste_delay_ms / 1000)
        wait_modifiers_released()
        if self.method == "sendinput":
            send_unicode(text)
            log.info("injected %d chars via SendInput", len(text))
            return

        prior: str | None = None
        try:
            prior = pyperclip.paste()
        except Exception:  # non-text clipboard — nothing we can restore (documented)
            pass
        pyperclip.copy(text)
        with self._kb.pressed(Key.ctrl):
            self._kb.press("v")
            self._kb.release("v")
        time.sleep(0.3)  # let the target consume the clipboard before restoring
        if prior is not None:
            try:
                pyperclip.copy(prior)
            except Exception:
                log.warning("could not restore prior clipboard")
        log.info("injected %d chars via clipboard paste", len(text))
