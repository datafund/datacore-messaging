"""Tests for hooks using the new lib modules."""
import sys
from pathlib import Path
import pytest

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

    def test_skips_when_task_already_working(self, tmp_space, task_state_config, monkeypatch):
        monkeypatch.setenv("DATACORE_ROOT", str(tmp_space.parent))
        from lib.agent_inbox import AgentInbox
        inbox = AgentInbox(tmp_space, "test-claude", task_state_config)
        t1 = inbox.create_task("owner@x.com", "Task 1", "owner", ["AI"])
        inbox.create_task("owner@x.com", "Task 2", "owner", ["AI"])
        inbox.claim(t1)
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
