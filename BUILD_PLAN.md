# Utter — Build Plan

> This document is the implementation roadmap for Utter. It is written to be executed by a
> fresh Claude (or human) engineering thread with **no prior context** beyond this repo. Read
> [CONTEXT.md](./CONTEXT.md) first for the product concept; this file covers *how* to build it.
>
> **Status:** executed — all phases (0–8) are implemented in this repo. Kept as the
> historical roadmap; where implementation deviated (e.g. Win32 RegisterHotKey instead of
> pynput GlobalHotKeys), the code and README are authoritative.

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

### 2.1 Pinned versions (these exact versions were verified working this session)

The RTX 5060 Ti is **Blackwell (sm_120)**. This requires a CTranslate2 built against CUDA 12.8 /
cuDNN 9 — an older CTranslate2 will load the DLLs fine but then throw `no kernel image is available
for execution on the device` on sm_120. Do **not** `pip install` latest-of-everything blindly. Pin:

```
faster-whisper == 1.2.1
ctranslate2    == 4.8.1          # CUDA 12.8 / cuDNN 9 build — required for Blackwell sm_120
nvidia-cublas-cu12 == 12.9.2.10
nvidia-cudnn-cu12  == 9.24.0.43
```

(These are the versions that transcribed correctly on the target machine this session. Bump only
deliberately, and re-test on the Blackwell GPU when you do.)

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

### 3.1 Concurrency & process model (decide this in Phase 0 — do NOT wing it)

This is the single most likely integration wall. Multiple things want the main thread on Windows:
pystray runs its own Win32 message loop, Tkinter requires all GUI calls on the thread that created
the root and wants its own `mainloop()`, faster-whisper blocks, and pynput/sounddevice run their
own callback threads. **You cannot naively call `tray.run()` and `root.mainloop()` in one process.**

Mandated model for v1:
- **Two processes, not one.**
  - **`utterd` (the daemon):** owns the hotkey listener, recorder, transcription, formatting,
    injector, overlay, and tray. This is what `utter start` launches (windowless in the packaged
    build).
  - **`utter dashboard` (the TUI):** a **separate** console process (Textual needs a real tty; a
    windowless daemon has none). Launched on demand from the tray menu or CLI.
- **Inside the daemon:**
  - **pystray owns the main thread** (`icon.run()` on main). 
  - **The Tkinter overlay runs on its own dedicated thread** with its own root + `mainloop()`;
    all overlay updates from other threads are marshaled via `root.after(0, ...)`. (Tkinter tolerates
    a non-main thread as long as *one* thread exclusively owns the root and everyone else posts to it.)
  - **Hotkey callback offloads work:** the pynput callback must return fast — it enqueues a
    start/stop event; a dedicated **worker thread** runs the blocking record→transcribe→format→inject
    chain so the listener and tray never freeze.
- **Daemon ↔ TUI communication (no live in-memory sharing across processes):**
  - Settings: the TUI writes `config.toml`; the daemon **watches the file** (mtime poll or
    `watchdog`) and hot-reloads (re-registers the hotkey, reloads prefs) on change.
  - Status/history: the daemon writes live status (active model, device, VRAM, last-N transcripts)
    to `history.db` / a small `status.json`; the TUI Dashboard **polls** it. No socket needed for v1.
- **Single-instance guard:** the daemon must refuse to start twice (a named mutex / lockfile in
  `%APPDATA%\Utter`) — two daemons would both grab the global hotkey and fight over the mic.

If the no-focus-steal overlay (see §7/§12) proves too fragile in Tkinter, **PySide6 is the
sanctioned upgrade** — it has first-class frameless/no-activate window support and a cleaner
threading story via its own event loop. Treat that as a Phase-3 escape hatch, not a v1 default.

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

[audio]
input_device = "default"           # name/index of mic; multi-mic machines must be able to pick
sample_rate = 16000                # Whisper-native; capture mono float32

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
model = "qwen3.6"                  # verified pulled locally this session (ollama list → qwen3.6:latest, 23GB)
disable_thinking = true            # qwen3.6 is a hybrid-THINKING model — see §6, must suppress <think>
timeout_seconds = 8                # generous: thinking models are slower; fall back to tier-1 on timeout
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

**Critical — qwen3.6 is a hybrid *thinking* model.** By default it emits a `<think>…</think>`
reasoning block, which would corrupt the pasted text and blow the timeout while it "thinks". You
MUST suppress it: send `"think": false` in the Ollama request options (and/or prepend `/no_think`),
AND defensively strip any residual `<think>…</think>` block from the response before use. Use a
generous timeout (~8 s, not 3 s — thinking-class models are slower even with thinking off) and fall
back to tier-1 text on any error/timeout — the LLM pass must never block a paste. This is where
"add context on how they want the text formatted" lives.

