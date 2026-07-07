import pytest

from utter.hotkey import MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, parse_combo


@pytest.mark.parametrize(
    ("combo", "mods", "vk"),
    [
        ("ctrl+alt+space", MOD_CONTROL | MOD_ALT, 0x20),
        ("ctrl+shift+d", MOD_CONTROL | MOD_SHIFT, ord("D")),
        ("win+f9", MOD_WIN, 0x78),
        ("F12", 0, 0x7B),
    ],
)
def test_combo_parsing(combo, mods, vk):
    assert parse_combo(combo) == (mods, vk)


def test_empty_combo_rejected():
    with pytest.raises(ValueError):
        parse_combo("  ")


def test_modifier_only_rejected():
    with pytest.raises(ValueError):
        parse_combo("ctrl+alt")


def test_two_keys_rejected():
    with pytest.raises(ValueError):
        parse_combo("ctrl+a+b")


def test_unknown_key_rejected():
    with pytest.raises(ValueError):
        parse_combo("ctrl+bogus")


def test_bare_letter_rejected():
    # RegisterHotKey would swallow the key system-wide
    with pytest.raises(ValueError):
        parse_combo("v")


def test_bare_space_rejected():
    with pytest.raises(ValueError):
        parse_combo("space")
