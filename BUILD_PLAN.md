# Utter — Build Plan

> This document is the implementation roadmap for Utter. It is written to be executed by a
> fresh Claude (or human) engineering thread with **no prior context** beyond this repo. Read
> [CONTEXT.md](./CONTEXT.md) first for the product concept; this file covers *how* to build it.
>
> **Status:** planning artifact. No application code exists yet. Phase 0 is the starting line.

---

## 0. TL;DR for the implementing thread

- **Language:** Python 3.11+ (single language, end to end). Rationale in §2.
- **Transcription:** `faster-whisper` (CTranslate2) on CUDA, CPU fallback. Already proven working
  on the target machine (RTX 5060 Ti, 16GB) this session.
- **Shell:** pure-Python — `pynput` (hotkey + paste), `sounddevice` (audio), `pystray` (tray),
  Tkinter (recording overlay), `Textual` (terminal dashboard + config), `Typer` (CLI entry).
- **Optional formatting brain:** the user's local LLM via **Ollama** (`http://localhost:11434`),
  default model `qwen3.6` — already pulled on the target machine.
- **Packaging:** PyInstaller **onedir** (not onefile — see §11), NVIDIA DLLs bundled explicitly,
  Whisper weights downloaded on first run (never bundled).
- **Build the pipeline headless first (Phase 1), add GUI later.** Do not start with the overlay.
- ⚠️ **Read §12 (Gotchas) before writing any transcription code** — the cuBLAS/cuDNN DLL trap
  will cost you an hour otherwise.

---

## 1. Irreducible requirements (what "done" must satisfy)

1. Press a global hotkey anywhere in Windows → recording starts, with a visible animated overlay.
2. Press the hotkey again → recording stops, audio is transcribed **locally**, text is formatted
   per the user's preferences, and pasted into whatever window has focus.
3. Runs as a background process (system tray), minimal idle footprint.
4. A **terminal** interface lets the user: pick the transcription model, pick the device, set
   text-formatting preferences (punctuation, capitalization, custom instructions), set the
   hotkey, and see a dashboard of recent activity/status.
5. Nothing leaves the machine. No account, no cloud, no telemetry.
6. Ships as an installable Windows executable; source is open.

---

## 2. Stack decision (and why — derived, not defaulted)

The only computationally hard step (local Whisper transcription) is best served by
`faster-whisper`/CTranslate2, which is **Python-first**. Once Python is mandatory for the hard
part, introducing a second language for the shell (e.g. a Rust/C# tray app driving a Python
transcription sidecar) buys nothing a v1 needs and costs an IPC boundary, a second toolchain,
and harder packaging. Every remaining component has a mature pure-Python, Windows-capable
library. Therefore: **single-language Python.**

| Concern | Choice | Why this and not the obvious alternative |
|---|---|---|
| Language | **Python 3.11+** | STT ecosystem is Python; agent-buildable; one toolchain. Not Rust/C#: no second-language tax for v1. |
| STT engine | **faster-whisper** (CTranslate2 backend) | 4× faster than reference `openai-whisper`, same accuracy; proven working here. Not `whisper.cpp`: Python binding friction; not cloud: violates req #5. |
| Audio capture | **sounddevice** (PortAudio) | Simple numpy-buffer capture at 16 kHz mono (Whisper-native). Not `pyaudio`: rougher API, build pain on Windows. |
| Global hotkey | **pynput** primary; **Win32 `RegisterHotKey`** fallback | `pynput` is pip-clean and usually needs no admin. Not `keyboard` lib: frequently requires admin on Windows. |
| Text delivery | **pyperclip** (set clipboard) + **pynput** (send Ctrl+V), with clipboard save/restore | Universal across apps. Direct `SendInput` Unicode injection is the fallback for paste-hostile apps (§7). |
| Recording overlay | **Tkinter** frameless always-on-top window | Stdlib, zero extra dep, enough for an animated mic-level bar. PySide6/Qt is an optional polish upgrade, not a v1 requirement. |
| System tray / background | **pystray** + Pillow | Pure Python tray icon + menu. |
| Terminal UI (config + dashboard) | **Textual** | The user asked for a *terminal* interface; a TUI is both what's wanted and less work than a GUI. Tabs for Dashboard/Model/Formatting/Hotkey/Logs. |
| CLI entry / commands | **Typer** | `utter start`, `utter config`, `utter dashboard`, `utter model ls`, etc. |
| Optional LLM formatting | **Ollama HTTP API** (`/api/generate`), default `qwen3.6` | Reuses the model the user already runs; no new runtime. Rule-based tier works with Ollama absent. |
| Config format | **TOML** via `tomllib` (read) + `tomli-w` (write) | Human-editable, stdlib-parseable. |
| Packaging | **PyInstaller** (onedir) | Produces a runnable Windows folder/exe; onedir handles the large NVIDIA DLLs better than onefile (§11). |
| Lint/format/test | **ruff** + **pytest** | Fast, standard. |

