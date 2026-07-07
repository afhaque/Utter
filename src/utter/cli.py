"""Typer CLI entry — `utter <command>`."""

from __future__ import annotations

import time

import typer

from utter import __version__

app = typer.Typer(help="Utter — free, open-source, fully local dictation for Windows.")


@app.command()
def version() -> None:
    """Print the Utter version."""
    typer.echo(f"utter {__version__}")


@app.command()
def config(show: bool = typer.Option(False, "--show", help="Print the config contents.")) -> None:
    """Write a default config.toml if none exists and print its location."""
    from utter.core import config as config_store

    path, created = config_store.ensure_exists()
    typer.echo(f"{'created' if created else 'exists'}: {path}")
    if show:
        typer.echo(path.read_text(encoding="utf-8"))


@app.command()
def devices() -> None:
    """List audio input devices and the transcription device."""
    import sounddevice as sd

    from utter import gpu

    typer.echo(f"transcription device: {gpu.detect_device()}")
    for idx, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] > 0:
            typer.echo(f"[{idx}] {dev['name']} ({dev['max_input_channels']} ch)")


@app.command()
def dictate(
    seconds: float | None = typer.Option(
        None, "--seconds", help="Record a fixed duration instead of waiting for Enter."
    ),
    input_file: str | None = typer.Option(
        None, "--input-file", help="Transcribe a WAV file instead of recording the mic."
    ),
    device: str | None = typer.Option(None, "--device", help="Override model device (cuda|cpu)."),
    model: str | None = typer.Option(None, "--model", help="Override model name."),
) -> None:
    """Headless dictation: record (or read a WAV), transcribe locally, print the text."""
    from utter.core import config as config_store
    from utter.core.pipeline import Pipeline
    from utter.logging_setup import setup

    setup()
    cfg = config_store.load()
    if device:
        cfg.model.device = device
    if model:
        cfg.model.name = model

    pipeline = Pipeline(cfg)
    pipeline.load()

    if input_file:
        from utter.core.recorder import load_wav

        transcript, final = pipeline.process_clip(load_wav(input_file))
    else:
        pipeline.start_recording()
        if seconds is None:
            typer.echo("Recording... press Enter to stop.")
            input()
        else:
            typer.echo(f"Recording for {seconds:.0f}s...")
            time.sleep(seconds)
        transcript, final = pipeline.stop_and_process()

    typer.echo(final)
    typer.echo(f"[{transcript.language}, {transcript.latency_ms:.0f} ms]", err=True)


@app.command()
def dashboard() -> None:
    """Open the terminal dashboard / settings UI (separate process from the daemon)."""
    from utter.ui import tui

    tui.run()


def _first_run_wizard() -> None:
    """Short terminal setup on first launch (BUILD_PLAN §8 first-run flow)."""
    from utter.core import config as config_store
    from utter.core.config import Config
    from utter.hotkey import parse_combo
    from utter.paths import config_path

    if config_path().exists():
        return
    typer.echo("First run — quick setup (press Enter to accept defaults).")
    cfg = Config()
    def _clean(s: str) -> str:
        return s.strip().lstrip("﻿")

    cfg.model.name = _clean(
        typer.prompt(
            "Model size (tiny/base/small/medium/large-v3; larger = more accurate,"
            " bigger download)",
            default=cfg.model.name,
        )
    )
    cfg.model.device = _clean(typer.prompt("Device (cuda/cpu/auto)", default=cfg.model.device))
    while True:
        combo = _clean(typer.prompt("Toggle hotkey", default=cfg.general.hotkey))
        try:
            parse_combo(combo)
            cfg.general.hotkey = combo
            break
        except ValueError as exc:
            typer.echo(f"  invalid hotkey: {exc}")
    path = config_store.save(cfg)
    typer.echo(f"Config written to {path}.")
    typer.echo("Note: the first use of a new model size downloads weights from Hugging Face.")


@app.command()
def start() -> None:
    """Start the Utter daemon (hotkey listener + tray)."""
    from utter.logging_setup import setup
    from utter.singleinstance import SingleInstance

    setup()
    guard = SingleInstance()
    if not guard.acquire():
        typer.echo("Utter is already running — refusing to start a second instance.", err=True)
        raise typer.Exit(code=1)
    _first_run_wizard()
    from utter import app as utter_app
    from utter.core import config as config_store

    try:
        cfg = config_store.load()
        typer.echo(f"Utter daemon starting (hotkey: {cfg.general.hotkey}, Ctrl+C to stop)...")
        utter_app.run(cfg)
    except KeyboardInterrupt:
        pass
    finally:
        guard.release()


def main() -> None:
    app()
