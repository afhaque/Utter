import utter.core.config as config_store
from utter.core.config import Config


def test_default_config_round_trip(tmp_path):
    path = tmp_path / "config.toml"
    cfg = Config()
    config_store.save(cfg, path)
    loaded = config_store.load(path)
    assert loaded.to_dict() == cfg.to_dict()


def test_load_missing_file_gives_defaults(tmp_path):
    cfg = config_store.load(tmp_path / "nope.toml")
    assert cfg.general.hotkey == "ctrl+alt+space"
    assert cfg.model.name == "large-v3"
    assert cfg.formatting.llm.enabled is False


def test_partial_file_overlays_defaults(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[model]\nname = "small"\n', encoding="utf-8")
    cfg = config_store.load(path)
    assert cfg.model.name == "small"
    assert cfg.model.device == "cuda"  # untouched default


def test_unknown_keys_ignored(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[general]\nbogus = true\nhotkey = "f9"\n', encoding="utf-8")
    cfg = config_store.load(path)
    assert cfg.general.hotkey == "f9"
    assert not hasattr(cfg.general, "bogus")


def test_utf8_bom_tolerated(tmp_path):
    path = tmp_path / "config.toml"
    path.write_bytes(b'\xef\xbb\xbf[general]\nhotkey = "f8"\n')
    assert config_store.load(path).general.hotkey == "f8"


def test_ensure_exists_creates_once(tmp_path):
    path = tmp_path / "config.toml"
    _, created_first = config_store.ensure_exists(path)
    _, created_second = config_store.ensure_exists(path)
    assert created_first is True
    assert created_second is False


def test_saved_file_contains_all_sections(tmp_path):
    path = tmp_path / "config.toml"
    config_store.save(Config(), path)
    text = path.read_text(encoding="utf-8")
    for section in ("[general]", "[audio]", "[model]", "[formatting]",
                    "[formatting.llm]", "[privacy]", "[injection]"):
        assert section in text