---

## 3. High-level architecture

```
                        ┌──────────────────────────────────────────┐
                        │              Utter (background)            │
                        │                                            │
  Global hotkey  ──────▶│  HotkeyController ──▶ RecorderService      │
                        │        │                    │  (audio buf) │
                        │        │                    ▼              │
                        │        │            TranscriptionService   │
                        │        │             (faster-whisper/CUDA) │
                        │        │                    │  (raw text)  │
                        │        │                    ▼              │
                        │   OverlayWindow       FormattingService    │
                        │   (Tkinter, animated)  rules → optional     │
                        │                        Ollama LLM pass      │
                        │                            │  (final text) │
                        │                            ▼              │
                        │                       Injector ──▶ focused app (paste)
                        │                            │              │
                        │                            ▼              │
                        │                       HistoryStore (sqlite)│
                        │                                            │
                        │   TrayIcon (pystray)   ConfigStore (TOML)  │
                        └──────────────────────────────────────────┘
                                        ▲
                                        │ reads/writes
                        ┌───────────────┴────────────────┐
                        │   Terminal UI (Textual)  +  CLI  │
                        │   Dashboard · Model · Formatting │
                        │   Hotkey · Logs                  │
                        └──────────────────────────────────┘
```

**Design principles**
- **Core is headless and importable.** The record→transcribe→format→inject pipeline is a library
  with no GUI dependency. The overlay, tray, and TUI are thin layers on top. This is what makes
  Phase 1 testable before any UI exists.
- **Single source of truth for state.** `ConfigStore` (TOML) + `HistoryStore` (sqlite). The TUI
  and the background process both read/write these; no in-memory-only settings.
- **Services are swappable.** `TranscriptionService` is an interface; `faster-whisper` is the
  first implementation. A future `whisper.cpp` or cloud-optional backend slots in behind it. Same
  for `FormattingService`.

---

## 4. Component contracts (interfaces the thread should implement)

```
RecorderService
  start() -> None                 # begin capturing mic to an internal buffer
  stop()  -> AudioClip            # stop, return 16kHz mono float32 numpy array + duration

TranscriptionService (interface)
  load(model, device, compute_type) -> None
  transcribe(clip: AudioClip) -> Transcript   # {text, segments, language, latency_ms}
  # first impl: FasterWhisperService

FormattingService
  format(text: str, prefs: FormattingPrefs) -> str
  # tier 1: rule-based (deterministic). tier 2 (optional): Ollama LLM pass.

Injector
  paste(text: str) -> None        # clipboard save → set → Ctrl+V → restore

HotkeyController
  register(combo: str, on_toggle: Callable) -> None
  unregister() -> None

ConfigStore
  load() -> Config ; save(cfg: Config) -> None    # TOML at %APPDATA%\Utter\config.toml

HistoryStore
  add(entry) ; recent(n) -> list  # sqlite at %APPDATA%\Utter\history.db
```

---

## 5. Config schema (`%APPDATA%\Utter\config.toml`)

