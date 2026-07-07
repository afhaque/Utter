import dataclasses

import pytest

from utter.core.config import FormattingCfg, LlmCfg
from utter.core.formatting import apply_rules, format_text, strip_think


def prefs(**kw) -> FormattingCfg:
    return dataclasses.replace(FormattingCfg(), **kw)  # raises on typo'd field names


RAW = "Hello world. this is, um, a test of dictation."


@pytest.mark.parametrize(
    ("kw", "expected"),
    [
        ({}, "Hello world. This is, um, a test of dictation."),
        ({"punctuation": False}, "Hello world This is um a test of dictation"),
        ({"capitalization": "lower"}, "hello world. this is, um, a test of dictation."),
        ({"capitalization": "upper"}, "HELLO WORLD. THIS IS, UM, A TEST OF DICTATION."),
        ({"capitalization": "as-is"}, "Hello world. this is, um, a test of dictation."),
        ({"strip_filler_words": True}, "Hello world. This is, a test of dictation."),
        (
            {"custom_replacements": [["dictation", "speech-to-text"]]},
            "Hello world. This is, um, a test of speech-to-text.",
        ),
    ],
)
def test_rule_tier(kw, expected):
    assert apply_rules(RAW, prefs(**kw)) == expected


def test_trailing_space_appended():
    assert format_text("hello", prefs(trailing_space=True)) == "Hello "


def test_trailing_space_off():
    assert format_text("hello", prefs(trailing_space=False)) == "Hello"


def test_empty_input_stays_empty():
    assert format_text("   ", prefs()) == ""


def test_strip_think_block():
    assert strip_think("<think>reasoning here\nmore</think>Actual answer") == "Actual answer"


def test_strip_unclosed_think_block():
    assert strip_think("<think>never closed") == ""


def test_llm_unreachable_falls_back_to_rules():
    p = prefs(trailing_space=False)
    p.llm = LlmCfg(enabled=True, base_url="http://localhost:1", timeout_seconds=0.5)
    assert format_text("hello world", p) == "Hello world"
