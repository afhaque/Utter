# ADR 0001 — Process & concurrency model

Status: accepted (Phase 0). Source: BUILD_PLAN.md §3.1. Later phases implement this
without re-litigating it.

## Decision

**Two processes, not one.**

- **`utterd` (daemon, launched by `utter start`):** owns the hotkey listener, recorder,
  transcription, formatting, injector, overlay, and tray.
- **`utter dashboard` (TUI):** a separate console process — Textual needs a real tty,
  the windowless daemon has none. Launched on demand from the tray menu or CLI.

**Inside the daemon:**

- **pystray owns the main thread** (`icon.run()` on main).
- **The Tkinter overlay runs on one dedicated thread** that exclusively owns the Tk root
  and its `mainloop()`. All updates from other threads are marshaled via `root.after(0, ...)`.
- **The pynput hotkey callback returns fast**: it only enqueues a start/stop event. A
  dedicated **worker thread** runs the blocking record→transcribe→format→inject chain so
  the listener and tray never freeze.

**Daemon ↔ TUI IPC (file-based, no sockets in v1):**

- Settings: the TUI writes `config.toml`; the daemon polls its mtime and hot-reloads
  (re-registers hotkey, reloads prefs) on change.
- Status/history: the daemon writes `status.json` (active model, device, recent
  transcripts) and `history.db`; the TUI Dashboard polls them.

**Single-instance guard:** a named Win32 mutex (`utter.singleinstance`) — the second
`utter start` exits with an error instead of double-grabbing the hotkey and mic.

## Consequences

- The core pipeline stays headless and importable; UI layers are thin.
- If the Tkinter no-activate overlay proves fragile, PySide6 is the sanctioned Phase-3
  escape hatch (BUILD_PLAN §12.7) — the threading model above still holds.