```toml
[general]
hotkey = "ctrl+alt+space"          # toggle record start/stop
launch_on_startup = false
overlay = true

[model]
engine = "faster-whisper"
name = "large-v3"                  # tiny|base|small|medium|large-v3 (or a local path)
device = "cuda"                    # cuda|cpu|auto
compute_type = "float16"           # float16|int8_float16|int8
beam_size = 5
language = "auto"                  # or an ISO code like "en"

[formatting]
punctuation = true                 # keep Whisper's punctuation; false = strip
capitalization = "sentence"        # sentence|lower|upper|as-is
strip_filler_words = false         # remove "um", "uh", ...
trailing_space = true              # append a space so consecutive dictations don't collide
custom_replacements = []           # [["gonna","going to"], ...]

[formatting.llm]
enabled = false                    # optional LLM cleanup pass
provider = "ollama"
base_url = "http://localhost:11434"
model = "qwen3.6"
# freeform instruction injected into the LLM prompt — this is the user's "context on how
# they want text formatted", e.g. "Format as terse Slack messages, no capital letters."
instruction = ""

[privacy]
save_history = true                # local sqlite only; never transmitted
```

---

## 6. Formatting pipeline (two tiers)

**Tier 1 — rule-based (always on, deterministic, ~0 ms).** Applies the `[formatting]` prefs:
punctuation keep/strip, capitalization mode, filler-word removal, custom replacements, trailing
space. This alone matches most of what a cloud dictation tool does post-transcription.

**Tier 2 — optional LLM pass (`[formatting.llm].enabled = true`).** POST the tier-1 text to
Ollama `/api/generate` with a prompt built from `instruction`, e.g.:

```
System: You reformat dictated text. Apply ONLY formatting/wording changes, never add content.
User instruction: {instruction}
Text: {tier1_text}
Return only the reformatted text.
```

Keep a hard timeout (e.g. 3 s) and fall back to tier-1 text on any error/timeout — the LLM pass
must never block a paste. This is where "add context on how they want the text formatted" lives.

---

## 7. Text delivery details (the fiddly part)

Default path: save current clipboard → set clipboard to final text → send `Ctrl+V` via `pynput`
→ restore original clipboard after a short delay. **Gotchas to handle:**
- Restore the user's prior clipboard contents (don't clobber it).
- Some apps swallow synthetic `Ctrl+V`. Provide a config toggle for a **`SendInput` Unicode
  injection** fallback (Win32 `KEYEVENTF_UNICODE`) that types the characters directly.
- Add a small configurable delay before paste so the target window regains focus after the
  overlay closes.

---

## 8. UX flows

**Recording flow:** hotkey ↓ → overlay appears bottom-center, animating a live mic-level bar →
user speaks → hotkey ↓ again → overlay switches to a "transcribing…" spinner → text pasted →
overlay fades out. Total post-speech latency target: **< 1.5 s** for `small`, **< 3 s** for
`large-v3` on a 16GB GPU (see §10).

**First-run flow:** on first `utter start`, if no config exists → run a short setup wizard in the
terminal (pick model size with a download-size hint, pick device, set hotkey), write config,
trigger the first model download with a progress indicator, then go to tray.

**Tray menu:** Start/Pause dictation · Open Dashboard (launches the Textual UI) · Settings ·
Quit.

**Terminal UI (Textual) tabs:**
- **Dashboard** — active model, device, GPU/VRAM status, last N transcriptions with latency.
- **Model** — choose engine/size/device/compute_type; shows download state; "test transcription".
- **Formatting** — toggle punctuation/capitalization/filler; edit custom replacements; enable and
  write the LLM `instruction`.
- **Hotkey** — capture/set the toggle combo.
- **Logs** — tail the log file.

---

## 9. Proposed repository / package structure

