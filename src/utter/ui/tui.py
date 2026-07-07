"""Terminal UI (Textual) — Dashboard / Model / Formatting / Hotkey / Logs (BUILD_PLAN §8).

Runs as a SEPARATE console process from the daemon (ADR 0001). All settings edits are
written to config.toml; the running daemon watches the file and hot-reloads. Status and
history flow the other way: the daemon publishes status.json + history.db; the Dashboard
polls them.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime

from textual.app import App, ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widget import Widget
from textual.widgets import (
    Button,
    DataTable,
    Input,
    Label,
    RichLog,
    Select,
    Static,
    Switch,
    TabbedContent,
    TabPane,
)

from utter.core import config as config_store
from utter.core.config import (
    CAP_MODES,
    COMPUTE_TYPES,
    DEVICES,
    INJECTION_METHODS,
    MODEL_SIZES,
)
from utter.core.history import HistoryStore
from utter.hotkey import parse_combo
from utter.paths import history_db_path, log_dir, status_path

STALE_AFTER_S = 120


def _options(values: list[str], current: str) -> list[tuple[str, str]]:
    """Select options that always include the current config value — a hand-edited or
    path-style value must never crash the settings UI meant to fix it."""
    vals = list(values)
    if current not in vals:
        vals.append(current)
    return [(v, v) for v in vals]


def _replacements_to_text(pairs: list[list[str]]) -> str:
    return "; ".join(f"{a} => {b}" for a, b in pairs if len([a, b]) == 2)


def _text_to_replacements(text: str) -> list[list[str]]:
    pairs = []
    for chunk in text.split(";"):
        if "=>" in chunk:
            a, _, b = chunk.partition("=>")
            if a.strip():
                pairs.append([a.strip(), b.strip()])
    return pairs


class UtterTUI(App):
    TITLE = "Utter — local dictation"
    CSS = """
    TabPane { padding: 1 2; }
    Button { margin-top: 1; margin-right: 2; }
    #status { border: round $accent; padding: 1; margin-bottom: 1; }
    .row { height: auto; }
    .field-label { width: 26; content-align: right middle; margin-right: 1; padding-top: 1; }
    .section { margin-top: 1; text-style: bold; }
    """

    def __init__(self) -> None:
        super().__init__()
        self.cfg = config_store.load()
        self.history = HistoryStore()
        self._log_offset = 0
        self._status_mtime = 0.0
        self._history_mtime = -1.0

    # -- layout ---------------------------------------------------------------------------
    def _row(self, label: str, widget: Widget) -> Iterable[Widget]:
        with Horizontal(classes="row"):
            yield Label(label, classes="field-label")
            yield widget

    def compose(self) -> ComposeResult:
        cfg = self.cfg
        with TabbedContent():
            with TabPane("Dashboard", id="dashboard"):
                yield Static("loading status...", id="status")
                yield DataTable(id="recent")
            with TabPane("Model", id="model"), VerticalScroll():
                yield from self._row(
                    "Model size",
                    Select(_options(MODEL_SIZES, cfg.model.name), value=cfg.model.name,
                           id="model_name", allow_blank=False),
                )
                yield from self._row(
                    "Device",
                    Select(_options(DEVICES, cfg.model.device), value=cfg.model.device,
                           id="model_device", allow_blank=False),
                )
                yield from self._row(
                    "Compute type",
                    Select(_options(COMPUTE_TYPES, cfg.model.compute_type),
                           value=cfg.model.compute_type, id="model_compute", allow_blank=False),
                )
                yield from self._row(
                    "Language (auto or ISO code)", Input(value=cfg.model.language, id="model_lang")
                )
                yield from self._row(
                    "Audio input device", Input(value=cfg.audio.input_device, id="audio_device")
                )
                with Horizontal(classes="row"):
                    yield Button("Save", id="save_model", variant="primary")
                    yield Button("Test transcription", id="test_model")
                yield Static("", id="model_msg")
            with TabPane("Formatting", id="formatting"), VerticalScroll():
                yield from self._row(
                    "Keep punctuation", Switch(value=cfg.formatting.punctuation, id="fmt_punct")
                )
                yield from self._row(
                    "Capitalization",
                    Select(_options(CAP_MODES, cfg.formatting.capitalization),
                           value=cfg.formatting.capitalization, id="fmt_caps", allow_blank=False),
                )
                yield from self._row(
                    "Strip filler words",
                    Switch(value=cfg.formatting.strip_filler_words, id="fmt_filler"),
                )
                yield from self._row(
                    "Trailing space", Switch(value=cfg.formatting.trailing_space, id="fmt_trail")
                )
                yield from self._row(
                    "Custom replacements (a => b; c => d)",
                    Input(value=_replacements_to_text(cfg.formatting.custom_replacements),
                          id="fmt_repl"),
                )
                yield from self._row(
                    "Save history", Switch(value=cfg.privacy.save_history, id="priv_history")
                )
                yield Label("LLM formatting pass (Ollama)", classes="section")
                yield from self._row(
                    "Enabled", Switch(value=cfg.formatting.llm.enabled, id="fmt_llm")
                )
                yield from self._row(
                    "Model", Input(value=cfg.formatting.llm.model, id="llm_model")
                )
                yield from self._row(
                    "Base URL", Input(value=cfg.formatting.llm.base_url, id="llm_url")
                )
                yield from self._row(
                    "Timeout (s)",
                    Input(value=str(cfg.formatting.llm.timeout_seconds), id="llm_timeout"),
                )
                yield from self._row(
                    "Instruction", Input(value=cfg.formatting.llm.instruction,
                                         id="fmt_instruction")
                )
                yield Button("Save", id="save_formatting", variant="primary")
                yield Static("", id="fmt_msg")
            with TabPane("Hotkey", id="hotkey"), VerticalScroll():
                yield from self._row(
                    "Toggle hotkey", Input(value=cfg.general.hotkey, id="hotkey_input")
                )
                yield from self._row(
                    "Show overlay", Switch(value=cfg.general.overlay, id="gen_overlay")
                )
                yield from self._row(
                    "Launch on startup",
                    Switch(value=cfg.general.launch_on_startup, id="gen_startup"),
                )
                yield from self._row(
                    "Injection method",
                    Select(_options(INJECTION_METHODS, cfg.injection.method),
                           value=cfg.injection.method, id="inj_method", allow_blank=False),
                )
                yield from self._row(
                    "Pre-paste delay (ms)",
                    Input(value=str(cfg.injection.pre_paste_delay_ms), id="inj_delay"),
                )
                yield Button("Save", id="save_hotkey", variant="primary")
                yield Static("", id="hotkey_msg")
            with TabPane("Logs", id="logs"):
                yield RichLog(id="log_view", wrap=True, highlight=False, markup=False)

    def on_mount(self) -> None:
        table = self.query_one("#recent", DataTable)
        table.add_columns("time", "text", "ms", "model")
        self.refresh_dashboard()
        self.refresh_logs()
        self.set_interval(2.0, self.refresh_dashboard)
        self.set_interval(2.0, self.refresh_logs)

    # -- dashboard ------------------------------------------------------------------------
    def refresh_dashboard(self) -> None:
        self._refresh_status()
        self._refresh_recent()

    def _refresh_status(self) -> None:
        status_widget = self.query_one("#status", Static)
        path = status_path()
        if not path.exists():
            status_widget.update("daemon not running (no status.json) — start with: utter start")
            return
        mtime = path.stat().st_mtime
        if mtime == self._status_mtime:
            return
        self._status_mtime = mtime
        try:
            s = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            status_widget.update("daemon status unreadable")
            return
        if s.get("paused"):
            state = "paused"
        else:
            state = "running" if s.get("running") else "stopped"
        try:
            age = (datetime.now(UTC) - datetime.fromisoformat(s.get("updated", ""))).total_seconds()
        except ValueError:
            age = 0.0
        is_stale = state == "running" and age > STALE_AFTER_S
        stale = " (stale — daemon may have crashed)" if is_stale else ""
        vram = f"   vram: {s['vram']}" if s.get("vram") else ""
        status_widget.update(
            f"daemon: {state}{stale}   model: {s.get('model')}   device: {s.get('device')}"
            f"{vram}   hotkey: {s.get('hotkey')}   updated: {s.get('updated', '')[:19]}"
        )

    def _refresh_recent(self) -> None:
        db = history_db_path()
        mtime = db.stat().st_mtime if db.exists() else 0.0
        if mtime == self._history_mtime:
            return
        self._history_mtime = mtime
        table = self.query_one("#recent", DataTable)
        table.clear()
        for row in self.history.recent(10):
            text = row["final"] or row["raw"]
            if len(text) > 60:
                text = text[:57] + "..."
            table.add_row(row["ts"][11:19], text, f"{row['latency_ms']:.0f}", row["model"])

    def refresh_logs(self) -> None:
        log_file = log_dir() / "utter.log"
        if not log_file.exists():
            return
        view = self.query_one("#log_view", RichLog)
        try:
            if log_file.stat().st_size < self._log_offset:
                self._log_offset = 0  # log rotated — start over
            with open(log_file, encoding="utf-8", errors="replace") as f:
                f.seek(self._log_offset)
                new = f.read()
                self._log_offset = f.tell()
            if new:
                view.write(new.rstrip())
        except OSError:
            pass

    # -- saves ----------------------------------------------------------------------------
    def on_button_pressed(self, event: Button.Pressed) -> None:
        handler = {
            "save_model": self.save_model,
            "test_model": self.test_model,
            "save_formatting": self.save_formatting,
            "save_hotkey": self.save_hotkey,
        }.get(event.button.id or "")
        if handler:
            handler()

    def _persist(self) -> None:
        config_store.save(self.cfg)

    def _fresh_cfg(self) -> None:
        # re-read before writing so a save from one tab can't clobber concurrent
        # hand-edits to unrelated sections
        self.cfg = config_store.load()

    def save_model(self) -> None:
        self._fresh_cfg()
        self.cfg.model.name = str(self.query_one("#model_name", Select).value)
        self.cfg.model.device = str(self.query_one("#model_device", Select).value)
        self.cfg.model.compute_type = str(self.query_one("#model_compute", Select).value)
        self.cfg.model.language = self.query_one("#model_lang", Input).value.strip() or "auto"
        self.cfg.audio.input_device = (
            self.query_one("#audio_device", Input).value.strip() or "default"
        )
        self._persist()
        self.query_one("#model_msg", Static).update(
            "saved — model/audio changes need a daemon restart"
        )

    def save_formatting(self) -> None:
        self._fresh_cfg()
        f = self.cfg.formatting
        f.punctuation = self.query_one("#fmt_punct", Switch).value
        f.capitalization = str(self.query_one("#fmt_caps", Select).value)
        f.strip_filler_words = self.query_one("#fmt_filler", Switch).value
        f.trailing_space = self.query_one("#fmt_trail", Switch).value
        f.custom_replacements = _text_to_replacements(self.query_one("#fmt_repl", Input).value)
        f.llm.enabled = self.query_one("#fmt_llm", Switch).value
        f.llm.model = self.query_one("#llm_model", Input).value.strip() or f.llm.model
        f.llm.base_url = self.query_one("#llm_url", Input).value.strip() or f.llm.base_url
        try:
            f.llm.timeout_seconds = float(self.query_one("#llm_timeout", Input).value)
        except ValueError:
            pass
        f.llm.instruction = self.query_one("#fmt_instruction", Input).value
        self.cfg.privacy.save_history = self.query_one("#priv_history", Switch).value
        self._persist()
        self.query_one("#fmt_msg", Static).update("saved — takes effect on the next dictation")

    def save_hotkey(self) -> None:
        combo = self.query_one("#hotkey_input", Input).value.strip()
        msg = self.query_one("#hotkey_msg", Static)
        try:
            parse_combo(combo)
        except ValueError as exc:
            msg.update(f"invalid hotkey: {exc}")
            return
        self._fresh_cfg()
        self.cfg.general.hotkey = combo
        self.cfg.general.overlay = self.query_one("#gen_overlay", Switch).value
        self.cfg.general.launch_on_startup = self.query_one("#gen_startup", Switch).value
        self.cfg.injection.method = str(self.query_one("#inj_method", Select).value)
        try:
            self.cfg.injection.pre_paste_delay_ms = int(self.query_one("#inj_delay", Input).value)
        except ValueError:
            pass
        self._persist()
        msg.update(f"saved — the running daemon re-registers {combo} within ~1s")

    # -- model test -----------------------------------------------------------------------
    def test_model(self) -> None:
        self.query_one("#model_msg", Static).update("loading model + test clip...")
        self.run_worker(self._test_model_worker, thread=True, exclusive=True)

    def _test_model_worker(self) -> None:
        from pathlib import Path

        from utter.core.recorder import load_wav, silence_clip
        from utter.core.transcription import FasterWhisperService

        try:
            svc = FasterWhisperService(beam_size=1)
            svc.load(
                str(self.query_one("#model_name", Select).value),
                str(self.query_one("#model_device", Select).value),
                str(self.query_one("#model_compute", Select).value),
            )
            fixture = Path(__file__).parents[3] / "tests" / "fixtures" / "hello.wav"
            clip = load_wav(str(fixture)) if fixture.exists() else silence_clip()
            t = svc.transcribe(clip)
            result = f"OK on {svc.device}: {t.latency_ms:.0f} ms — {t.text[:60]!r}"
        except Exception as exc:
            result = f"FAILED: {exc}"
        self.call_from_thread(self.query_one("#model_msg", Static).update, result)


def run() -> None:
    UtterTUI().run()
