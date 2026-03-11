import json
import time
from datetime import datetime
from pathlib import Path
import pytest


@pytest.fixture
def gov(tmp_path, monkeypatch):
    from lib.config import clear_settings_cache
    clear_settings_cache()
    monkeypatch.setenv("DATACORE_ROOT", str(tmp_path))
    from lib.governor import TaskGovernor
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
        for i in range(3):
            gov.record_usage("spammer@x.com", tokens=4000)
        result = gov.check_task("spammer@x.com", estimated_tokens=4000)
        assert result.allowed is False
        assert "budget" in result.reason.lower()


class TestRateLimiting:
    def test_tasks_per_hour_limit(self, gov):
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
        result = gov.check_task("unknown@x.com", estimated_tokens=100, effort=3)
        assert result.allowed is True

    def test_effort_exceeds_tier_limit(self, gov):
        result = gov.check_task("unknown@x.com", estimated_tokens=100, effort=5)
        assert result.allowed is False
        assert "effort" in result.reason.lower()