```
Utter/
├─ README.md
├─ CONTEXT.md
├─ BUILD_PLAN.md          # this file
├─ LICENSE
├─ pyproject.toml         # deps, ruff, pytest, entry points
├─ logo.jpg
├─ src/utter/
│  ├─ __init__.py
│  ├─ __main__.py         # `python -m utter`
│  ├─ cli.py              # Typer app: start/config/dashboard/model/...
│  ├─ core/
│  │  ├─ recorder.py      # RecorderService (sounddevice)
│  │  ├─ transcription.py # TranscriptionService iface + FasterWhisperService
│  │  ├─ formatting.py    # rule tier + Ollama tier
│  │  ├─ injector.py      # clipboard/paste/SendInput
│  │  ├─ pipeline.py      # orchestrates record→transcribe→format→inject
│  │  ├─ config.py        # ConfigStore (TOML)
│  │  └─ history.py       # HistoryStore (sqlite)
│  ├─ ui/
│  │  ├─ overlay.py       # Tkinter frameless animated overlay
│  │  ├─ tray.py          # pystray icon + menu
│  │  └─ tui.py           # Textual dashboard + settings
│  ├─ hotkey.py           # HotkeyController (pynput / Win32 fallback)
│  └─ gpu.py              # cuBLAS/cuDNN DLL PATH shim (see §12), device detection
├─ tests/
│  ├─ fixtures/hello.wav
│  ├─ test_formatting.py
│  ├─ test_config.py
│  └─ test_pipeline.py
├─ packaging/
│  ├─ utter.spec          # PyInstaller onedir spec
│  └─ installer.iss       # optional Inno Setup script
└─ .github/workflows/ci.yml
```

---

## 10. Performance / latency targets

| Model | VRAM (approx) | Target post-speech latency (16GB GPU) | Use |
|---|---|---|---|
| `small` | ~1–2 GB | < 1 s | fast, casual dictation |
| `medium` | ~2–3 GB | ~1–2 s | balanced |
| `large-v3` | ~3 GB | ~2–3 s | max accuracy (default recommendation) |

Keep the model **loaded in memory** in the background process — pay the multi-second load cost
once at startup, never per-dictation. Use `beam_size` and model size as the primary speed knobs.
(This session's cold test measured 3.3 s load + 9.3 s for a 10 s clip using `large-v3`,
`beam_size=5`, model loaded cold — representative of the *wrong* way; the persistent-load hot path
is far faster.)

---

## 11. Packaging

- **PyInstaller onedir** (`--onedir`, not `--onefile`). Onefile unpacks to a temp dir every launch
  — slow and fragile with the large NVIDIA CUDA DLLs. Onedir ships a folder that launches fast.
- Explicitly collect the CTranslate2 + `nvidia-cublas-cu12` + `nvidia-cudnn-cu12` binaries into
  the bundle (hidden imports / `--collect-binaries`); verify `cublas64_12.dll` and `cudnn*64_9.dll`
  land next to the exe.
- **Do NOT bundle Whisper model weights.** They download from Hugging Face to the user's cache on
  first run. Bundling would bloat the installer by gigabytes and break model switching.
- Optional: wrap the onedir output in an **Inno Setup** installer (`packaging/installer.iss`) for a
  Start-menu shortcut and optional "launch on startup".
- Ship a CPU-only build variant too (smaller, no NVIDIA DLLs) for machines without CUDA.

---

## 12. Gotchas (read before coding — learned the hard way this session)

1. **cuBLAS/cuDNN DLLs must be on PATH before importing/using faster-whisper on CUDA.** The pip
   `ctranslate2` wheel does **not** bundle them. Symptom: `RuntimeError: Library cublas64_12.dll
   is not found or cannot be loaded`. **Fix that works on Windows:** `pip install nvidia-cublas-cu12
   nvidia-cudnn-cu12`, then at startup prepend their `bin` dirs to `os.environ["PATH"]` (the
   `nvidia/cublas/bin` and `nvidia/cudnn/bin` folders under site-packages). Note: `os.add_dll_directory()`
   alone did **not** reliably work for this loader on the target machine — mutating `PATH` did.
   Put this shim in `gpu.py` and call it before any transcription import. This is non-negotiable
   and the #1 time-sink if missed.
2. **Whisper wants 16 kHz mono float32.** Capture at 16 kHz mono directly, or resample before
   handing the buffer to faster-whisper.
3. **`keyboard` lib often needs admin on Windows** — prefer `pynput`; keep Win32 `RegisterHotKey`
   as the robust fallback.
4. **Synthetic paste isn't universal** — implement clipboard restore and the `SendInput` Unicode
   fallback (§7).
