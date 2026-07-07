"""PyInstaller entry: the windowless daemon exe (utterd.exe) — always `utter start`."""

import os
import sys

if __name__ == "__main__":
    # windowless exe: stdout/stderr are None, which crashes any first- or third-party
    # code that writes to them (tqdm, click, tracebacks). Bind them once, here —
    # the file log is the real output channel for the daemon.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115

    from utter.cli import main

    sys.argv = [sys.argv[0], "start"]
    main()
