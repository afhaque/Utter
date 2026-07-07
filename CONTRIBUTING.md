# Contributing to Utter

Thanks for wanting to help. Utter is a small, single-language (Python) codebase — the
whole record→transcribe→format→paste pipeline is importable without any UI.

## Dev setup

```powershell
git clone https://github.com/afhaque/Utter.git
cd Utter
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
```

Python 3.11+ on Windows. An NVIDIA GPU is optional — everything falls back to CPU
(`--device cpu`), just slower.

## Layout

- `src/utter/core/` — headless pipeline: recorder, transcription, formatting, injector,
  pipeline, config, history. No GUI imports here, ever.
- `src/utter/ui/` — thin layers on top: overlay (Tk), tray (pystray), TUI (Textual).
- `src/utter/daemon.py` — wires hotkey → worker thread → pipeline. Read
  `docs/adr/0001-concurrency-model.md` before touching threading.
- `src/utter/gpu.py` — the cuBLAS/cuDNN DLL shim. Must run before anything imports
  ctranslate2/faster-whisper. See BUILD_PLAN.md §12.1 for why.
- `packaging/utter.spec` — PyInstaller onedir spec (GPU + CPU variants).

## Checks

```powershell
.venv\Scripts\ruff check .
.venv\Scripts\pytest -q                      # fast suite
$env:UTTER_INTEGRATION = "1"; pytest -q      # + model-loading integration test
```

Both must pass before a PR. CI runs the fast suite on windows-latest.

## Rules of the road

- Version pins in `pyproject.toml` for faster-whisper/ctranslate2/nvidia wheels are
  load-bearing (Blackwell sm_120 support) — bump them only deliberately and re-test on
  a real GPU (BUILD_PLAN.md §2.1).
- Nothing may leave the machine: no telemetry, no cloud calls. Network is allowed only
  for Hugging Face model downloads and localhost Ollama.
- Every user-facing behavior claim needs a test or a documented manual check.
- Config vocabularies (model sizes, devices, capitalization modes) live in
  `core/config.py` — add new values there, not in the TUI.