5. **HF symlink warning on Windows** is benign (falls back to copies) — optionally enable Windows
   Developer Mode or set `HF_HUB_DISABLE_SYMLINKS_WARNING=1` to silence it.
6. **First run downloads gigabytes.** Make it explicit with progress; never silently hang.
7. **Overlay must be click-through / non-focus-stealing** or it will steal focus from the target
   app and break paste — set the Tkinter window to not take focus, and restore focus before paste.

---

## 13. Phased milestones

Each phase is a shippable increment with its own acceptance criteria. **Do them in order.**

### Phase 0 — Scaffolding
- **Deliverables:** `pyproject.toml` (deps, ruff, pytest, `utter` entry point), package skeleton
  from §9, `config.py` (TOML load/save with the §5 schema + defaults), `gpu.py` DLL shim + device
  detection, logging setup, `LICENSE` (recommend MIT), CI stub.
- **Key libs:** Typer, tomllib/tomli-w, ruff, pytest.
- **Acceptance:** `python -m utter --help` runs; `utter config` writes a default `config.toml`;
  `ruff check` and `pytest` pass on an empty test suite; `gpu.py` correctly reports cuda vs cpu.

### Phase 1 — Headless transcription pipeline (the core, proves everything)
- **Deliverables:** `recorder.py`, `transcription.py` (`FasterWhisperService`), `pipeline.py` wired
  as `utter dictate --once` = record N seconds (or until Enter) → transcribe → print text. No GUI.
- **Key libs:** sounddevice, faster-whisper, numpy.
- **Acceptance:** `utter dictate --once` transcribes real speech correctly on GPU (and on CPU with
  `--device cpu`); a fixture-WAV integration test passes; model stays loaded across repeated calls
  in one process (no reload per call).

### Phase 2 — Hotkey + paste (makes it feel like dictation)
- **Deliverables:** `hotkey.py`, `injector.py`; a foreground `utter start` that toggles
  record/transcribe/paste on the configured hotkey and injects into the focused window.
- **Key libs:** pynput, pyperclip.
- **Acceptance:** with a text editor focused, hotkey→speak→hotkey pastes correct text; the user's
  prior clipboard is restored; works in ≥3 different apps (editor, browser field, chat box).

### Phase 3 — Recording overlay
- **Deliverables:** `ui/overlay.py` — frameless, always-on-top, non-focus-stealing window with a
  live mic-level animation while recording and a "transcribing…" state after.
- **Key libs:** Tkinter (or PySide6 if upgrading polish).
- **Acceptance:** overlay appears on hotkey, animates to real mic input, switches to transcribing
  state, fades out after paste, and does **not** steal focus (paste still lands correctly).

### Phase 4 — System tray / background
- **Deliverables:** `ui/tray.py`; `utter start` runs in the tray (no console window in the packaged
  build), menu = Start/Pause · Dashboard · Settings · Quit; optional launch-on-startup.
- **Key libs:** pystray, Pillow.
- **Acceptance:** app lives in the tray, dictation works while backgrounded, menu actions work,
  Quit exits cleanly (unregisters hotkey, releases mic).

### Phase 5 — Formatting engine
- **Deliverables:** `formatting.py` — rule tier (punctuation/capitalization/filler/replacements/
  trailing space) + optional Ollama LLM tier with timeout + graceful fallback; `history.py` (sqlite).
- **Key libs:** httpx/requests (Ollama), sqlite3.
- **Acceptance:** each `[formatting]` pref demonstrably changes pasted output; with LLM enabled and
  Ollama up, the `instruction` reshapes text; with Ollama down, it silently falls back to tier-1;
  history rows are written locally.

### Phase 6 — Terminal UI (config + dashboard)
- **Deliverables:** `ui/tui.py` — Textual app with the §8 tabs (Dashboard/Model/Formatting/Hotkey/
  Logs); `utter dashboard` launches it; first-run setup wizard.
- **Key libs:** Textual.
- **Acceptance:** every setting is editable in the TUI and persists to `config.toml`; Dashboard
  shows live model/device/VRAM + recent transcriptions; "test transcription" works from the Model
  tab; changing the hotkey in the TUI takes effect in the running app.

