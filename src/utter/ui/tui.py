"""Terminal UI (Textual) — Dashboard / Model / Formatting / Hotkey / Logs (BUILD_PLAN §8).

Runs as a SEPARATE console process from the daemon (ADR 0001). All settings edits are
written to config.toml; the running daemon watches the file and hot-reloads. Status and
history flow the other way: the daemon publishes status.json + history.db; the Dashboard
polls them.
"""

from __future__ import annotations

import json
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Horizontal
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
from utter.core.history import HistoryStore
from utter.hotkey import parse_combo
from utter.paths import log_dir, status_path

MODEL_SIZES = ["tiny", "base", "small", "medium", "large-v3"]
DEVICES = ["cuda", "cpu", "auto"]
COMPUTE_TYPES = ["float16", "int8_float16", "int8"]
CAP_MODES = ["sentence", "lower", "upper", "as-is"]


class UtterTUI(App):
    TITLE = "Utter — local dictation"
    CSS = """
    TabPane { padding: 1 2; }
    Label { margin-top: 1; }
    Button { margin-top: 1; margin-right: 2; }
    #status { border: round $accent; padding: 1; }
    .row { height: auto; }
    .field-label { width: 24; content-align: right middle; margin-right: 1; }
    """

    def __init__(self) -> None:
        super().__init__()
        self.cfg = config_store.load()
        self.history = HistoryStore()
        self._log_offset = 0

    # -- layout ---------------------------------------------------------------------------
    def compose(self) -> ComposeResult:
        cfg = self.cfg
        with TabbedContent():
            with TabPane("Dashboard", id="dashboard"):
                yield Static("loading status...", id="status")
                yield DataTable(id="recent")
            with TabPane("Model", id="model"):
                with Horizontal(classes="row"):
                    yield Label("Model size", classes="field-label")
                    yield Select(
                        [(s, s) for s in MODEL_SIZES], value=cfg.model.name, id="model_name",
                        allow_blank=False,
                    )
                with Horizontal(classes="row"):
                    yield Label("Device", classes="field-label")
                    yield Select(
                        [(d, d) for d in DEVICES], value=cfg.model.device, id="model_device",
                        allow_blank=False,
                    )
                with Horizontal(classes="row"):
                    yield Label("Compute type", classes="field-label")
                    yield Select(
                        [(c, c) for c in COMPUTE_TYPES], value=cfg.model.compute_type,
                        id="model_compute", allow_blank=False,
                    )
                with Horizontal(classes="row"):
                    yield Button("Save", id="save_model", variant="primary")
                    yield Button("Test transcription", id="test_model")
                yield Static("", id="model_msg")
            with TabPane("Formatting", id="formatting"):
                with Horizontal(classes="row"):
                    yield Label("Keep punctuation", classes="field-label")
                    yield Switch(value=cfg.formatting.punctuation, id="fmt_punct")
                with Horizontal(classes="row"):
                    yield Label("Capitalization", classes="field-label")
                    yield Select(
                        [(m, m) for m in CAP_MODES], value=cfg.formatting.capitalization,
                        id="fmt_caps", allow_blank=False,
                    )
                with Horizontal(classes="row"):
                    yield Label("Strip filler words", classes="field-label")
                    yield Switch(value=cfg.formatting.strip_filler_words, id="fmt_filler")
                with Horizontal(classes="row"):
                    yield Label("Trailing space", classes="field-label")
                    yield Switch(value=cfg.formatting.trailing_space, id="fmt_trail")
                with Horizontal(classes="row"):
                    yield Label("LLM formatting", classes="field-label")
                    yield Switch(value=cfg.formatting.llm.enabled, id="fmt_llm")
                yield Label("LLM instruction (how you want text shaped)")
                yield Input(value=cfg.formatting.llm.instruction, id="fmt_instruction")
                yield Button("Save", id="save_formatting", variant="primary")
                yield Static("", id="fmt_msg")
            with TabPane("Hotkey", id="hotkey"):
                yield Label("Toggle hotkey (e.g. ctrl+alt+space)")
                yield Input(value=cfg.general.hotkey, id="hotkey_input")
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
        status_widget = self.query_one("#status", Static)
        path = status_path()
        if path.exists():
            try:
                s = json.loads(path.read_text(encoding="utf-8"))
                if s.get("paused"):
                    state = "paused"
                else:
                    state = "running" if s.get("running") else "stopped"
                status_widget.update(
                    f"daemon: {state}   model: {s.get('model')}   device: {s.get('device')}   "
                    f"hotkey: {s.get('hotkey')}   updated: {s.get('updated', '')[:19]}"
                )
            except (json.JSONDecodeError, OSError):
                status_widget.update("daemon status unreadable")
        else:
            status_widget.update("daemon not running (no status.json) — start it with: utter start")
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

    def save_model(self) -> None:
        self.cfg.model.name = str(self.query_one("#model_name", Select).value)
        self.cfg.model.device = str(self.query_one("#model_device", Select).value)
        self.cfg.model.compute_type = str(self.query_one("#model_compute", Select).value)
        self._persist()
        self.query_one("#model_msg", Static).update(
            "saved — running daemon reloads config, but a MODEL change needs a daemon restart"
        )

    def save_formatting(self) -> None:
        self.cfg.formatting.punctuation = self.query_one("#fmt_punct", Switch).value
        self.cfg.formatting.capitalization = str(self.query_one("#fmt_caps", Select).value)
        self.cfg.formatting.strip_filler_words = self.query_one("#fmt_filler", Switch).value
        self.cfg.formatting.trailing_space = self.query_one("#fmt_trail", Switch).value
        self.cfg.formatting.llm.enabled = self.query_one("#fmt_llm", Switch).value
        self.cfg.formatting.llm.instruction = self.query_one("#fmt_instruction", Input).value
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
        self.cfg.general.hotkey = combo
        self._persist()
        msg.update(f"saved — the running daemon re-registers {combo} within ~1s")

    # -- model test -----------------------------------------------------------------------
    def test_model(self) -> None:
        self.query_one("#model_msg", Static).update("loading model + test clip...")
        self.run_worker(self._test_model_worker, thread=True, exclusive=True)

    def _test_model_worker(self) -> None:
        import numpy as np

        from utter.core.recorder import AudioClip, load_wav
        from utter.core.transcription import FasterWhisperService

        try:
            svc = FasterWhisperService(beam_size=1)
            svc.load(
                str(self.query_one("#model_name", Select).value),
                str(self.query_one("#model_device", Select).value),
                str(self.query_one("#model_compute", Select).value),
            )
            fixture = Path(__file__).parents[3] / "tests" / "fixtures" / "hello.wav"
            clip = (
                load_wav(str(fixture))
                if fixture.exists()
                else AudioClip(np.zeros(8000, dtype=np.float32), 16000)
            )
            t = svc.transcribe(clip)
            result = f"OK on {svc.device}: {t.latency_ms:.0f} ms — {t.text[:60]!r}"
        except Exception as exc:
            result = f"FAILED: {exc}"
        self.call_from_thread(self.query_one("#model_msg", Static).update, result)


def run() -> None:
    UtterTUI().run()