> Note for the builder: `qwen3.6` is a real, locally-available Ollama tag on the target machine
> (confirmed this session via `ollama list`). If you're working from older training data that says
> it doesn't exist, trust the live `ollama list` output, not your prior. Any recent local model
> works here — it's an optional, swappable tier.

---

## 7. Text delivery details (the fiddly part)

Default path: save current clipboard → set clipboard to final text → send `Ctrl+V` via `pynput`
→ restore original clipboard after a short delay. **Gotchas to handle:**
- Restore the user's prior clipboard contents (don't clobber it). Note: `pyperclip` is **text-only**
  — it will destroy non-text clipboard contents (a copied image/file) on restore. If that matters,
  use `win32clipboard` to save/restore all formats; otherwise document the limitation.
- **Modifier bleed:** the toggle hotkey is `ctrl+alt+space`; if `alt` is still physically held when
  you send `Ctrl+V`, the target receives `Ctrl+Alt+V`. Before injecting, wait for/force-release the
  modifier keys (poll key state, or send explicit key-up) so the paste is a clean `Ctrl+V`.
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
trigger the first model download with a progress indicator, then go to tray. Note: surfacing HF
download progress into the TUI is non-trivial — `huggingface_hub` drives `tqdm`; either hook its
progress callback into a Textual progress bar or shell out and parse, but don't leave the first-run
looking hung during a multi-GB pull.

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

| Model | VRAM (rough, incl. runtime) | Provisional target post-speech latency (16GB GPU) | Use |
|---|---|---|---|
| `small` | ~0.5–1 GB | sub-second (once warm) | fast, casual dictation |
| `medium` | ~1.5–2.5 GB | ~1–2 s | balanced |
| `large-v3` | ~4–5 GB (weights ~3 GB + beam-search buffers) | ~2–3 s | max accuracy (default recommendation) |

These targets are **provisional and MUST be re-measured** — do not treat them as verified. Two rules:
- **Keep the model loaded in memory** in the daemon — pay the multi-second load cost once at
  startup, never per-dictation.
- **Do a warmup inference at startup** (transcribe a fraction of a second of silence right after
  loading). ⚠️ Important correction to earlier session data: a cold first-call measured **3.3 s
  load + 9.3 s to transcribe a 10 s clip** on `large-v3`/`beam_size=5`. Keeping the model resident
  removes the **3.3 s load, NOT the 9.3 s compute** — transcription time is independent of load. The
  9.3 s was almost certainly first-call CUDA/cuDNN kernel JIT + lazy-load warmup, which is exactly
  what the startup warmup pass amortizes. **Phase 1 must measure the *warm* per-clip compute time and
  the targets above must be confirmed or corrected against it** before the §8 UX latency promise is
  made. If warm `large-v3` compute is still ~1× realtime, drop the default to `small`/`medium`.
- Primary speed knobs: model size, then `beam_size`.

---

## 11. Packaging

- **PyInstaller onedir** (`--onedir`, not `--onefile`). Onefile unpacks to a temp dir every launch
  — slow and fragile with the large NVIDIA CUDA DLLs. Onedir ships a folder that launches fast.
- **PyInstaller ≥6 puts bundled binaries in an `_internal/` subfolder, not next to the exe.** The
  `gpu.py` DLL shim MUST be layout-aware (see §12.1): in a frozen build it points the CUDA DLL search
  at `_internal/` (via `sys._MEIPASS`), in dev it points at site-packages `nvidia/*/bin`. Getting
  this wrong means CUDA loads in dev and silently fails on the packaged exe — bridge Phase 1's shim
  to Phase 7 explicitly or the "runs on a clean machine" acceptance fails.
- Explicitly collect the CTranslate2 + `nvidia-cublas-cu12` + `nvidia-cudnn-cu12` binaries into
  the bundle (`--collect-binaries` / hidden imports). Verify **all** required DLLs land, not just
  the headline one: `cublas64_12.dll` **and** `cublasLt64_12.dll`, plus the `cudnn*64_9.dll` set
  (note `cudnn_engines_precompiled64_9.dll` is very large).
- **Reality check on size:** the CUDA + cuDNN DLL set makes the onedir bundle roughly **2–3 GB**.
  That's before model weights. Plan the installer/download UX around that — it is not a small app.
