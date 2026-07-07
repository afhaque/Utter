<p align="center">
  <img src="logo.jpg" width="240" alt="Utter logo — an otter sitting on a telephone handset sitting on a microphone" />
</p>

<h1 align="center">Utter</h1>

<p align="center">
  A free, open-source, fully local dictation app for Windows.<br/>
  Press a hotkey anywhere, speak, press it again — your words are transcribed on
  <em>your</em> GPU and pasted into whatever app has focus.
</p>

---

## Why

Cloud dictation tools charge a subscription to do something a modern consumer GPU
already does well. Utter runs Whisper-family models locally via
[faster-whisper](https://github.com/SYSTRAN/faster-whisper): no account, no audio
leaving your machine, no per-month fee. On an RTX-class GPU, a 5-second utterance
transcribes in about half a second with the most accurate model.

## Privacy, plainly

Everything — audio capture, transcription, formatting, pasting, history — happens
on-device. The only network traffic is (a) a one-time model download from Hugging Face
and (b) calls to `localhost` Ollama **if** you enable the optional LLM formatting pass.
No telemetry, no cloud, no account. History is a local SQLite file you can disable
(`[privacy] save_history = false`) or delete.

## Install

### Packaged build (no Python needed)

1. Grab the `utter` folder (GPU build, NVIDIA required) or `utter-cpu` folder (any PC)
   from a release, and put it anywhere (e.g. `C:\Tools\utter`).
2. Run **`utterd.exe`** — the daemon appears in the system tray. First run writes a
   default config and downloads model weights from Hugging Face (~3 GB for the default
   `large-v3`; see the model table below), showing progress in the log.
3. **SmartScreen note:** the exe is not code-signed (v1), so Windows may show
   "Windows protected your PC" — click **More info → Run anyway**.

`utter.exe` in the same folder is the command-line interface (`utter.exe dashboard`,
`utter.exe dictate`, `utter.exe --help`).

### From source

```powershell
git clone https://github.com/afhaque/Utter.git
cd Utter
python -m venv .venv
.venv\Scripts\pip install -e .
.venv\Scripts\utter start
```

Python 3.11+. The pinned `ctranslate2`/CUDA wheel versions in `pyproject.toml` are what
make modern (Blackwell) GPUs work — don't upgrade them casually.

## Using it

| Action | How |
|---|---|
| Start dictation | press **Ctrl+Alt+Space** (configurable) — an overlay animates while recording |
| Finish + paste | press the hotkey again — text lands in the focused app |
| Pause / resume | tray icon → *Pause dictation* |
| Dashboard & settings | tray icon → *Open Dashboard*, or `utter dashboard` |
| One-off headless dictation | `utter dictate` (add `--device cpu` or `--model small` to experiment) |

The hotkey is a **toggle**: tap to start, tap to stop. Accidental double-taps are
discarded (too-short clips are never transcribed), and a voice-activity filter stops
Whisper from hallucinating text out of silence.

Config lives at `%APPDATA%\Utter\config.toml`. Edit it in the TUI (*Dashboard* →
tabs), or by hand — the running daemon hot-reloads changes within ~1 s (model changes
need a daemon restart). Hotkey syntax: `ctrl+alt+space`, `ctrl+shift+d`, `f9`, … — one
non-modifier key, and bare letters are rejected on purpose (the hotkey is swallowed
system-wide).

## Picking a model

| Model | Download | Typical VRAM | Feel on a 16 GB GPU | Use when |
|---|---|---|---|---|
| `tiny` / `base` | 75–145 MB | <1 GB | instant | quick notes, weak hardware |
| `small` | ~460 MB | ~1 GB | instant | fast casual dictation |
| `medium` | ~1.5 GB | ~2.5 GB | sub-second | balanced |
| `large-v3` (default) | ~3 GB | ~4.5 GB | ~0.5 s per 5 s clip (measured) | maximum accuracy |

CPU-only? Use `small` or `medium` with `device = "cpu"` — `large-v3` works but takes
several seconds per utterance.

## The optional LLM formatting pass

Enable `[formatting.llm]` to post-process transcripts through a local Ollama model
(default `qwen3.6`) with your own instruction, e.g. *"Format as terse Slack messages,
no capital letters."* If Ollama is down or slow, Utter silently falls back to the
rule-based formatter — a paste is never blocked.

## Troubleshooting

- **`Library cublas64_12.dll is not found` (source installs):** the NVIDIA wheels
  aren't visible. `pip install nvidia-cublas-cu12 nvidia-cudnn-cu12` into the same
  environment. Utter registers their DLL folders itself (`src/utter/gpu.py`); this is
  the #1 CUDA setup issue (BUILD_PLAN.md §12.1).
- **`no kernel image is available for execution on the device`:** your ctranslate2
  build predates your GPU architecture — reinstall with the exact pins in
  `pyproject.toml`.
- **Transcribes but nothing pastes:** some apps swallow synthetic Ctrl+V. Set
  `[injection] method = "sendinput"` to type characters directly.
- **Hotkey does nothing:** another app may own that chord — pick a different combo in
  the Hotkey tab. Windows blocks `RegisterHotKey` duplicates; the daemon log
  (`%APPDATA%\Utter\logs\utter.log`) will say so.
- **No microphone found:** run `utter devices` and set `[audio] input_device` to one of
  the listed names/indexes.
- **First run looks hung:** it's probably downloading gigabytes of weights — watch the
  log file. Weights cache under `%USERPROFILE%\.cache\huggingface`.
- **Dashboard says "stale — daemon may have crashed":** the daemon stopped without
  cleanup; restart `utterd.exe` and check the log.

## Building the packaged app

```powershell
.venv\Scripts\pip install -e ".[dev]"
.venv\Scripts\pyinstaller packaging\utter.spec --noconfirm          # GPU bundle -> dist\utter
$env:UTTER_CPU_ONLY = "1"
.venv\Scripts\pyinstaller packaging\utter.spec --noconfirm          # CPU bundle -> dist\utter-cpu
```

The GPU bundle is large (≈2.5 GB) because it ships the CUDA math libraries; model
weights are **not** bundled and download on first run. `packaging/installer.iss` is an
optional Inno Setup script for a Start-menu installer.

## Project docs

- **[CONTEXT.md](./CONTEXT.md)** — product concept and spec
- **[BUILD_PLAN.md](./BUILD_PLAN.md)** — the implementation roadmap this app was built from
- **[CONTRIBUTING.md](./CONTRIBUTING.md)** — dev setup, layout, rules
- **[docs/adr/0001-concurrency-model.md](./docs/adr/0001-concurrency-model.md)** — process/threading model

## License

[MIT](./LICENSE)
