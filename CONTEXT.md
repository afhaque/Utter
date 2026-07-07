# Utter

<p align="center">
  <img src="logo.jpg" width="240" alt="Utter logo — an otter sitting on a telephone handset sitting on a microphone" />
</p>

**Utter** is a free, open-source, fully local dictation app for Windows. It's a drop-in
alternative to cloud dictation tools (like Wispr Flow) — same "hotkey, speak, paste"
workflow, but transcription runs entirely on your own machine using a local model of
your choosing. No subscription, no audio leaving your computer, no network round-trip.

## Why

Cloud dictation tools charge a recurring fee to do something a modern consumer GPU can
already do well: turn speech into text, fast, using open-weight speech-to-text models
(e.g. Whisper and its derivatives) running locally. Utter exists to make that local path
as easy to use as the cloud version, at zero marginal cost per use and with nothing sent
off-device.

## Core Concept

- **Local-model-agnostic transcription.** Utter doesn't ship a fixed model — it lets the
  user pick which local speech-to-text model handles transcription (starting with
  Whisper-family models via `faster-whisper`, with room to support alternatives as they
  emerge). The user's hardware and preferences decide the tradeoff between speed and
  accuracy, not Utter.
- **Runs in the background.** Once launched, Utter sits quietly as a background process —
  no visible window, minimal resource use while idle.
- **Hotkey-summoned recording.** Pressing a configurable hotkey brings up a small on-screen
  overlay that animates while actively recording, giving clear visual confirmation that
  Utter is listening. Pressing the hotkey again stops the recording, runs local
  transcription, and pastes the resulting text directly into whatever application currently
  has focus.
- **A dashboard.** A lightweight view into what Utter is doing — recent transcriptions,
  which model is active, basic status/health — so the tool doesn't feel like a black box.
- **A terminal interface for configuration.** Setup and tuning happen through a terminal
  UI rather than a heavyweight settings app, covering things like:
  - **Model selection** — choose which local model/model size handles transcription.
  - **Output formatting preferences** — how transcribed text should be shaped before it's
    pasted, e.g.:
    - Punctuation on/off
    - Capitalization rules (sentence case, all lowercase, etc.)
    - Other light post-processing preferences the user wants applied to raw transcription
      output before it lands in the target app.

## Distribution

Utter is intended to ship as a standalone Windows executable — something a user can
install and run without needing to manually set up a Python environment — while remaining
fully open source, so anyone can inspect, modify, or extend it (swap in a different local
model, add new formatting rules, etc.).

## Status

This repository currently holds the concept/spec only. Implementation has not started yet.

## License

TBD.