- **Do NOT bundle Whisper model weights.** They download from Hugging Face to the user's cache on
  first run. Bundling would bloat the installer by gigabytes and break model switching.
- Optional: wrap the onedir output in an **Inno Setup** installer (`packaging/installer.iss`) for a
  Start-menu shortcut and optional "launch on startup".
- **Code signing:** an unsigned PyInstaller exe will trip Windows SmartScreen / AV on first run —
  which will fail a naive "runs on a clean machine" test. Either sign the binary or explicitly
  document the SmartScreen "More info → Run anyway" step for v1.
- Ship a CPU-only build variant too (much smaller, no NVIDIA DLLs) for machines without CUDA.

---

## 12. Gotchas (read before coding — learned the hard way this session)

1. **cuBLAS/cuDNN DLLs must be resolvable before faster-whisper touches CUDA — this is the #1
   time-sink.** The pip `ctranslate2` wheel does **not** bundle them. Symptom: `RuntimeError:
   Library cublas64_12.dll is not found or cannot be loaded`. Install them as wheels (`pip install
   nvidia-cublas-cu12 nvidia-cudnn-cu12`) and make `gpu.py` register their location **before any
   transcription import**, in this order of robustness:
   1. **Most robust — copy the DLLs next to the CTranslate2 `.pyd`** (or into the frozen bundle dir)
      so the OS resolves them by the default same-directory search. This is the recommended primary,
      and it's what the packaged build needs anyway.
   2. **`os.add_dll_directory(<dir>)`** — the officially documented Windows mechanism since Python 3.8
      (dependent-DLL resolution ignores `PATH` by default under secure DLL loading).
   3. **Prepend the DLL dirs to `os.environ["PATH"]`** — this is what *actually* worked on the target
      machine this session when `add_dll_directory` alone did not (loader/version-specific), so keep
      it as a belt-and-suspenders fallback. Do all three; they don't conflict.
   - **`gpu.py` must be layout-aware:** in dev, the dirs are `site-packages/nvidia/cublas/bin` and
     `.../nvidia/cudnn/bin`; in a PyInstaller onedir build they're under `sys._MEIPASS`/`_internal`
     (see §11). Detect `sys.frozen` and branch.
   - **Register the full set:** `cublas64_12.dll` **and** `cublasLt64_12.dll`, plus the `cudnn*64_9.dll`
     family — missing `cublasLt` fails the same way as missing `cublas`.
2. **Whisper wants 16 kHz mono float32.** Capture at 16 kHz mono directly, or resample before
   handing the buffer to faster-whisper.
3. **`keyboard` lib often needs admin on Windows** — prefer `pynput`; keep Win32 `RegisterHotKey`
   as the robust fallback.
4. **Synthetic paste isn't universal** — implement clipboard restore and the `SendInput` Unicode
   fallback (§7).
5. **HF symlink warning on Windows** is benign (falls back to copies) — optionally enable Windows
   Developer Mode or set `HF_HUB_DISABLE_SYMLINKS_WARNING=1` to silence it.
6. **First run downloads gigabytes.** Make it explicit with progress; never silently hang.
7. **Overlay must be non-focus-stealing — and Tkinter has no flag for this.** If the overlay steals
   focus from the target app, the paste lands in the overlay (or nowhere) and the whole flow breaks.
   `overrideredirect(True)` + `-topmost` gives a frameless topmost window but it **still activates on
   show**. There is no Tkinter API for no-activate/click-through; you need Win32 ctypes:
   `SetWindowLong(hwnd, GWL_EXSTYLE, ... | WS_EX_NOACTIVATE | WS_EX_TRANSPARENT)`. Budget real Phase 3
   effort for this and validate that paste still lands with the overlay visible. **If it stays flaky,
   switch the overlay to PySide6** (§3.1 escape hatch) — Qt supports `Qt.WindowDoesNotAcceptFocus` /
   `Qt.WA_TransparentForMouseEvents` natively. Also restore focus to the prior foreground window
   before paste regardless of framework.

---

## 13. Phased milestones

Each phase is a shippable increment with its own acceptance criteria. **Do them in order.**

### Phase 0 — Scaffolding + concurrency decision
- **Deliverables:** `pyproject.toml` (deps **with the §2.1 version pins**, ruff, pytest, `utter`
  entry point), package skeleton from §9, `config.py` (TOML load/save with the §5 schema + defaults),
  `gpu.py` **layout-aware** DLL shim (§12.1) + device detection, logging setup, a **single-instance
  guard** (named mutex/lockfile), the **§3.1 concurrency model written down** as an ADR/docstring so
  later phases don't re-litigate it, `LICENSE` (recommend MIT — confirm with owner), CI stub.
