"""FormattingService — rule tier + optional Ollama LLM tier (BUILD_PLAN §6).

Tier 1 (always): deterministic prefs — filler removal, replacements, punctuation,
capitalization, trailing space.

Tier 2 (optional): Ollama /api/generate pass. qwen3.6 is a hybrid THINKING model —
thinking is suppressed via "think": false AND any residual <think> block is stripped
defensively. Any error/timeout falls back silently to tier-1 text: the LLM pass must
never block a paste.
"""

from __future__ import annotations

import logging
import re

import httpx

from utter.core.config import FormattingCfg, LlmCfg

log = logging.getLogger(__name__)

_FILLERS = re.compile(r"\b(?:um+|uh+|erm+|ah+|hmm+)\b[,.!?]?\s*", re.IGNORECASE)
_THINK_BLOCK = re.compile(r"<think>.*?(?:</think>|$)", re.DOTALL)
_PUNCT = re.compile(r"[.,!?;:…]")
_SENTENCE_STARTS = re.compile(r"(^|[.!?]\s+)([a-z])")

_LLM_PROMPT = (
    "You reformat dictated text. Apply ONLY formatting/wording changes, never add content.\n"
    "User instruction: {instruction}\n"
    "Text: {text}\n"
    "Return only the reformatted text."
)


def strip_think(text: str) -> str:
    return _THINK_BLOCK.sub("", text).strip()


def apply_rules(text: str, prefs: FormattingCfg) -> str:
    out = text.strip()
    if prefs.strip_filler_words:
        out = _FILLERS.sub("", out)
        out = re.sub(r"\s{2,}", " ", out).strip()
    for pair in prefs.custom_replacements:
        if len(pair) == 2:
            out = out.replace(pair[0], pair[1])
    # capitalization BEFORE punctuation strip — sentence mode needs the boundaries
    mode = prefs.capitalization
    if mode == "lower":
        out = out.lower()
    elif mode == "upper":
        out = out.upper()
    elif mode == "sentence":
        out = _SENTENCE_STARTS.sub(lambda m: m.group(1) + m.group(2).upper(), out)
    # "as-is": leave untouched
    if not prefs.punctuation:
        out = _PUNCT.sub("", out)
    return out


def apply_llm(text: str, llm: LlmCfg) -> str:
    """Tier-2 Ollama pass. Raises on any failure — callers fall back to tier-1."""
    payload: dict = {
        "model": llm.model,
        "prompt": _LLM_PROMPT.format(instruction=llm.instruction or "(none)", text=text),
        "stream": False,
    }
    if llm.disable_thinking:
        payload["think"] = False
    resp = httpx.post(
        f"{llm.base_url}/api/generate", json=payload, timeout=llm.timeout_seconds
    )
    resp.raise_for_status()
    out = strip_think(resp.json().get("response", ""))
    if not out:
        raise ValueError("LLM returned empty text")
    return out


def format_text(text: str, prefs: FormattingCfg) -> str:
    """Full pipeline: rules -> optional LLM -> trailing space last."""
    if not text.strip():
        return ""
    out = apply_rules(text, prefs)
    if prefs.llm.enabled and out:
        try:
            out = apply_llm(out, prefs.llm)
        except Exception as exc:
            log.warning("LLM formatting failed (%s) — using rule-tier text", exc)
    if prefs.trailing_space and out:
        out += " "
    return out
