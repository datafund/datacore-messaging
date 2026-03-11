"""Tests for the agent inbox store (lib/agent_inbox.py)."""

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
        node = agent_store.create_task("unknown@x.com", "task", "unknown", ["AI"])
        assert node.todo == "WAITING"
        agent_store.approve(node)
        assert node.todo == "QUEUED"

    def test_reject_task(self, agent_store):
        node = agent_store.create_task("unknown@x.com", "task", "unknown", ["AI"])
        agent_store.reject(node, reason="Not relevant")
        assert node.todo == "CANCELLED"

    def test_claim_and_complete(self, agent_store):
        node = agent_store.create_task("owner@x.com", "task", "owner", ["AI"])
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
        node = agent_store.create_task("owner@x.com", "task", "owner", ["AI"])
        agent_store.claim(node)
        agent_store.complete(node, tokens_used=100)
        agent_store.request_revision(node, feedback="Needs more detail")
        assert node.todo == "QUEUED"

    def test_cancel_queued_task(self, agent_store):
        node = agent_store.create_task("owner@x.com", "task", "owner", ["AI"])
        assert node.todo == "QUEUED"
        agent_store.cancel(node, reason="No longer needed")
        assert node.todo == "CANCELLED"
        assert node.properties["CANCELLATION_REASON"] == "No longer needed"

    def test_retry_failed_task(self, agent_store):
        node = agent_store.create_task("owner@x.com", "task", "owner", ["AI"])
        agent_store.claim(node)
        assert node.todo == "WORKING"
        agent_store.retry(node, reason="Agent crashed")
        assert node.todo == "QUEUED"
        assert node.properties["RETRY_REASON"] == "Agent crashed"
        assert int(node.properties.get("RETRY_COUNT", "0")) == 1

    def test_precondition_reject_on_queued_raises(self, agent_store):
        node = agent_store.create_task("owner@x.com", "task", "owner", ["AI"])
        assert node.todo == "QUEUED"
        with pytest.raises(ValueError, match="Expected state WAITING"):
            agent_store.reject(node)

    def test_precondition_claim_on_waiting_raises(self, agent_store):
        node = agent_store.create_task("unknown@x.com", "task", "unknown", ["AI"])
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
