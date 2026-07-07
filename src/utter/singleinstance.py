"""Single-instance guard via a named Win32 mutex (BUILD_PLAN §3.1).

Two daemons would both grab the global hotkey and fight over the mic, so the second
`utter start` must refuse to launch.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes

from utter.paths import lock_name

ERROR_ALREADY_EXISTS = 183


class SingleInstance:
    def __init__(self) -> None:
        self._handle = None

    def acquire(self) -> bool:
        """Try to become the single running daemon. False if one already runs."""
        # use_last_error captures the code at call time — ctypes-internal calls can
        # clobber a later windll.kernel32.GetLastError()
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.CreateMutexW(None, False, lock_name())
        already = ctypes.get_last_error() == ERROR_ALREADY_EXISTS
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        if already:
            kernel32.CloseHandle(handle)
            return False
        self._handle = handle
        return True

    def release(self) -> None:
        if self._handle:
            ctypes.windll.kernel32.CloseHandle(self._handle)
            self._handle = None
