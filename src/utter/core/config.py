"""ConfigStore — TOML config at %APPDATA%\\Utter\\config.toml (BUILD_PLAN §5)."""

from __future__ import annotations

import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path

import tomli_w

from utter.paths import config_path


@dataclass
class GeneralCfg:
    hotkey: str = "ctrl+alt+space"
    launch_on_startup: bool = False
    overlay: bool = True


@dataclass
class AudioCfg:
    input_device: str = "default"
    sample_rate: int = 16000


@dataclass
class ModelCfg:
    engine: str = "faster-whisper"
    name: str = "large-v3"
    device: str = "cuda"
    compute_type: str = "float16"
    beam_size: int = 5
    language: str = "auto"


@dataclass
class LlmCfg:
    enabled: bool = False
    provider: str = "ollama"
    base_url: str = "http://localhost:11434"
    model: str = "qwen3.6"
    disable_thinking: bool = True
    timeout_seconds: float = 8.0
    instruction: str = ""


@dataclass
class FormattingCfg:
    punctuation: bool = True
    capitalization: str = "sentence"  # sentence|lower|upper|as-is
    strip_filler_words: bool = False
    trailing_space: bool = True
    custom_replacements: list[list[str]] = field(default_factory=list)
    llm: LlmCfg = field(default_factory=LlmCfg)


@dataclass
class PrivacyCfg:
    save_history: bool = True


@dataclass
class InjectionCfg:
    method: str = "paste"  # paste|sendinput
    pre_paste_delay_ms: int = 150


@dataclass
class Config:
    general: GeneralCfg = field(default_factory=GeneralCfg)
    audio: AudioCfg = field(default_factory=AudioCfg)
    model: ModelCfg = field(default_factory=ModelCfg)
    formatting: FormattingCfg = field(default_factory=FormattingCfg)
    privacy: PrivacyCfg = field(default_factory=PrivacyCfg)
    injection: InjectionCfg = field(default_factory=InjectionCfg)

    def to_dict(self) -> dict:
        return asdict(self)


def _merge(dc, data: dict):
    """Overlay parsed TOML onto a dataclass instance, ignoring unknown keys."""
    for key, value in data.items():
        if not hasattr(dc, key):
            continue
        current = getattr(dc, key)
        if hasattr(current, "__dataclass_fields__") and isinstance(value, dict):
            _merge(current, value)
        else:
            setattr(dc, key, value)
    return dc


def load(path: Path | None = None) -> Config:
    """Load config, overlaying the file (if any) onto defaults."""
    path = path or config_path()
    cfg = Config()
    if path.exists():
        with open(path, "rb") as f:
            _merge(cfg, tomllib.load(f))
    return cfg


def save(cfg: Config, path: Path | None = None) -> Path:
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        tomli_w.dump(cfg.to_dict(), f)
    return path


def ensure_exists(path: Path | None = None) -> tuple[Path, bool]:
    """Write a default config if none exists. Returns (path, created)."""
    path = path or config_path()
    if path.exists():
        return path, False
    return save(Config(), path), True