### Phase 7 — Packaging & release
- **Deliverables:** `packaging/utter.spec` (onedir, NVIDIA DLLs collected), optional
  `installer.iss`, a CPU-only variant, README install/usage docs.
- **Key libs:** PyInstaller, (Inno Setup).
- **Acceptance:** the built exe runs on a clean Windows machine **without** a Python install;
  GPU build transcribes on CUDA; CPU build transcribes without NVIDIA DLLs; first-run model
  download works from the packaged app.

### Phase 8 — Hardening & docs
- **Deliverables:** error handling for no-mic/no-GPU/model-download-failure; unit tests for
  formatting + config; README with GIF, hotkey docs, model-size guidance, troubleshooting (incl.
  the §12 DLL note); CONTRIBUTING.md.
- **Acceptance:** graceful, user-legible failure on each error path; `pytest` green; README lets a
  new user install and dictate without asking questions.

---

## 14. Testing strategy

- **Unit (pytest):** formatting rules (table-driven: input → prefs → expected output), config
  round-trip (write→read→equal), history store CRUD, gpu.py device selection logic.
- **Integration:** `test_pipeline.py` runs `FasterWhisperService` on a committed fixture WAV
  (`tests/fixtures/hello.wav`, generated via Windows TTS as we did this session) and asserts the
  transcript contains expected tokens. Mark it to auto-skip if no model/GPU is available in CI.
- **Manual checklist (per release):** hotkey in 3+ apps, clipboard restore, overlay focus behavior,
  tray actions, first-run wizard, packaged-exe on a clean VM.

## 15. CI (`.github/workflows/ci.yml`)

- **lint:** `ruff check` + `ruff format --check`.
- **test:** `pytest` on `windows-latest` (skip GPU-only integration tests; run CPU int8 path where
  feasible).
- **build (on tag):** PyInstaller onedir on `windows-latest`, upload the exe folder as a release
  artifact. GPU DLLs are pip-installed in the build job so they're collected into the bundle.

## 16. Privacy & security

Utter is fully local: audio is captured, transcribed, formatted, and pasted entirely on-device.
No network calls except (a) one-time model weight downloads from Hugging Face and (b) localhost
Ollama calls if the optional LLM formatting pass is enabled. No account, no telemetry, no cloud.
History is a local sqlite file the user can disable or delete. State this plainly in the README.

## 17. Open questions / deferred decisions

- **Overlay framework:** stdlib Tkinter (chosen for v1, zero-dep) vs PySide6 (nicer animation,
  heavier bundle). Revisit only if Tkinter animation feels cheap in Phase 3.
- **Push-to-talk vs toggle:** plan assumes press-to-toggle. A hold-to-talk mode is a possible
  config option later.
- **Streaming/partial transcription:** out of scope for v1 (record-then-transcribe matches the
  target UX and is simpler). Revisit only if latency on long dictations feels bad.
- **Non-CUDA GPUs (AMD):** CPU fallback covers correctness; a Vulkan/DirectML path is a later
  enhancement, not v1.
- **License:** recommend MIT; confirm with the owner before Phase 0 lands `LICENSE`.
- **Model manager depth:** v1 exposes Whisper sizes; a richer "install/remove models" UI can come
  later.

## 18. Recommended first PR

**PR #1 = Phase 0 + Phase 1** — scaffolding plus the headless `utter dictate --once` pipeline.
This is the highest-leverage starting point: it stands up the package, proves the core
record→transcribe path end-to-end (the only technically risky part), bakes in the §12 DLL shim
from the start, and gives every later phase something real to build on. Everything after it is
additive UI/UX around a working core.

Concretely, PR #1 delivers: `pyproject.toml`, the `src/utter` skeleton, `config.py`, `gpu.py`
(with the DLL shim), `recorder.py`, `transcription.py`, `pipeline.py`, `cli.py` (`--help`,
`config`, `dictate --once`), one integration test on a fixture WAV, ruff+pytest CI. Acceptance =
`utter dictate --once` transcribes live speech on the target machine.
