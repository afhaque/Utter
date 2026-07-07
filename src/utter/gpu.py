"""CUDA DLL shim + device detection (BUILD_PLAN §12.1).

The pip ctranslate2 wheel does NOT bundle cuBLAS/cuDNN. Their DLL directories must be
registered BEFORE anything imports ctranslate2/faster_whisper, or CUDA init fails with
"Library cublas64_12.dll is not found". Call register_dlls() first — every module that
touches transcription imports it via this module.

Layout-aware: dev resolves site-packages/nvidia/{cublas,cudnn}/bin; a PyInstaller onedir
build resolves under sys._MEIPASS/_internal (PyInstaller >= 6 layout).
"""

from __future__ import annotations

import importlib.util
import logging
import os
import sys
from functools import lru_cache
from pathlib import Path

log = logging.getLogger(__name__)


def _candidate_dirs() -> list[Path]:
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent / "_internal"))
        return [
            base,
            base / "nvidia" / "cublas" / "bin",
            base / "nvidia" / "cudnn" / "bin",
        ]
    dirs: list[Path] = []
    spec = importlib.util.find_spec("nvidia")
    if spec and spec.submodule_search_locations:
        for loc in spec.submodule_search_locations:
            for pkg in ("cublas", "cudnn"):
                dirs.append(Path(loc) / pkg / "bin")
    return dirs


@lru_cache(maxsize=1)
def register_dlls() -> list[str]:
    """Register cuBLAS/cuDNN DLL dirs. Idempotent. Returns the dirs registered."""
    registered: list[str] = []
    for d in _candidate_dirs():
        if not d.is_dir():
            continue
        # Belt and suspenders (§12.1): add_dll_directory is the documented mechanism,
        # but PATH-prepend is what actually resolved on the target machine.
        os.add_dll_directory(str(d))
        os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")
        registered.append(str(d))
    if registered:
        log.debug("CUDA DLL dirs registered: %s", registered)
    else:
        log.warning("No NVIDIA DLL dirs found — CUDA will be unavailable")
    return registered


def detect_device() -> str:
    """Return 'cuda' if a usable CUDA device exists, else 'cpu'."""
    register_dlls()
    try:
        import ctranslate2

        if ctranslate2.get_cuda_device_count() > 0:
            return "cuda"
    except Exception as exc:  # any DLL/driver failure means CPU fallback
        log.warning("CUDA detection failed, falling back to CPU: %s", exc)
    return "cpu"


def resolve_device(configured: str) -> str:
    """Map a configured device (cuda|cpu|auto) to a concrete one.

    'cuda' and 'auto' both probe — a broken CUDA setup degrades gracefully to CPU.
    """
    return "cpu" if configured == "cpu" else detect_device()
