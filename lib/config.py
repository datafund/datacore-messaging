"""Shared configuration for datacore-messaging.

Single source of truth for settings, identity, relay config,
and trust tier resolution. Replaces duplicated getters across
hooks, GUI, and relay code.
"""

import os
from pathlib import Path
from typing import Any

_settings_cache: dict | None = None
_RELAY_URL_DEFAULT = "wss://datacore-messaging-relay.datafund.ai/ws"

_TRUST_TIER_DEFAULTS = {
    "owner": {
        "priority_boost": 2.0,
        "daily_token_limit": 0,
        "max_task_effort": 0,
        "auto_accept": True,
    },
    "team": {
        "priority_boost": 1.5,
        "daily_token_limit": 100_000,
        "max_task_effort": 8,
        "auto_accept": True,
    },
    "trusted": {
        "priority_boost": 1.0,
        "daily_token_limit": 50_000,
        "max_task_effort": 5,
        "auto_accept": False,
    },
    "unknown": {
        "priority_boost": 0.5,
        "daily_token_limit": 10_000,
        "max_task_effort": 3,
        "auto_accept": False,
    },
}


def datacore_root() -> Path:
    return Path(os.environ.get("DATACORE_ROOT", str(Path.home() / "Data")))


def get_settings() -> dict[str, Any]:
    """Load settings from .datacore/settings.local.yaml, with caching.

    Call clear_settings_cache() in tests before each test that uses
    monkeypatch to change DATACORE_ROOT.
    """
    global _settings_cache
    if _settings_cache is not None:
        return _settings_cache

    try:
        import yaml
    except ImportError:
        return {}

    settings_path = datacore_root() / ".datacore" / "settings.local.yaml"
    if not settings_path.exists():
        return {}

    try:
        with open(settings_path) as f:
            _settings_cache = yaml.safe_load(f) or {}
    except Exception:
        _settings_cache = {}

    return _settings_cache


def clear_settings_cache() -> None:
    """Clear cached settings. Call in test fixtures, not in production code."""
    global _settings_cache
    _settings_cache = None


def get_username() -> str:
    """Get messaging username from settings or environment."""
    settings = get_settings()
    name = settings.get("identity", {}).get("name", "")
    if name:
        return name
    return os.environ.get("USER", "unknown")


def get_default_space() -> str:
    """Get default messaging space."""
    settings = get_settings()
    return settings.get("messaging", {}).get("default_space", "0-personal")


def get_relay_url() -> str:
    """Get relay WebSocket URL."""
    settings = get_settings()
    url = settings.get("messaging", {}).get("relay", {}).get("url", "")
    return url or _RELAY_URL_DEFAULT


def get_relay_secret() -> str:
    """Get relay authentication secret."""
    settings = get_settings()
    secret = settings.get("messaging", {}).get("relay", {}).get("secret", "")
    return secret or os.environ.get("RELAY_SECRET", "")


def get_trust_tier(actor_id: str) -> str:
    """Resolve trust tier for an actor. Returns tier name."""
    settings = get_settings()
    overrides = settings.get("messaging", {}).get("trust_overrides", {})
    if actor_id in overrides:
        return overrides[actor_id]
    return "unknown"


def get_trust_tier_config(tier_name: str) -> dict[str, Any]:
    """Get configuration for a trust tier."""
    settings = get_settings()
    custom_tiers = settings.get("messaging", {}).get("trust_tiers", {})
    if tier_name in custom_tiers:
        merged = dict(_TRUST_TIER_DEFAULTS.get(tier_name, {}))
        merged.update(custom_tiers[tier_name])
        return merged
    return dict(_TRUST_TIER_DEFAULTS.get(tier_name, _TRUST_TIER_DEFAULTS["unknown"]))


def get_compute_config() -> dict[str, Any]:
    """Get compute budget configuration."""
    settings = get_settings()
    defaults = {
        "daily_budget_tokens": 500_000,
        "per_sender_daily_max": 100_000,
        "per_task_max_tokens": 50_000,
        "per_task_timeout_minutes": 30,
        "cooldown_between_tasks": 60,
        "max_queue_depth": 20,
        "rate_limits": {
            "tasks_per_hour": 5,
        },
    }
    custom = settings.get("messaging", {}).get("compute", {})
    defaults.update(custom)
    return defaults


def messaging_dir(space: str | None = None) -> Path:
    """Get the messaging org directory for a space."""
    root = datacore_root()
    space = space or get_default_space()
    return root / space / "org" / "messaging"


def agent_inbox_path(agent_name: str, space: str | None = None) -> Path:
    """Get the inbox file path for a specific agent."""
    return messaging_dir(space) / "agents" / f"{agent_name}.org"
