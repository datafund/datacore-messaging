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

        check = gov.check_task("tex@team.com", estimated_tokens=5000)
        assert check.allowed is True
        assert check.trust_tier == "unknown"

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
        gov = full_setup["governor"]

        for i in range(5):
            gov.record_task_submission("spammer@x.com")

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
