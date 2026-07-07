"""PyInstaller entry: the windowless daemon exe (utterd.exe) — always `utter start`."""

import sys

from utter.cli import main

if __name__ == "__main__":
    sys.argv = [sys.argv[0], "start"]
    main()
