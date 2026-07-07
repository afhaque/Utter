"""TUI tests via Textual's headless Pilot."""

import pytest

import utter.core.config as config_store


@pytest.fixture()
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("UTTER_HOME", str(tmp_path))
    config_store.ensure_exists()
    return tmp_path


@pytest.mark.asyncio
async def test_all_five_tabs_present(isolated_home):
    from textual.widgets import TabPane

    from utter.ui.tui import UtterTUI

    app = UtterTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        ids = {pane.id for pane in app.query(TabPane)}
    assert ids == {"dashboard", "model", "formatting", "hotkey", "logs"}


@pytest.mark.asyncio
async def test_hotkey_edit_persists_to_config(isolated_home):
    from textual.widgets import Input

    from utter.ui.tui import UtterTUI

    app = UtterTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        app.query_one("#hotkey_input", Input).value = "ctrl+shift+f9"
        await pilot.pause()
        app.save_hotkey()
        await pilot.pause()
    cfg = config_store.load()
    assert cfg.general.hotkey == "ctrl+shift+f9"


@pytest.mark.asyncio
async def test_invalid_hotkey_rejected(isolated_home):
    from textual.widgets import Input, Static

    from utter.ui.tui import UtterTUI

    app = UtterTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        app.query_one("#hotkey_input", Input).value = "ctrl+alt"
        app.save_hotkey()
        await pilot.pause()
        msg = str(app.query_one("#hotkey_msg", Static).render())
    assert "invalid" in msg
    assert config_store.load().general.hotkey == "ctrl+alt+space"  # unchanged


@pytest.mark.asyncio
async def test_formatting_switch_persists(isolated_home):
    from textual.widgets import Switch

    from utter.ui.tui import UtterTUI

    app = UtterTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        app.query_one("#fmt_filler", Switch).value = True
        await pilot.pause()
        app.save_formatting()
        await pilot.pause()
    assert config_store.load().formatting.strip_filler_words is True
