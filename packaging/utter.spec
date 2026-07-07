# PyInstaller spec — onedir per BUILD_PLAN §11 (onefile is forbidden: the CUDA DLL set
# makes temp-dir unpacking slow and fragile).
#
# Two exes share one bundle:
#   utter.exe  — console CLI (dictate/config/dashboard/...)
#   utterd.exe — windowless daemon (tray + hotkey), what a shortcut should launch
#
# CPU-only variant: set UTTER_CPU_ONLY=1 before building — skips the NVIDIA DLL tree
# (bundle shrinks by ~a couple of GB; transcription runs int8 on CPU).
#
# Build (from repo root):  pyinstaller packaging/utter.spec --noconfirm

import importlib.util
import os
from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)

cpu_only = os.environ.get("UTTER_CPU_ONLY") == "1"
bundle_name = "utter-cpu" if cpu_only else "utter"
here = Path(SPECPATH)  # packaging/
icon = str(here / "utter.ico")

# the ctranslate2 wheel bundles its own (potentially version-skewed) cudnn copy —
# strip CUDA-family DLLs from it in BOTH variants; the GPU bundle gets the single
# pinned set under _internal/nvidia/*/bin instead
_cuda_prefixes = ("cudnn", "cublas", "cudart", "nvblas", "nvrtc")
binaries = [
    (src, dest) for src, dest in collect_dynamic_libs("ctranslate2")
    if not Path(src).name.lower().startswith(_cuda_prefixes)
]
if not cpu_only:
    # cuBLAS + cuDNN into _internal/nvidia/<pkg>/bin — exactly where utter.gpu's
    # frozen branch looks (§12.1). The FULL set matters: cublasLt64_12.dll fails
    # identically to cublas64_12.dll when missing.
    nvidia = importlib.util.find_spec("nvidia")
    if not (nvidia and nvidia.submodule_search_locations):
        raise SystemExit("nvidia wheels not importable — GPU build impossible")
    for loc in nvidia.submodule_search_locations:
        for pkg in ("cublas", "cudnn"):
            bin_dir = Path(loc) / pkg / "bin"
            for dll in bin_dir.glob("*.dll") if bin_dir.is_dir() else []:
                binaries.append((str(dll), f"nvidia/{pkg}/bin"))
    if not any("cublasLt64" in src for src, _ in binaries):
        raise SystemExit("cublasLt64 DLL not found — GPU bundle would be broken")

datas = (
    collect_data_files("faster_whisper")  # Silero VAD onnx assets
    + collect_data_files("textual")       # TUI css
    + [(str(here.parent / "src" / "utter" / "assets" / "logo.jpg"), "utter/assets")]
)

# onnxruntime: faster_whisper imports it lazily for VAD.
# textual: widgets are lazy-loaded via __getattr__/import_module — static analysis
# misses them (packaged `utter dashboard` died on textual.widgets._tab_pane).
hiddenimports = ["onnxruntime"] + collect_submodules("textual")
excludes = ["pytest", "_pytest", "pluggy", "setuptools", "pip"]  # no test frameworks in a user app

a_cli = Analysis(
    [str(here / "launch_utter.py")],
    pathex=[str(here.parent / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
pyz_cli = PYZ(a_cli.pure)
exe_cli = EXE(
    pyz_cli,
    a_cli.scripts,
    [],
    exclude_binaries=True,
    name="utter",
    icon=icon,
    console=True,
    upx=False,
)

a_daemon = Analysis(
    [str(here / "launch_utterd.py")],
    pathex=[str(here.parent / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
pyz_daemon = PYZ(a_daemon.pure)
exe_daemon = EXE(
    pyz_daemon,
    a_daemon.scripts,
    [],
    exclude_binaries=True,
    name="utterd",
    icon=icon,
    console=False,  # windowless: the daemon lives in the tray (Phase 4 acceptance)
    upx=False,
)

coll = COLLECT(
    exe_cli,
    a_cli.binaries,
    a_cli.datas,
    exe_daemon,
    a_daemon.binaries,
    a_daemon.datas,
    name=bundle_name,
    upx=False,
)
