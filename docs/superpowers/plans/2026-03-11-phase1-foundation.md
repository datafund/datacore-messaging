# Phase 1: Foundation — org-workspace, Governance, Bug Fixes

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the datacore-messaging prototype to use org-workspace for storage, add task governance (trust tiers, budgets, rate limits), fix all critical/high audit issues, and add tests. This is Phase 1 of DIP-0023.

**Architecture:** Extract shared utilities into a `lib/config.py` module. Replace all raw file manipulation with org-workspace API calls through a `lib/message_store.py` abstraction. Add `lib/governor.py` for task governance. Consolidate relay into single `lib/relay.py`. Keep existing GUI and hooks functional but rewired to use the new library layer.

**Tech Stack:** Python 3.10+, org-workspace (PyPI), aiohttp, websockets, PyQt6, pytest

**PR Target:** `datafund/datacore-messaging` main branch

---

## Chunk 1: Project Setup and Shared Utilities

### Task 1: Add org-workspace dependency and update project config

**Files:**
- Modify: `requirements.txt`
- Create: `pyproject.toml`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Update requirements.txt**

```
org-workspace>=0.3.0
aiohttp>=3.9.0
websockets>=12.0
pyyaml>=6.0
```

- [ ] **Step 2: Create pyproject.toml for test configuration**

```toml
[project]
name = "datacore-messaging"
version = "0.2.0"
requires-python = ">=3.10"
dependencies = [
    "org-workspace>=0.3.0",
    "aiohttp>=3.9.0",
    "websockets>=12.0",
    "pyyaml>=6.0",
]

[project.optional-dependencies]
gui = ["PyQt6>=6.5.0"]
dev = ["pytest>=7.0", "pytest-asyncio>=0.21", "pytest-aiohttp>=1.0"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

- [ ] **Step 3: Create test scaffolding**

Create `tests/__init__.py` (empty) and `tests/conftest.py`:

```python
import os
import tempfile
from pathlib import Path

import pytest
from org_workspace import OrgWorkspace, StateConfig


@pytest.fixture
def tmp_space(tmp_path):
    """Create a temporary Datacore space with messaging directories."""
    org_dir = tmp_path / "org" / "messaging"
    org_dir.mkdir(parents=True)
    agents_dir = org_dir / "agents"
    agents_dir.mkdir()

    # Write inbox.org with proper TODO keywords
    inbox = org_dir / "inbox.org"
    inbox.write_text(
        "#+TODO: TODO WAITING QUEUED WORKING | DONE CANCELLED ARCHIVED\n"
    )

    # Write agent inbox
    agent_inbox = agents_dir / "test-claude.org"
    agent_inbox.write_text(
        "#+TODO: TODO WAITING QUEUED WORKING | DONE CANCELLED ARCHIVED\n"
    )

    return tmp_path


@pytest.fixture
def msg_state_config():
    """StateConfig for message storage (inbox.org). DONE is terminal for messages."""
    return StateConfig(
        active=["TODO", "WAITING"],
        terminal=["DONE", "CANCELLED", "ARCHIVED"],
    )


@pytest.fixture
def task_state_config():
    """StateConfig for agent tasks. DONE is NOT terminal — allows revision cycle."""
    return StateConfig(
        active=["TODO", "WAITING", "QUEUED", "WORKING", "DONE"],
        terminal=["CANCELLED", "ARCHIVED"],
    )


@pytest.fixture
def workspace(tmp_space, msg_state_config):
    """Pre-loaded OrgWorkspace for messaging tests."""
    ws = OrgWorkspace(state_config=msg_state_config)
    inbox = tmp_space / "org" / "messaging" / "inbox.org"
    ws.load(inbox)
    return ws