- **Key libs:** Typer, tomllib/tomli-w, ruff, pytest.
- **Acceptance:** `python -m utter --help` runs; `utter config` writes a default `config.toml`;
  `ruff check` and `pytest` pass; `gpu.py` correctly reports cuda vs cpu **and** resolves the CUDA
  DLLs in dev layout; a second `utter start` refuses to launch (single-instance guard proven).

### Phase 1 — Headless transcription pipeline (the core, proves everything)
- **Deliverables:** `recorder.py`, `transcription.py` (`FasterWhisperService`), `pipeline.py` wired
  as `utter dictate --once` = record N seconds (or until Enter) → transcribe → print text. No GUI.
  Include a **startup warmup inference** (transcribe a short silence clip after `load()`).
- **Key libs:** sounddevice, faster-whisper, numpy.
- **Acceptance:** `utter dictate --once` transcribes real speech correctly on GPU (and on CPU with
  `--device cpu`); a fixture-WAV integration test passes; model stays loaded across repeated calls
  in one process (no reload per call); **the warm per-clip compute time is measured and logged, and
  §10's latency targets are confirmed or corrected against it** (this closes the §10 open item).

### Phase 2 — Hotkey + paste (makes it feel like dictation)
- **Deliverables:** `hotkey.py`, `injector.py`; a foreground `utter start` that toggles
  record/transcribe/paste on the configured hotkey and injects into the focused window.
- **Key libs:** pynput, pyperclip.
- **Acceptance:** with a text editor focused, hotkey→speak→hotkey pastes correct text; the user's
  prior clipboard is restored; works in ≥3 different apps (editor, browser field, chat box).

### Phase 3 — Recording overlay
- **Deliverables:** `ui/overlay.py` — frameless, always-on-top, **non-focus-stealing** window
  (requires the Win32 `WS_EX_NOACTIVATE`/`WS_EX_TRANSPARENT` ctypes work — §12.7, this is not a
  Tkinter flag) with a live mic-level animation while recording and a "transcribing…" state after.
  Runs on its own thread per §3.1.
- **Key libs:** Tkinter + ctypes (**PySide6 is the sanctioned fallback** if no-activate stays flaky).
- **Acceptance:** overlay appears on hotkey, animates to real mic input, switches to transcribing
  state, fades out after paste, and **provably does not steal focus** — paste still lands in the
  originally-focused app with the overlay visible (test in a real editor, not just asserted).

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
- **Deliverables:** `ui/tui.py` — Textual app (a **separate console process** per §3.1) with the §8
  tabs (Dashboard/Model/Formatting/Hotkey/Logs); `utter dashboard` launches it; first-run setup
  wizard. Implement the **daemon↔TUI contract from §3.1**: TUI writes `config.toml`; daemon watches
  it and hot-reloads; daemon publishes live status (model/device/VRAM/recent) to `history.db`/
  `status.json` which the Dashboard polls.
- **Key libs:** Textual, watchdog (or mtime poll).
- **Acceptance:** every setting is editable in the TUI and persists to `config.toml`; Dashboard shows
  live model/device/VRAM + recent transcriptions **published by the running daemon** (cross-process);
  "test transcription" works from the Model tab; changing the hotkey in the TUI **takes effect in the
  already-running daemon without a restart** (proves the file-watch hot-reload).

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

## 17a. Adversarial review applied

This plan was adversarially reviewed before handoff. Fixes folded in: mandated the two-process +
threading model (§3.1), pinned the Blackwell-compatible faster-whisper/CTranslate2/CUDA versions
(§2.1), made the CUDA-DLL shim packaging-layout-aware and corrected the PyInstaller `_internal/`
location (§11, §12.1), corrected the latency analysis + mandated a warmup measurement (§10, Phase 1),
specified the daemon↔TUI IPC (§3.1, Phase 6), flagged the real Win32 no-activate overlay work + a
PySide6 escape hatch (§12.7, Phase 3), added the qwen3.6 thinking-suppression requirement (§6),
plus single-instance guard, audio-device selection, modifier-release-before-paste, clipboard-format
limitation, `cublasLt64_12.dll`, ~2–3 GB bundle-size reality, and code-signing/SmartScreen (§7,
§11, §12). One reviewer claim was rejected on evidence: it asserted `qwen3.6` isn't a real model,
but `ollama list` on the target machine shows it present — see §6 note.

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
