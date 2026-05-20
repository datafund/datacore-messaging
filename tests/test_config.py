import os
from pathlib import Path

import pytest
from lib.config import clear_settings_cache


@pytest.fixture(autouse=True)
def _fresh_config():
    """Clear settings cache before each test to prevent cross-test pollution."""
    clear_settings_cache()
    yield
    clear_settings_cache()


def _write_settings(tmp_path, content: str):
    """Write settings to correct .datacore/ path."""
    dc_dir = tmp_path / ".datacore"
    dc_dir.mkdir(exist_ok=True)
    (dc_dir / "settings.local.yaml").write_text(content)


def test_get_username_from_settings(tmp_path, monkeypatch):
    from lib.config import get_username

    _write_settings(tmp_path, "identity:\n  name: testuser\n")
    monkeypatch.setenv("DATACORE_ROOT", str(tmp_path))
    assert get_username() == "testuser"


def test_get_username_fallback_to_env(monkeypatch):
    from lib.config import get_username

    monkeypatch.setenv("DATACORE_ROOT", "/nonexistent")
    monkeypatch.setenv("USER", "envuser")
    assert get_username() == "envuser"


def test_get_settings_returns_empty_on_missing(monkeypatch):
    from lib.config import get_settings

    monkeypatch.setenv("DATACORE_ROOT", "/nonexistent")
    result = get_settings()
    assert result == {}


def test_get_default_space(tmp_path, monkeypatch):
    from lib.config import get_default_space

    _write_settings(tmp_path, "messaging:\n  default_space: 0-personal\n")
    monkeypatch.setenv("DATACORE_ROOT", str(tmp_path))
    assert get_default_space() == "0-personal"


def test_get_relay_url_default(monkeypatch):
    from lib.config import get_relay_url

    monkeypatch.setenv("DATACORE_ROOT", "/nonexistent")
    url = get_relay_url()
    assert url == "wss://datacore-messaging-relay.datafund.ai/ws"


def test_get_trust_tier_defaults(monkeypatch):
    from lib.config import get_trust_tier

    monkeypatch.setenv("DATACORE_ROOT", "/nonexistent")
    tier = get_trust_tier("unknown@example.com")
    assert tier == "unknown"


def test_get_trust_tier_override(tmp_path, monkeypatch):
    from lib.config import get_trust_tier

    _write_settings(
        tmp_path,
        "messaging:\n"
        "  trust_overrides:\n"
        '    "tex@team.example.com": team\n',
    )
    monkeypatch.setenv("DATACORE_ROOT", str(tmp_path))
    assert get_trust_tier("tex@team.example.com") == "team"
    assert get_trust_tier("random@example.com") == "unknown"