```

- [ ] **Step 4: Install dev dependencies and verify**

Run: `pip install -e ".[dev]"` (from repo root)
Run: `pytest --co -q`
Expected: `no tests ran` (collection succeeds, no tests yet)

- [ ] **Step 5: Commit**

```bash
git add requirements.txt pyproject.toml tests/
git commit -m "chore: add org-workspace dependency, pytest config, test scaffolding"
```

---

### Task 2: Extract shared config module

**Files:**
- Create: `lib/__init__.py`
- Create: `lib/config.py`
- Create: `tests/test_config.py`

Currently `get_username()`, `get_settings()`, `get_default_space()`, `get_relay_url()`, `get_relay_secret()` are duplicated across 5+ files. Extract into one module.

- [ ] **Step 1: Write failing tests for config**

```python
# tests/test_config.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_config.py -v`
Expected: FAIL (lib.config doesn't exist)

- [ ] **Step 3: Implement lib/config.py**

```python
# lib/__init__.py
"""Datacore messaging library."""
import sys
from pathlib import Path

# Ensure lib/ is importable from hooks/ (hooks run standalone)
_LIB_DIR = Path(__file__).resolve().parent
_REPO_DIR = _LIB_DIR.parent
if str(_REPO_DIR) not in sys.path:
    sys.path.insert(0, str(_REPO_DIR))

# lib/config.py
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

    # Datacore stores settings at .datacore/settings.local.yaml
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_config.py -v`
Expected: All 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add lib/__init__.py lib/config.py tests/test_config.py
git commit -m "feat: extract shared config module — single source for settings, trust tiers, paths"
```

---

## Chunk 2: Message Store (org-workspace integration)

### Task 3: Implement message store with org-workspace

**Files:**
- Create: `lib/message_store.py`
- Create: `tests/test_message_store.py`

This is the core replacement for all raw file manipulation. Every message read/write goes through this module.

- [ ] **Step 1: Write failing tests for message store**

```python
# tests/test_message_store.py
from datetime import datetime
from pathlib import Path

import pytest
from org_workspace import OrgWorkspace, StateConfig


@pytest.fixture
def store(tmp_space, msg_state_config):
    from lib.message_store import MessageStore

    return MessageStore(tmp_space, state_config=msg_state_config)


class TestCreateMessage:
    def test_create_message_basic(self, store):
        node = store.create_message(
            from_actor="gregor@example.com",
            to_actor="tex@example.com",
            content="Hello from tests",
        )
        assert node.todo == "TODO"
        assert "message" in node.shallow_tags
        assert "unread" in node.shallow_tags
        assert node.properties["FROM"] == "gregor@example.com"
        assert node.properties["TO"] == "tex@example.com"
        assert "msg-" in node.properties["ID"]

    def test_create_message_with_thread(self, store):
        parent = store.create_message(
            from_actor="tex@example.com",
            to_actor="gregor@example.com",
            content="Original",
        )
        reply = store.create_message(
            from_actor="gregor@example.com",
            to_actor="tex@example.com",
            content="Reply",
            reply_to=parent.properties["ID"],
        )
        assert reply.properties["REPLY_TO"] == parent.properties["ID"]
        assert reply.properties["THREAD"] == parent.properties["ID"]

    def test_message_ids_are_unique(self, store):
        msg1 = store.create_message(
            from_actor="a@x.com", to_actor="b@x.com", content="hello"
        )
        msg2 = store.create_message(
            from_actor="a@x.com", to_actor="b@x.com", content="different"
        )
        assert msg1.properties["ID"] != msg2.properties["ID"]

    def test_message_id_same_content_different_time(self, store):
        # Same content at different times should still differ (timestamp in ID)
        msg1 = store.create_message(
            from_actor="a@x.com", to_actor="b@x.com", content="same"
        )
        msg2 = store.create_message(
            from_actor="a@x.com", to_actor="b@x.com", content="same"
        )
        # IDs may collide within same second — that's OK for tests
        # In production, content hash includes timestamp


class TestQueryMessages:
    def test_find_unread(self, store):
        store.create_message("a@x.com", "b@x.com", "msg1")
        store.create_message("a@x.com", "b@x.com", "msg2")
        unread = store.find_unread()
        assert len(unread) == 2

    def test_find_unread_after_mark_read(self, store):
        msg = store.create_message("a@x.com", "b@x.com", "test")
        store.mark_read(msg)
        unread = store.find_unread()
        assert len(unread) == 0

    def test_find_by_thread(self, store):
        parent = store.create_message("a@x.com", "b@x.com", "parent")
        pid = parent.properties["ID"]
        store.create_message("b@x.com", "a@x.com", "reply1", reply_to=pid)
        store.create_message("b@x.com", "a@x.com", "reply2", reply_to=pid)
        thread = store.find_thread(pid)
        assert len(thread) >= 2  # replies


class TestMarkOperations:
    def test_mark_read(self, store):
        msg = store.create_message("a@x.com", "b@x.com", "test")
        store.mark_read(msg)
        assert msg.todo == "DONE"

    def test_mark_archived(self, store):
        msg = store.create_message("a@x.com", "b@x.com", "test")
        store.mark_read(msg)
        store.archive(msg)
        assert msg.todo == "ARCHIVED"


class TestFileDelivery:
    def test_create_file_delivery(self, store):
        node = store.create_file_delivery(
            from_actor="tex@example.com",
            filename="report.pdf",
            size=2400000,
            content_type="application/pdf",
            swarm_ref="abc123",
        )
        assert node.todo == "TODO"
        assert "file_delivery" in node.shallow_tags
        assert "unread" in node.shallow_tags
        assert node.properties["FILENAME"] == "report.pdf"
        assert node.properties["SIZE"] == "2400000"
        assert node.properties["DOWNLOADED"] == "false"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_message_store.py -v`
Expected: FAIL (lib.message_store doesn't exist)

- [ ] **Step 3: Implement lib/message_store.py**

```python
# lib/message_store.py
"""Message storage layer built on org-workspace.

All message CRUD operations go through this module.
Handles message creation, querying, state transitions,
threading, and file delivery notifications.

Message IDs are timestamp-unique (not content-addressed):
format is msg-YYYYMMDD-HHMMSS-{hash[:8]} where hash includes
microseconds to minimize collision risk within the same second.
"""

import hashlib
import os
from datetime import datetime
from pathlib import Path

from org_workspace import OrgWorkspace, StateConfig, NodeView
from org_workspace.concurrency import FileLock


_TODO_HEADER = "#+TODO: TODO WAITING QUEUED WORKING | DONE CANCELLED ARCHIVED\n"

# Messages use a simpler state machine than tasks:
# TODO (unread) -> DONE (read) -> ARCHIVED
_MSG_STATE_CONFIG = StateConfig(
    active=["TODO", "WAITING"],
    terminal=["DONE", "CANCELLED", "ARCHIVED"],
)


def _unique_msg_id(from_actor: str, to_actor: str, content: str) -> str:
    """Generate a timestamp-unique message ID.

    NOT content-addressed — includes microseconds for uniqueness.
    Two identical messages sent in rapid succession get different IDs.
    """
    now = datetime.now()
    ts = now.strftime("%Y%m%d-%H%M%S")
    raw = f"{from_actor}:{to_actor}:{content}:{now.isoformat()}"
    h = hashlib.sha256(raw.encode()).hexdigest()[:8]
    return f"msg-{ts}-{h}"


def _unique_file_id(from_actor: str, filename: str) -> str:
    """Generate a timestamp-unique file delivery ID."""
    now = datetime.now()
    ts = now.strftime("%Y%m%d-%H%M%S")
    raw = f"{from_actor}:{filename}:{now.isoformat()}"
    h = hashlib.sha256(raw.encode()).hexdigest()[:8]
    return f"file-{ts}-{h}"


class MessageStore:
    """org-workspace backed message storage."""

    def __init__(
        self,
        space_root: Path,
        state_config: StateConfig | None = None,
    ):
        self._root = Path(space_root)
        self._msg_dir = self._root / "org" / "messaging"
        self._agents_dir = self._msg_dir / "agents"
        self._inbox_path = self._msg_dir / "inbox.org"
        self._outbox_path = self._msg_dir / "outbox.org"

        self._ws = OrgWorkspace(state_config=state_config or _MSG_STATE_CONFIG)
        self._ensure_files()
        self._ws.load(self._inbox_path)

    def _ensure_files(self) -> None:
        """Create messaging directories and files if missing (atomic)."""
        self._msg_dir.mkdir(parents=True, exist_ok=True)
        self._agents_dir.mkdir(exist_ok=True)
        for p in (self._inbox_path, self._outbox_path):
            try:
                fd = os.open(str(p), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, _TODO_HEADER.encode())
                os.close(fd)
            except FileExistsError:
                pass  # Already exists — no race

    def create_message(
        self,
        from_actor: str,
        to_actor: str,
        content: str,
        reply_to: str | None = None,
        priority: str | None = None,
        **extra_props: str,
    ) -> NodeView:
        """Create a new message in the inbox."""
        msg_id = _unique_msg_id(from_actor, to_actor, content)
        now_str = datetime.now().strftime("[%Y-%m-%d %a %H:%M]")
        heading = f"{now_str}"

        props = {
            "FROM": from_actor,
            "TO": to_actor,
            **extra_props,
        }
        if reply_to:
            props["REPLY_TO"] = reply_to
            # Thread ID = the root message of the thread.
            # For nested replies, look up the parent's THREAD property.
            # If the parent has no THREAD, it IS the root.
            parent = self._ws.find_by_id(reply_to)
            if parent and parent.properties.get("THREAD"):
                props["THREAD"] = parent.properties["THREAD"]
            else:
                props["THREAD"] = reply_to
        if priority:
            props["PRIORITY"] = priority

        with FileLock(self._inbox_path):
            node = self._ws.create_node(
                file=self._inbox_path,
                heading=heading,
                state="TODO",
                tags=["unread", "message"],
                body=content,
                ID=msg_id,
                **props,
            )
            self._ws.save(self._inbox_path)

        return node

    def create_file_delivery(
        self,
        from_actor: str,
        filename: str,
        size: int,
        content_type: str,
        swarm_ref: str,
        fairdrop_ref: str = "",
    ) -> NodeView:
        """Create a file delivery notification in the inbox."""
        file_id = _unique_file_id(from_actor, filename)
        now_str = datetime.now().strftime("[%Y-%m-%d %a %H:%M]")
        heading = f"{now_str}"

        with FileLock(self._inbox_path):
            node = self._ws.create_node(
                file=self._inbox_path,
                heading=heading,
                state="TODO",
                tags=["unread", "file_delivery"],
                body=f"File delivery via Fairdrop. Download to process.",
                ID=file_id,
                FROM=from_actor,
                FILENAME=filename,
                SIZE=str(size),
                CONTENT_TYPE=content_type,
                SWARM_REF=swarm_ref,
                FAIRDROP_REF=fairdrop_ref,
                DOWNLOADED="false",
            )
            self._ws.save(self._inbox_path)

        return node

    def find_unread(self) -> list[NodeView]:
        """Find all unread messages."""
        self._ws.reload(self._inbox_path)
        return [n for n in self._ws.find_by_tag("unread") if n.todo == "TODO"]

    def find_messages(self) -> list[NodeView]:
        """Find all message nodes (any state)."""
        self._ws.reload(self._inbox_path)
        return [n for n in self._ws.find_by_tag("message")]

    def find_file_deliveries(self, unread_only: bool = True) -> list[NodeView]:
        """Find file delivery notifications."""
        self._ws.reload(self._inbox_path)
        nodes = self._ws.find_by_tag("file_delivery")
        if unread_only:
            nodes = [n for n in nodes if "unread" in n.shallow_tags]
        return nodes

    def find_thread(self, thread_root_id: str) -> list[NodeView]:
        """Find all messages in a thread (by root message ID).

        The THREAD property on each reply stores the root message's full ID.
        """
        self._ws.reload(self._inbox_path)
        return [
            n
            for n in self._ws.all_nodes()
            if n.properties.get("THREAD") == thread_root_id
        ]

    def find_by_id(self, msg_id: str) -> NodeView | None:
        """Find a message by its ID."""
        return self._ws.find_by_id(msg_id)

    def mark_read(self, node: NodeView) -> None:
        """Mark message as read (TODO -> DONE)."""
        with FileLock(self._inbox_path):
            tags = list(node.shallow_tags - {"unread"})
            self._ws.set_tags(node, tags)
            self._ws.transition(node, "DONE")
            self._ws.save(self._inbox_path)

    def archive(self, node: NodeView) -> None:
        """Archive a message (DONE -> ARCHIVED)."""
        with FileLock(self._inbox_path):
            self._ws.transition(node, "ARCHIVED")
            self._ws.save(self._inbox_path)

    @property
    def workspace(self) -> OrgWorkspace:
        """Access underlying workspace (for advanced queries)."""
        return self._ws
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_message_store.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add lib/message_store.py tests/test_message_store.py
git commit -m "feat: add message store — org-workspace backed message CRUD with FileLock"
```

---

### Task 4: Implement agent inbox store

**Files:**
- Create: `lib/agent_inbox.py`
- Create: `tests/test_agent_inbox.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_agent_inbox.py
from pathlib import Path

import pytest
from org_workspace import StateConfig


@pytest.fixture
def agent_store(tmp_space, task_state_config):
    from lib.agent_inbox import AgentInbox

    return AgentInbox(
        space_root=tmp_space,
        agent_name="test-claude",
        state_config=task_state_config,
    )


class TestTaskCreation:
    def test_create_task_auto_accept(self, agent_store):
        node = agent_store.create_task(
            from_actor="owner@example.com",
            content="Research competitors",
            trust_tier="owner",
            tags=["AI", "research"],
        )
        assert node.todo == "QUEUED"
        assert node.properties["FROM"] == "owner@example.com"
        assert node.properties["TRUST_TIER"] == "owner"
        assert node.properties["APPROVAL"] == "auto_accepted"

    def test_create_task_needs_approval(self, agent_store):
        node = agent_store.create_task(
            from_actor="unknown@example.com",
            content="Do something",
            trust_tier="unknown",
            tags=["AI"],
        )
        assert node.todo == "WAITING"
        assert node.properties["AWAITING"] == "owner-approval"

    def test_create_task_team_auto_accepts(self, agent_store):
        node = agent_store.create_task(
            from_actor="tex@team.com",
            content="Draft report",
            trust_tier="team",
            tags=["AI", "content"],
        )
        assert node.todo == "QUEUED"


class TestTaskLifecycle:
    def test_approve_task(self, agent_store):
        node = agent_store.create_task(
            "unknown@x.com", "task", "unknown", ["AI"]
        )
        assert node.todo == "WAITING"
        agent_store.approve(node)
        assert node.todo == "QUEUED"

    def test_reject_task(self, agent_store):
        node = agent_store.create_task(
            "unknown@x.com", "task", "unknown", ["AI"]
        )
        agent_store.reject(node, reason="Not relevant")
        assert node.todo == "CANCELLED"

    def test_claim_and_complete(self, agent_store):
        node = agent_store.create_task(
            "owner@x.com", "task", "owner", ["AI"]
        )
        agent_store.claim(node)
        assert node.todo == "WORKING"
        assert node.properties.get("STARTED")

        agent_store.complete(
            node,
            tokens_used=5000,
            cost="$0.08",
            result_path="0-inbox/result.md",
            quality_score=0.85,
        )
        assert node.todo == "DONE"
        assert node.properties["TOKENS_USED"] == "5000"
        assert node.properties["QUALITY_SCORE"] == "0.85"

    def test_request_revision(self, agent_store):
        node = agent_store.create_task(
            "owner@x.com", "task", "owner", ["AI"]
        )
        agent_store.claim(node)
        agent_store.complete(node, tokens_used=100)
        agent_store.request_revision(node, feedback="Needs more detail")
        assert node.todo == "QUEUED"

    def test_cancel_queued_task(self, agent_store):
        node = agent_store.create_task(
            "owner@x.com", "task", "owner", ["AI"]
        )
        assert node.todo == "QUEUED"
        agent_store.cancel(node, reason="No longer needed")
        assert node.todo == "CANCELLED"
        assert node.properties["CANCELLATION_REASON"] == "No longer needed"

    def test_retry_failed_task(self, agent_store):
        node = agent_store.create_task(
            "owner@x.com", "task", "owner", ["AI"]
        )
        agent_store.claim(node)
        assert node.todo == "WORKING"
        agent_store.retry(node, reason="Agent crashed")
        assert node.todo == "QUEUED"
        assert node.properties["RETRY_REASON"] == "Agent crashed"
        assert int(node.properties.get("RETRY_COUNT", "0")) == 1

    def test_precondition_reject_on_queued_raises(self, agent_store):
        node = agent_store.create_task(
            "owner@x.com", "task", "owner", ["AI"]
        )
        assert node.todo == "QUEUED"
        with pytest.raises(ValueError, match="Expected state WAITING"):
            agent_store.reject(node)

    def test_precondition_claim_on_waiting_raises(self, agent_store):
        node = agent_store.create_task(
            "unknown@x.com", "task", "unknown", ["AI"]
        )
        assert node.todo == "WAITING"
        with pytest.raises(ValueError, match="Expected state QUEUED"):
            agent_store.claim(node)


class TestQueries:
    def test_find_queued(self, agent_store):
        agent_store.create_task("a@x.com", "t1", "owner", ["AI"])
        agent_store.create_task("a@x.com", "t2", "owner", ["AI"])
        queued = agent_store.find_by_state("QUEUED")
        assert len(queued) == 2

    def test_find_waiting_approval(self, agent_store):
        agent_store.create_task("a@x.com", "t1", "unknown", ["AI"])
        agent_store.create_task("b@x.com", "t2", "trusted", ["AI"])
        waiting = agent_store.find_awaiting_approval()
        assert len(waiting) == 2

    def test_counts(self, agent_store):
        agent_store.create_task("a@x.com", "t1", "owner", ["AI"])
        agent_store.create_task("b@x.com", "t2", "unknown", ["AI"])
        counts = agent_store.counts()
        assert counts["queued"] == 1
        assert counts["waiting"] == 1
        assert counts["total"] == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_agent_inbox.py -v`
Expected: FAIL

- [ ] **Step 3: Implement lib/agent_inbox.py**

```python
# lib/agent_inbox.py
"""Agent inbox — per-agent task store with lifecycle management.

State machine (DIP-0023 Section 5.2):
  WAITING  -> QUEUED     (owner approves)
  WAITING  -> CANCELLED  (owner rejects)
  QUEUED   -> WORKING    (agent claims)
  QUEUED   -> CANCELLED  (owner cancels)
  WORKING  -> DONE       (execution complete)
  WORKING  -> QUEUED     (retry on failure)
  DONE     -> ARCHIVED   (owner approves result)
  DONE     -> QUEUED     (owner requests revision)

IMPORTANT: DONE is NOT terminal for tasks — it's an active state that
allows revision. Only CANCELLED and ARCHIVED are terminal. This differs
from message_store.py where DONE IS terminal for simple messages.
"""

import os
from datetime import datetime
from pathlib import Path

from org_workspace import OrgWorkspace, StateConfig, NodeView
from org_workspace.concurrency import FileLock

from lib.config import get_trust_tier_config


_TODO_HEADER = "#+TODO: TODO WAITING QUEUED WORKING | DONE CANCELLED ARCHIVED\n"

# Task StateConfig: DONE is active (allows DONE -> QUEUED revision)
_TASK_STATE_CONFIG = StateConfig(
    active=["TODO", "WAITING", "QUEUED", "WORKING", "DONE"],
    terminal=["CANCELLED", "ARCHIVED"],
)


def _should_auto_accept(trust_tier: str) -> bool:
    """Check if a trust tier auto-accepts tasks. Single source of truth."""
    tier_config = get_trust_tier_config(trust_tier)
    return tier_config.get("auto_accept", False)


def _assert_state(node: NodeView, expected: str, method: str) -> None:
    """Precondition assertion for state transitions."""
    if node.todo != expected:
        raise ValueError(
            f"{method}: Expected state {expected}, got {node.todo}"
        )


class AgentInbox:
    """Manages tasks for a single agent."""

    def __init__(
        self,
        space_root: Path,
        agent_name: str,
        state_config: StateConfig | None = None,
    ):
        self._root = Path(space_root)
        self._name = agent_name
        self._inbox_path = (
            self._root / "org" / "messaging" / "agents" / f"{agent_name}.org"
        )

        self._ws = OrgWorkspace(state_config=state_config or _TASK_STATE_CONFIG)
        self._ensure_file()
        self._ws.load(self._inbox_path)

    def _ensure_file(self) -> None:
        """Create agent inbox file if missing (atomic)."""
        self._inbox_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(str(self._inbox_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, _TODO_HEADER.encode())
            os.close(fd)
        except FileExistsError:
            pass

    def _reload(self) -> None:
        self._ws.reload(self._inbox_path)

    def create_task(
        self,
        from_actor: str,
        content: str,
        trust_tier: str,
        tags: list[str],
        effort: int | None = None,
        estimated_tokens: int | None = None,
    ) -> NodeView:
        """Create a task in the agent inbox.

        Auto-accept is determined by trust tier config (from config.py).
        """
        auto_accept = _should_auto_accept(trust_tier)
        state = "QUEUED" if auto_accept else "WAITING"
        now_str = datetime.now().strftime("[%Y-%m-%d %a %H:%M]")

        props = {
            "FROM": from_actor,
            "TRUST_TIER": trust_tier,
            "SUBMITTED": now_str,
        }
        if auto_accept:
            props["APPROVAL"] = "auto_accepted"
        else:
            props["AWAITING"] = "owner-approval"
        if effort is not None:
            props["EFFORT"] = str(effort)
        if estimated_tokens is not None:
            props["ESTIMATED_TOKENS"] = str(estimated_tokens)
            cost = estimated_tokens / 1000 * 0.015
            props["ESTIMATED_COST"] = f"${cost:.2f}"

        with FileLock(self._inbox_path):
            node = self._ws.create_node(
                file=self._inbox_path,
                heading=content,
                state=state,
                tags=tags,
                body="",
                **props,
            )
            self._ws.save(self._inbox_path)

        return node

    def approve(self, node: NodeView) -> None:
        """Approve a WAITING task -> QUEUED."""
        _assert_state(node, "WAITING", "approve")
        with FileLock(self._inbox_path):
            self._ws.set_property(node, "APPROVAL", "owner_approved")
            self._ws.transition(node, "QUEUED")
            self._ws.save(self._inbox_path)

    def reject(self, node: NodeView, reason: str = "") -> None:
        """Reject a WAITING task -> CANCELLED."""
        _assert_state(node, "WAITING", "reject")
        with FileLock(self._inbox_path):
            if reason:
                self._ws.set_property(node, "REJECTION_REASON", reason)
            self._ws.transition(node, "CANCELLED")
            self._ws.save(self._inbox_path)

    def cancel(self, node: NodeView, reason: str = "") -> None:
        """Cancel a QUEUED task -> CANCELLED."""
        _assert_state(node, "QUEUED", "cancel")
        with FileLock(self._inbox_path):
            if reason:
                self._ws.set_property(node, "CANCELLATION_REASON", reason)
            self._ws.transition(node, "CANCELLED")
            self._ws.save(self._inbox_path)

    def claim(self, node: NodeView) -> None:
        """Claim a QUEUED task -> WORKING."""
        _assert_state(node, "QUEUED", "claim")
        now_str = datetime.now().strftime("[%Y-%m-%d %a %H:%M]")
        with FileLock(self._inbox_path):
            self._ws.set_property(node, "STARTED", now_str)
            self._ws.transition(node, "WORKING")
            self._ws.save(self._inbox_path)

    def complete(
        self,
        node: NodeView,
        tokens_used: int = 0,
        cost: str = "",
        result_path: str = "",
        quality_score: float | None = None,
    ) -> None:
        """Complete a WORKING task -> DONE."""
        _assert_state(node, "WORKING", "complete")
        now_str = datetime.now().strftime("[%Y-%m-%d %a %H:%M]")
        with FileLock(self._inbox_path):
            self._ws.set_property(node, "COMPLETED", now_str)
            if tokens_used:
                self._ws.set_property(node, "TOKENS_USED", str(tokens_used))
            if cost:
                self._ws.set_property(node, "COST", cost)
            if result_path:
                self._ws.set_property(node, "RESULT_PATH", result_path)
            if quality_score is not None:
                self._ws.set_property(
                    node, "QUALITY_SCORE", f"{quality_score:.2f}"
                )
            self._ws.transition(node, "DONE")
            self._ws.save(self._inbox_path)

    def retry(self, node: NodeView, reason: str = "") -> None:
        """Return a WORKING task -> QUEUED after failure."""
        _assert_state(node, "WORKING", "retry")
        retry_count = int(node.properties.get("RETRY_COUNT", "0")) + 1
        with FileLock(self._inbox_path):
            self._ws.set_property(node, "RETRY_COUNT", str(retry_count))
            if reason:
                self._ws.set_property(node, "RETRY_REASON", reason)
            self._ws.transition(node, "QUEUED")
            self._ws.save(self._inbox_path)

    def request_revision(self, node: NodeView, feedback: str = "") -> None:
        """Return a DONE task -> QUEUED for revision.

        This works because DONE is an active state in task_state_config.
        """
        _assert_state(node, "DONE", "request_revision")
        with FileLock(self._inbox_path):
            if feedback:
                self._ws.set_property(node, "REVISION_FEEDBACK", feedback)
            self._ws.transition(node, "QUEUED")
            self._ws.save(self._inbox_path)

    def find_by_state(self, *states: str) -> list[NodeView]:
        """Find tasks by state."""
        self._reload()
        return self._ws.find_by_state(*states)

    def find_awaiting_approval(self) -> list[NodeView]:
        """Find tasks awaiting owner approval."""
        self._reload()
        return [
            n
            for n in self._ws.find_by_state("WAITING")
            if n.properties.get("AWAITING") == "owner-approval"
        ]

    def counts(self) -> dict[str, int]:
        """Get task counts by state."""
        self._reload()
        all_nodes = list(self._ws.all_nodes())
        # Skip root node (the file itself)
        nodes = [n for n in all_nodes if n.level > 0]
        result = {
            "queued": sum(1 for n in nodes if n.todo == "QUEUED"),
            "working": sum(1 for n in nodes if n.todo == "WORKING"),
            "done": sum(1 for n in nodes if n.todo == "DONE"),
            "waiting": sum(1 for n in nodes if n.todo == "WAITING"),
            "cancelled": sum(1 for n in nodes if n.todo == "CANCELLED"),
            "total": len(nodes),
        }
        return result

    @property
    def workspace(self) -> OrgWorkspace:
        return self._ws
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_agent_inbox.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add lib/agent_inbox.py tests/test_agent_inbox.py
git commit -m "feat: add agent inbox — per-agent task store with state machine lifecycle"
```

---

## Chunk 3: Task Governor

### Task 5: Implement task governor (trust, budgets, rate limits)

**Files:**
- Create: `lib/governor.py`
- Create: `tests/test_governor.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_governor.py
import json
import time
from datetime import datetime
from pathlib import Path

import pytest


@pytest.fixture
def gov(tmp_path, monkeypatch):
    from lib.governor import TaskGovernor

    monkeypatch.setenv("DATACORE_ROOT", str(tmp_path))
    state_dir = tmp_path / ".datacore" / "state" / "messaging"
    state_dir.mkdir(parents=True)
    return TaskGovernor(state_dir=state_dir)


class TestTrustTierResolution:
    def test_unknown_actor_gets_unknown_tier(self, gov):
        result = gov.check_task("random@example.com", estimated_tokens=1000)
        assert result.trust_tier == "unknown"
        assert result.auto_accept is False

    def test_budget_check_within_limit(self, gov):
        result = gov.check_task("user@x.com", estimated_tokens=5000)
        assert result.allowed is True

    def test_budget_check_exceeds_per_sender(self, gov):
        # Unknown tier has 10_000 daily limit
        for i in range(3):
            gov.record_usage("spammer@x.com", tokens=4000)
        result = gov.check_task("spammer@x.com", estimated_tokens=4000)
        assert result.allowed is False
        assert "budget" in result.reason.lower()


class TestRateLimiting:
    def test_tasks_per_hour_limit(self, gov):
        # Unknown tier gets 5 tasks/hour default
        for i in range(5):
            gov.record_task_submission("spammer@x.com")
        result = gov.check_task("spammer@x.com", estimated_tokens=100)
        assert result.allowed is False
        assert "rate" in result.reason.lower()


class TestBudgetTracking:
    def test_record_and_query_usage(self, gov):
        gov.record_usage("user@x.com", tokens=5000)
        gov.record_usage("user@x.com", tokens=3000)
        usage = gov.get_usage("user@x.com")
        assert usage["tokens_today"] == 8000

    def test_usage_persists_to_file(self, gov):
        gov.record_usage("user@x.com", tokens=5000)
        # Create new governor instance (simulates restart)
        from lib.governor import TaskGovernor

        gov2 = TaskGovernor(state_dir=gov._state_dir)
        usage = gov2.get_usage("user@x.com")
        assert usage["tokens_today"] == 5000

    def test_daily_budget_summary(self, gov):
        gov.record_usage("a@x.com", tokens=5000)
        gov.record_usage("b@x.com", tokens=3000)
        summary = gov.daily_summary()
        assert summary["total_tokens"] == 8000
        assert len(summary["by_sender"]) == 2


class TestEffortCheck:
    def test_effort_within_tier_limit(self, gov):
        # Unknown tier max_task_effort = 3
        result = gov.check_task(
            "unknown@x.com", estimated_tokens=100, effort=3
        )
        assert result.allowed is True

    def test_effort_exceeds_tier_limit(self, gov):
        result = gov.check_task(
            "unknown@x.com", estimated_tokens=100, effort=5
        )
        assert result.allowed is False
        assert "effort" in result.reason.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_governor.py -v`
Expected: FAIL

- [ ] **Step 3: Implement lib/governor.py**

```python
# lib/governor.py
"""Task governance — trust tiers, compute budgets, rate limits.

Controls what work Claude agents accept and at what cost.
Per DIP-0023 Section 7.
"""

import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from org_workspace.concurrency import FileLock

from lib.config import (
    get_trust_tier,
    get_trust_tier_config,
    get_compute_config,
)


@dataclass
class TaskCheckResult:
    """Result of a task governance check."""

    allowed: bool
    trust_tier: str
    auto_accept: bool
    reason: str = ""
    priority_boost: float = 1.0


@dataclass
class _SenderState:
    tokens_today: int = 0
    tasks_this_hour: list[float] = field(default_factory=list)
    tasks_today: int = 0
    active_tasks: int = 0  # Currently QUEUED or WORKING (not completed)


class TaskGovernor:
    """Enforces trust tiers, budgets, and rate limits."""

    def __init__(self, state_dir: Path | None = None):
        self._state_dir = state_dir or Path(".datacore/state/messaging")
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._today = datetime.now().strftime("%Y-%m-%d")
        self._budget_file = self._state_dir / f"budget-{self._today}.json"
        self._state: dict[str, _SenderState] = {}
        self._load_state()

    def _load_state(self) -> None:
        with FileLock(self._budget_file):
            if self._budget_file.exists():
                try:
                    data = json.loads(self._budget_file.read_text())
                    for sender, info in data.get("senders", {}).items():
                        self._state[sender] = _SenderState(
                            tokens_today=info.get("tokens_today", 0),
                            tasks_this_hour=info.get("tasks_this_hour", []),
                            tasks_today=info.get("tasks_today", 0),
                            active_tasks=info.get("active_tasks", 0),
                        )
                except (json.JSONDecodeError, KeyError):
                    pass

    def _save_state(self) -> None:
        now = time.time()
        hour_ago = now - 3600
        data = {
            "date": self._today,
            "senders": {},
        }
        for sender, state in self._state.items():
            # Prune stale rate-limit entries on save
            state.tasks_this_hour = [t for t in state.tasks_this_hour if t > hour_ago]
            data["senders"][sender] = {
                "tokens_today": state.tokens_today,
                "tasks_this_hour": state.tasks_this_hour,
                "tasks_today": state.tasks_today,
                "active_tasks": state.active_tasks,
            }
        with FileLock(self._budget_file):
            self._budget_file.write_text(json.dumps(data, indent=2))

    def _check_date_rollover(self) -> None:
        """Reset state if day has changed (for long-lived processes)."""
        today = datetime.now().strftime("%Y-%m-%d")
        if today != self._today:
            self._today = today
            self._budget_file = self._state_dir / f"budget-{today}.json"
            self._state = {}
            self._load_state()

    def _get_sender(self, actor_id: str) -> _SenderState:
        if actor_id not in self._state:
            self._state[actor_id] = _SenderState()
        return self._state[actor_id]

    def check_task(
        self,
        actor_id: str,
        estimated_tokens: int = 0,
        effort: int = 0,
    ) -> TaskCheckResult:
        """Check if a task from this actor should be accepted."""
        self._check_date_rollover()
        tier_name = get_trust_tier(actor_id)
        tier_config = get_trust_tier_config(tier_name)
        compute = get_compute_config()
        sender = self._get_sender(actor_id)

        auto_accept = tier_config.get("auto_accept", False)
        boost = tier_config.get("priority_boost", 1.0)

        # Check effort limit
        max_effort = tier_config.get("max_task_effort", 0)
        if max_effort > 0 and effort > max_effort:
            return TaskCheckResult(
                allowed=False,
                trust_tier=tier_name,
                auto_accept=auto_accept,
                reason=f"Effort {effort} exceeds tier limit {max_effort}",
                priority_boost=boost,
            )

        # Check per-sender daily token budget
        daily_limit = tier_config.get("daily_token_limit", 0)
        if daily_limit > 0:
            if sender.tokens_today + estimated_tokens > daily_limit:
                return TaskCheckResult(
                    allowed=False,
                    trust_tier=tier_name,
                    auto_accept=auto_accept,
                    reason=f"Budget exceeded: {sender.tokens_today}/{daily_limit} tokens today",
                    priority_boost=boost,
                )

        # Check global daily budget
        global_limit = compute.get("daily_budget_tokens", 0)
        if global_limit > 0:
            total = sum(s.tokens_today for s in self._state.values())
            if total + estimated_tokens > global_limit:
                return TaskCheckResult(
                    allowed=False,
                    trust_tier=tier_name,
                    auto_accept=auto_accept,
                    reason="Global daily budget exceeded",
                    priority_boost=boost,
                )

        # Check rate limit (tasks per hour)
        now = time.time()
        hour_ago = now - 3600
        recent = [t for t in sender.tasks_this_hour if t > hour_ago]
        rate_limits = compute.get("rate_limits", {})
        tasks_per_hour = rate_limits.get("tasks_per_hour", 5)
        if len(recent) >= tasks_per_hour:
            return TaskCheckResult(
                allowed=False,
                trust_tier=tier_name,
                auto_accept=auto_accept,
                reason=f"Rate limit: {len(recent)}/{tasks_per_hour} tasks this hour",
                priority_boost=boost,
            )

        # Check queue depth (active tasks only, not total submissions)
        max_queue = compute.get("max_queue_depth", 20)
        active_tasks = sum(s.active_tasks for s in self._state.values())
        if active_tasks >= max_queue:
            return TaskCheckResult(
                allowed=False,
                trust_tier=tier_name,
                auto_accept=auto_accept,
                reason=f"Queue full: {active_tasks}/{max_queue}",
                priority_boost=boost,
            )

        return TaskCheckResult(
            allowed=True,
            trust_tier=tier_name,
            auto_accept=auto_accept,
            priority_boost=boost,
        )

    def check_and_record(
        self,
        actor_id: str,
        estimated_tokens: int = 0,
        effort: int = 0,
    ) -> TaskCheckResult:
        """Check + record under a single lock — eliminates TOCTOU.

        If the check passes, immediately records the submission.
        Both operations run within the same FileLock scope.
        Uses _write_state (no lock) since we already hold the lock.
        """
        with FileLock(self._budget_file):
            # Reload fresh state under lock
            if self._budget_file.exists():
                try:
                    data = json.loads(self._budget_file.read_text())
                    for sender, info in data.get("senders", {}).items():
                        self._state[sender] = _SenderState(
                            tokens_today=info.get("tokens_today", 0),
                            tasks_this_hour=info.get("tasks_this_hour", []),
                            tasks_today=info.get("tasks_today", 0),
                            active_tasks=info.get("active_tasks", 0),
                        )
                except (json.JSONDecodeError, KeyError):
                    pass

            result = self.check_task(actor_id, estimated_tokens, effort)
            if result.allowed:
                sender = self._get_sender(actor_id)
                sender.tasks_this_hour.append(time.time())
                sender.tasks_today += 1
                sender.active_tasks += 1
                # Write state directly (no nested FileLock)
                now = time.time()
                hour_ago = now - 3600
                out = {"date": self._today, "senders": {}}
                for s_id, s in self._state.items():
                    s.tasks_this_hour = [t for t in s.tasks_this_hour if t > hour_ago]
                    out["senders"][s_id] = {
                        "tokens_today": s.tokens_today,
                        "tasks_this_hour": s.tasks_this_hour,
                        "tasks_today": s.tasks_today,
                        "active_tasks": s.active_tasks,
                    }
                self._budget_file.write_text(json.dumps(out, indent=2))
        return result

    def record_usage(self, actor_id: str, tokens: int) -> None:
        """Record token usage for a sender."""
        self._check_date_rollover()
        sender = self._get_sender(actor_id)
        sender.tokens_today += tokens
        self._save_state()

    def record_task_submission(self, actor_id: str) -> None:
        """Record a task submission (for rate limiting)."""
        sender = self._get_sender(actor_id)
        sender.tasks_this_hour.append(time.time())
        sender.tasks_today += 1
        sender.active_tasks += 1
        self._save_state()

    def record_task_completion(self, actor_id: str) -> None:
        """Record a task completion (decrements active count)."""
        sender = self._get_sender(actor_id)
        sender.active_tasks = max(0, sender.active_tasks - 1)
        self._save_state()

    def get_usage(self, actor_id: str) -> dict:
        """Get usage stats for a sender."""
        sender = self._get_sender(actor_id)
        return {
            "tokens_today": sender.tokens_today,
            "tasks_today": sender.tasks_today,
        }

    def daily_summary(self) -> dict:
        """Get daily budget summary across all senders."""
        total_tokens = sum(s.tokens_today for s in self._state.values())
        by_sender = {
            actor: {"tokens": s.tokens_today, "tasks": s.tasks_today}
            for actor, s in self._state.items()
        }
        return {
            "date": self._today,
            "total_tokens": total_tokens,
            "by_sender": by_sender,
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_governor.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add lib/governor.py tests/test_governor.py
git commit -m "feat: add task governor — trust tiers, per-sender budgets, rate limiting"
```

---

## Chunk 4: Relay Consolidation and Bug Fixes

### Task 6: Consolidate relay to single file and fix critical bugs

**Files:**
- Create: `lib/relay.py` (consolidated from 3 sources)
- Delete: `lib/datacore-msg-relay.py`
- Delete: `relay/datacore-msg-relay.py`
- Modify: `relay/Dockerfile`
- Create: `tests/test_relay.py`

- [ ] **Step 1: Write failing tests for relay fixes**

```python
# tests/test_relay.py
import json

import pytest
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop


@pytest.fixture
def relay_app():
    from lib.relay import create_relay_app

    return create_relay_app(relay_secret="test-secret-123")


class TestRelayAuth:
    @pytest.mark.asyncio
    async def test_status_requires_no_user_list(self, relay_app, aiohttp_client):
        """Status endpoint must NOT leak connected usernames."""
        client = await aiohttp_client(relay_app)
        resp = await client.get("/status")
        data = await resp.json()
        assert resp.status == 200
        assert "users" not in data
        assert "users_online" not in data
        assert data["status"] == "ok"

    @pytest.mark.asyncio
    async def test_status_shows_count_only(self, relay_app, aiohttp_client):
        client = await aiohttp_client(relay_app)
        resp = await client.get("/status")
        data = await resp.json()
        assert "connected" in data
        assert isinstance(data["connected"], int)


class TestRelayStartup:
    def test_relay_refuses_empty_secret(self):
        from lib.relay import create_relay_app

        with pytest.raises(ValueError, match="RELAY_SECRET"):
            create_relay_app(relay_secret="")

    def test_relay_accepts_valid_secret(self):
        from lib.relay import create_relay_app

        app = create_relay_app(relay_secret="valid-secret")
        assert app is not None


class TestArgParsing:
    def test_host_flag_not_h(self):
        """Verify -h is NOT used for hosting (it's --help)."""
        from lib.relay import parse_relay_args

        # --host should work
        args = parse_relay_args(["--host"])
        assert args.host is True

        # -h should trigger help, not hosting
        with pytest.raises(SystemExit):
            parse_relay_args(["-h"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_relay.py -v`
Expected: FAIL

- [ ] **Step 3: Implement lib/relay.py (consolidated)**

```python
# lib/relay.py
"""WebSocket relay server — single consolidated implementation.

Replaces the three duplicate relay files (lib/, relay/, embedded in GUI).
Fixes: auth leak on /status, -h flag collision, empty secret startup.
"""

import argparse
import json
import logging
import os
import time
from dataclasses import dataclass, field

from aiohttp import web, WSMsgType

logger = logging.getLogger(__name__)


@dataclass
class User:
    username: str
    ws: web.WebSocketResponse
    connected_at: float = field(default_factory=time.time)
    status: str = "online"


class RelayServer:
    def __init__(self, secret: str, claude_whitelist: dict | None = None):
        self.secret = secret
        self.users: dict[str, User] = {}
        self.claude_whitelist = claude_whitelist or {}

    def add_user(self, username: str, ws: web.WebSocketResponse) -> None:
        self.users[username] = User(username=username, ws=ws)

    def remove_user(self, username: str) -> None:
        self.users.pop(username, None)

    def list_users(self) -> list[str]:
        return list(self.users.keys())

    def connected_count(self) -> int:
        return len(self.users)

    async def route_message(self, msg: dict, sender: str) -> bool:
        target = msg.get("to", "")
        if not target or target not in self.users:
            return False
        try:
            await self.users[target].ws.send_json(msg)
            return True
        except Exception:
            logger.warning("Failed to deliver message to %s", target)
            return False

    async def broadcast_presence(self, username: str, status: str) -> None:
        event = {
            "type": "presence",
            "username": username,
            "status": status,
        }
        for user in self.users.values():
            if user.username != username:
                try:
                    await user.ws.send_json(event)
                except Exception:
                    pass


def create_relay_app(relay_secret: str) -> web.Application:
    """Create the aiohttp relay application.

    Raises ValueError if relay_secret is empty.
    """
    if not relay_secret:
        raise ValueError(
            "RELAY_SECRET must be set. "
            "Generate one with: python -c 'import secrets; print(secrets.token_hex(32))'"
        )

    relay = RelayServer(secret=relay_secret)
    app = web.Application()
    app["relay"] = relay

    async def handle_status(request: web.Request) -> web.Response:
        """Status endpoint — shows connected count only, never usernames."""
        return web.json_response(
            {"status": "ok", "connected": relay.connected_count()}
        )

    async def handle_ws(request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        username = None

        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                    except json.JSONDecodeError:
                        continue

                    msg_type = data.get("type")

                    if msg_type == "auth":
                        if data.get("secret") != relay.secret:
                            await ws.send_json(
                                {"type": "error", "message": "Invalid secret"}
                            )
                            await ws.close()
                            return ws
                        username = data.get("username", "")
                        if not username:
                            await ws.send_json(
                                {"type": "error", "message": "Username required"}
                            )
                            await ws.close()
                            return ws
                        relay.add_user(username, ws)
                        await ws.send_json({"type": "auth_ok"})
                        await relay.broadcast_presence(username, "online")
                        logger.info("User connected: %s", username)

                    elif msg_type == "send" and username:
                        payload = {
                            "type": "message",
                            "from": username,
                            "to": data.get("to"),
                            "content": data.get("content", ""),
                            "id": data.get("id", ""),
                            "thread": data.get("thread"),
                            "reply_to": data.get("reply_to"),
                            "timestamp": data.get(
                                "timestamp", time.strftime("%Y-%m-%dT%H:%M:%S")
                            ),
                        }
                        delivered = await relay.route_message(payload, username)
                        if not delivered:
                            await ws.send_json(
                                {
                                    "type": "error",
                                    "message": f"User {data.get('to')} not online",
                                }
                            )

                    elif msg_type == "status_change" and username:
                        new_status = data.get("status", "online")
                        if username in relay.users:
                            relay.users[username].status = new_status
                        await relay.broadcast_presence(username, new_status)

                    elif msg_type == "ping":
                        await ws.send_json({"type": "pong"})

                elif msg.type == WSMsgType.ERROR:
                    logger.error("WS error: %s", ws.exception())
        finally:
            if username:
                relay.remove_user(username)
                await relay.broadcast_presence(username, "offline")
                logger.info("User disconnected: %s", username)

        return ws

    app.router.add_get("/status", handle_status)
    app.router.add_get("/ws", handle_ws)
    return app


def parse_relay_args(args: list[str] | None = None) -> argparse.Namespace:
    """Parse relay CLI arguments. Uses --host (not -h) for hosting."""
    parser = argparse.ArgumentParser(description="Datacore messaging relay")
    parser.add_argument("--host", action="store_true", help="Host relay server")
    parser.add_argument("--port", type=int, default=8080, help="Port (default: 8080)")
    parser.add_argument("--bind", default="0.0.0.0", help="Bind address")
    return parser.parse_args(args)


def run_relay() -> None:
    """Entry point for standalone relay server."""
    args = parse_relay_args()
    secret = os.environ.get("RELAY_SECRET", "")
    app = create_relay_app(relay_secret=secret)
    web.run_app(app, host=args.bind, port=args.port)


if __name__ == "__main__":
    run_relay()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_relay.py -v`
Expected: All tests PASS

- [ ] **Step 5: Delete duplicate relay files and update Dockerfile**

Delete `lib/datacore-msg-relay.py` and `relay/datacore-msg-relay.py`.

Update `relay/Dockerfile` to use:
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY lib/ lib/
CMD ["python", "-m", "lib.relay", "--host"]
```

Update `Procfile` to:
```
web: python -m lib.relay --host
```

- [ ] **Step 6: Commit**

```bash
git add lib/relay.py tests/test_relay.py relay/Dockerfile Procfile
git rm lib/datacore-msg-relay.py relay/datacore-msg-relay.py
git commit -m "feat: consolidate relay to single lib/relay.py — fix auth leak, -h collision, empty secret"
```

---

## Chunk 5: Rewire Hooks and Update Module Manifest

### Task 7: Rewire hooks to use lib modules

**Files:**
- Rewrite: `hooks/inbox-watcher.py`
- Rewrite: `hooks/send-reply.py`
- Rewrite: `hooks/mark-message.py`
- Rewrite: `hooks/task-queue.py`
- Create: `tests/test_hooks.py`

Each hook currently has duplicated settings/parsing code. Rewire them to import from `lib/` modules.

- [ ] **Step 1: Write failing tests for hooks**

```python
# tests/test_hooks.py
"""Tests for hooks using the new lib modules.

Hooks are tested by importing their main functions directly.
Each hook uses sys.path setup from lib/__init__.py.
"""
import sys
from pathlib import Path

import pytest

# Ensure repo root is on sys.path for hook imports
_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from lib.config import clear_settings_cache


@pytest.fixture(autouse=True)
def _fresh_config():
    clear_settings_cache()
    yield
    clear_settings_cache()


class TestInboxWatcher:
    def test_no_tasks_returns_empty(self, tmp_space, task_state_config, monkeypatch):
        monkeypatch.setenv("DATACORE_ROOT", str(tmp_space.parent))
        from lib.agent_inbox import AgentInbox

        inbox = AgentInbox(tmp_space, "test-claude", task_state_config)
        queued = inbox.find_by_state("QUEUED")
        working = inbox.find_by_state("WORKING")
        assert len(queued) == 0
        assert len(working) == 0

    def test_claims_next_queued_task(self, tmp_space, task_state_config, monkeypatch):
        monkeypatch.setenv("DATACORE_ROOT", str(tmp_space.parent))
        from lib.agent_inbox import AgentInbox

        inbox = AgentInbox(tmp_space, "test-claude", task_state_config)
        inbox.create_task("owner@x.com", "Research AI", "owner", ["AI"])
        queued = inbox.find_by_state("QUEUED")
        assert len(queued) == 1

        inbox.claim(queued[0])
        assert queued[0].todo == "WORKING"
        assert len(inbox.find_by_state("QUEUED")) == 0

    def test_skips_when_task_already_working(
        self, tmp_space, task_state_config, monkeypatch
    ):
        monkeypatch.setenv("DATACORE_ROOT", str(tmp_space.parent))
        from lib.agent_inbox import AgentInbox

        inbox = AgentInbox(tmp_space, "test-claude", task_state_config)
        t1 = inbox.create_task("owner@x.com", "Task 1", "owner", ["AI"])
        inbox.create_task("owner@x.com", "Task 2", "owner", ["AI"])
        inbox.claim(t1)

        # When one task is WORKING, watcher should not claim another
        working = inbox.find_by_state("WORKING")
        assert len(working) == 1


class TestSendReply:
    def test_creates_outgoing_message(self, tmp_space, msg_state_config, monkeypatch):
        monkeypatch.setenv("DATACORE_ROOT", str(tmp_space.parent))
        from lib.message_store import MessageStore

        store = MessageStore(tmp_space, msg_state_config)
        msg = store.create_message("gregor@x.com", "tex@x.com", "Hello!")
        assert msg.todo == "TODO"
        assert msg.properties["FROM"] == "gregor@x.com"


class TestMarkMessage:
    def test_mark_read_removes_unread(self, tmp_space, msg_state_config, monkeypatch):
        monkeypatch.setenv("DATACORE_ROOT", str(tmp_space.parent))
        from lib.message_store import MessageStore

        store = MessageStore(tmp_space, msg_state_config)
        msg = store.create_message("a@x.com", "b@x.com", "test")
        assert "unread" in msg.shallow_tags
        store.mark_read(msg)
        assert "unread" not in msg.shallow_tags
        assert msg.todo == "DONE"


class TestTaskQueue:
    def test_counts_reflect_state(self, tmp_space, task_state_config, monkeypatch):
        monkeypatch.setenv("DATACORE_ROOT", str(tmp_space.parent))
        from lib.agent_inbox import AgentInbox

        inbox = AgentInbox(tmp_space, "test-claude", task_state_config)
        inbox.create_task("owner@x.com", "T1", "owner", ["AI"])
        inbox.create_task("unknown@x.com", "T2", "unknown", ["AI"])
        counts = inbox.counts()
        assert counts["queued"] == 1
        assert counts["waiting"] == 1
        assert counts["total"] == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_hooks.py -v`
Expected: PASS (these test lib modules, which should already work)

- [ ] **Step 3: Rewrite hooks/inbox-watcher.py**

```python
#!/usr/bin/env python3
"""Inbox watcher hook — checks for queued tasks and claims the next one.

Claude Code hook: runs on prompt_submit to inject task context.
Uses lib/ modules instead of raw file parsing.
"""

import sys
from pathlib import Path

# Ensure lib/ is importable
_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from lib.config import get_username, get_default_space, datacore_root
from lib.agent_inbox import AgentInbox


def main() -> None:
    username = get_username()
    space = get_default_space()
    space_root = datacore_root() / space

    inbox = AgentInbox(space_root, f"{username}-claude")

    # Only one task at a time
    working = inbox.find_by_state("WORKING")
    if working:
        task = working[0]
        print(f"[messaging] Task in progress: {task.heading}")
        return

    queued = inbox.find_by_state("QUEUED")
    if not queued:
        return  # Nothing to do

    # Claim the oldest queued task
    task = queued[0]
    inbox.claim(task)
    print(f"[messaging] Claimed task: {task.heading}")
    print(f"  From: {task.properties.get('FROM', 'unknown')}")
    print(f"  Tier: {task.properties.get('TRUST_TIER', 'unknown')}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Rewrite hooks/send-reply.py**

```python
#!/usr/bin/env python3
"""Send reply hook — creates outgoing messages and completes agent tasks.

Uses lib/ modules instead of raw file parsing.
"""

import sys
import argparse
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from lib.config import get_username, get_default_space, datacore_root
from lib.message_store import MessageStore
from lib.agent_inbox import AgentInbox


def main() -> None:
    parser = argparse.ArgumentParser(description="Send a reply")
    parser.add_argument("to", help="Recipient actor ID")
    parser.add_argument("content", help="Message content")
    parser.add_argument("--reply-to", help="Message ID to reply to")
    parser.add_argument("--complete-task", help="Task ID to mark complete")
    parser.add_argument("--tokens", type=int, default=0, help="Tokens used")
    args = parser.parse_args()

    username = get_username()
    space = get_default_space()
    space_root = datacore_root() / space

    # Send the message
    store = MessageStore(space_root)
    msg = store.create_message(
        from_actor=username,
        to_actor=args.to,
        content=args.content,
        reply_to=args.reply_to,
    )
    print(f"[messaging] Sent: {msg.properties['ID']}")

    # Optionally complete the associated task
    if args.complete_task:
        inbox = AgentInbox(space_root, f"{username}-claude")
        node = inbox.workspace.find_by_id(args.complete_task)
        if node and node.todo == "WORKING":
            inbox.complete(node, tokens_used=args.tokens)
            print(f"[messaging] Completed task: {args.complete_task}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Rewrite hooks/mark-message.py**

```python
#!/usr/bin/env python3
"""Mark message hook — mark messages as read or archived.

Uses lib/message_store instead of regex-based tag manipulation.
"""

import sys
import argparse
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from lib.config import get_default_space, datacore_root
from lib.message_store import MessageStore


def main() -> None:
    parser = argparse.ArgumentParser(description="Mark message state")
    parser.add_argument("msg_id", help="Message ID")
    parser.add_argument("action", choices=["read", "archive"], help="Action")
    args = parser.parse_args()

    space = get_default_space()
    space_root = datacore_root() / space

    store = MessageStore(space_root)
    node = store.find_by_id(args.msg_id)
    if not node:
        print(f"[messaging] Message not found: {args.msg_id}")
        return

    if args.action == "read":
        store.mark_read(node)
        print(f"[messaging] Marked read: {args.msg_id}")
    elif args.action == "archive":
        store.archive(node)
        print(f"[messaging] Archived: {args.msg_id}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Rewrite hooks/task-queue.py**

```python
#!/usr/bin/env python3
"""Task queue hook — query and manage agent task queue.

Uses lib/agent_inbox instead of JSON state file.
"""

import sys
import argparse
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from lib.config import get_username, get_default_space, datacore_root
from lib.agent_inbox import AgentInbox


def main() -> None:
    parser = argparse.ArgumentParser(description="Task queue management")
    parser.add_argument(
        "action",
        choices=["status", "approve", "reject", "cancel"],
        help="Queue action",
    )
    parser.add_argument("--task-id", help="Task ID (for approve/reject/cancel)")
    parser.add_argument("--reason", default="", help="Reason (for reject/cancel)")
    args = parser.parse_args()

    username = get_username()
    space = get_default_space()
    space_root = datacore_root() / space

    inbox = AgentInbox(space_root, f"{username}-claude")

    if args.action == "status":
        counts = inbox.counts()
        print(f"Task queue for {username}-claude:")
        print(f"  Queued:  {counts['queued']}")
        print(f"  Working: {counts['working']}")
        print(f"  Waiting: {counts['waiting']}")
        print(f"  Done:    {counts['done']}")
        print(f"  Total:   {counts['total']}")

    elif args.action == "approve" and args.task_id:
        node = inbox.workspace.find_by_id(args.task_id)
        if node:
            inbox.approve(node)
            print(f"[messaging] Approved: {args.task_id}")

    elif args.action == "reject" and args.task_id:
        node = inbox.workspace.find_by_id(args.task_id)
        if node:
            inbox.reject(node, reason=args.reason)
            print(f"[messaging] Rejected: {args.task_id}")

    elif args.action == "cancel" and args.task_id:
        node = inbox.workspace.find_by_id(args.task_id)
        if node:
            inbox.cancel(node, reason=args.reason)
            print(f"[messaging] Cancelled: {args.task_id}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 7: Run hook tests**

Run: `pytest tests/test_hooks.py -v`
Expected: All tests PASS

- [ ] **Step 8: Smoke test hooks**

```bash
python hooks/task-queue.py status 2>&1 | head -5
```
Expected: Prints queue counts (may show 0s if no tasks)

- [ ] **Step 9: Commit**

```bash
git add hooks/ tests/test_hooks.py
git commit -m "refactor: rewire all hooks to use lib modules — remove duplicated code, use org-workspace"
```

---

### Task 8: Update module manifest and agent docs

**Files:**
- Modify: `module.yaml`
- Rewrite: `agents/claude-inbox.md` → `agents/message-task-intake.md`
- Modify: `agents/message-digest.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update module.yaml**

Key changes:
- Version bump to `0.2.0`
- Update agent list (`claude-inbox` → `message-task-intake`)
- Fix hooks to point to Python files (not `.md` files)
- Add `inbox_feeds` configuration
- Update dependency to include `org-workspace>=0.3.0`

- [ ] **Step 2: Rename and rewrite claude-inbox agent**

Rename `agents/claude-inbox.md` to `agents/message-task-intake.md`.
Rewrite to match actual code:
- References `org/messaging/agents/{username}-claude.org` (not `claude.org`)
- Uses org-workspace state machine (WAITING/QUEUED/WORKING/DONE)
- References TaskGovernor for approval gates
- Correct agent routing (matches actual tag patterns)

- [ ] **Step 3: Update message-digest.md**

Fix references to match new file layout:
- `org/messaging/inbox.org` instead of `org/inboxes/`
- Use org-workspace query API description
- Reference Universal Inbox feed

- [ ] **Step 4: Update CLAUDE.md**

Rewrite to match new architecture:
- Message storage at `org/messaging/` (not `org/inboxes/`)
- `TODO` keyword with `:message:` tag (not `MESSAGE` keyword)
- Agent inbox at `org/messaging/agents/`
- Trust tiers and governance
- `contacts.yaml` (not `USERS.yaml`)
- Correct settings schema

- [ ] **Step 5: Commit**

```bash
git add module.yaml agents/ CLAUDE.md
git rm agents/claude-inbox.md
git commit -m "docs: update module manifest, agent specs, and CLAUDE.md to match v0.2.0 architecture"
```

---

## Chunk 6: Integration Test and Cleanup

### Task 9: Integration test — end-to-end message flow

**Files:**
- Create: `tests/test_integration.py`

- [ ] **Step 1: Write integration test**

```python
# tests/test_integration.py
"""End-to-end test: message creation, agent task lifecycle, governance."""

import pytest
from pathlib import Path

from lib.config import clear_settings_cache


@pytest.fixture(autouse=True)
def _fresh_config():
    clear_settings_cache()
    yield
    clear_settings_cache()


@pytest.fixture
def full_setup(tmp_space, msg_state_config, task_state_config):
    """Set up message store, agent inbox, and governor together."""
    from lib.message_store import MessageStore
    from lib.agent_inbox import AgentInbox
    from lib.governor import TaskGovernor

    state_dir = tmp_space / ".datacore" / "state" / "messaging"
    state_dir.mkdir(parents=True)

    return {
        "store": MessageStore(tmp_space, state_config=msg_state_config),
        "agent": AgentInbox(tmp_space, "test-claude", state_config=task_state_config),
        "governor": TaskGovernor(state_dir=state_dir),
        "space": tmp_space,
    }


class TestMessageToTaskFlow:
    def test_unknown_sender_needs_approval(self, full_setup):
        """An unknown sender's task goes to WAITING for owner approval."""
        agent = full_setup["agent"]
        gov = full_setup["governor"]

        # Governor allows (no budget exceeded) but tier = unknown
        check = gov.check_task("tex@team.com", estimated_tokens=5000)
        assert check.allowed is True
        assert check.trust_tier == "unknown"  # Not configured as team

        # Create task with the resolved tier — unknown needs approval
        task = agent.create_task(
            from_actor="tex@team.com",
            content="Research competitors",
            trust_tier=check.trust_tier,
            tags=["AI", "research"],
        )
        assert task.todo == "WAITING"

    def test_full_task_lifecycle(self, full_setup):
        """Owner task: auto-accept -> claim -> complete -> archive."""
        agent = full_setup["agent"]
        gov = full_setup["governor"]

        check = gov.check_task("owner@x.com", estimated_tokens=1000)
        # Pass "owner" directly — in production, tier comes from settings
        task = agent.create_task(
            from_actor="owner@x.com",
            content="Quick research",
            trust_tier="owner",
            tags=["AI"],
        )
        assert task.todo == "QUEUED"

        agent.claim(task)
        assert task.todo == "WORKING"

        agent.complete(task, tokens_used=800)
        assert task.todo == "DONE"

        gov.record_usage("owner@x.com", tokens=800)
        usage = gov.get_usage("owner@x.com")
        assert usage["tokens_today"] == 800


class TestGovernorBlocksAbuse:
    def test_rate_limited_sender_blocked(self, full_setup):
        agent = full_setup["agent"]
        gov = full_setup["governor"]

        # Submit 5 tasks (unknown tier limit)
        for i in range(5):
            gov.record_task_submission("spammer@x.com")

        # 6th should be blocked
        check = gov.check_task("spammer@x.com", estimated_tokens=100)
        assert check.allowed is False


class TestMessageStoreIndependence:
    def test_messages_and_tasks_coexist(self, full_setup):
        """Messages in inbox.org and tasks in agent/*.org don't interfere."""
        store = full_setup["store"]
        agent = full_setup["agent"]

        store.create_message("a@x.com", "b@x.com", "Hello")
        agent.create_task("a@x.com", "Do work", "owner", ["AI"])

        assert len(store.find_unread()) == 1
        assert len(agent.find_by_state("QUEUED")) == 1
```

- [ ] **Step 2: Run all tests**

Run: `pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_integration.py
git commit -m "test: add integration tests — message-to-task flow, governance blocks, store independence"
```

---

### Task 10: Cleanup and PR preparation

**Files:**
- Modify: `README.md`
- Delete: `lib/datacore-msg-window.py` (legacy GUI, superseded by `datacore-msg.py`)
- Delete: `templates/USERS.yaml` (replaced by contacts.yaml)
- Create: `templates/contacts.yaml`

- [ ] **Step 1: Create contacts.yaml template**

```yaml
# Known ActivityPub actors for this space
# Add actors via /msg-trust or manually edit this file
actors: []
# Example:
#   - id: "tex@team.example.com"
#     name: "Tex"
#     trust_tier: team
#     added: 2026-03-11
```

- [ ] **Step 2: Delete legacy files**

```bash
git rm lib/datacore-msg-window.py templates/USERS.yaml
```

- [ ] **Step 3: Update README.md**

Update to reflect v0.2.0 changes:
- New storage layout (`org/messaging/`)
- org-workspace dependency
- Task governance overview
- Agent inbox concept
- Updated install instructions (include org-workspace)
- Remove references to single relay URL (configurable now)

- [ ] **Step 4: Run full test suite one final time**

Run: `pytest tests/ -v --tb=short`
Expected: All tests PASS, 0 errors

- [ ] **Step 5: Commit and prepare PR**

```bash
git add templates/contacts.yaml README.md
git commit -m "chore: cleanup — remove legacy files, add contacts template, update README for v0.2.0"
```

Final PR should contain:
- 10 commits, logically organized
- All CRITICAL and HIGH audit issues fixed
- org-workspace integration with FileLock
- Agent inbox with full state machine
- Task governor with trust tiers, budgets, rate limits
- Consolidated relay (1 file, not 3)
- Tests for all new modules
- Updated docs matching actual code
