"""Task governance — trust tiers, compute budgets, rate limits.

Controls what work Claude agents accept and at what cost.
Per DIP-0023 Section 7.
"""

import json
import os
import tempfile
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
    tasks_this_hour: list = field(default_factory=list)
    tasks_today: int = 0
    active_tasks: int = 0


class TaskGovernor:
    """Enforces trust tiers, budgets, and rate limits."""

    def __init__(self, state_dir: Path | None = None):
        self._state_dir = state_dir or Path(".datacore/state/messaging")
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._today = datetime.now().strftime("%Y-%m-%d")
        self._budget_file = self._state_dir / f"budget-{self._today}.json"
        self._state: dict[str, _SenderState] = {}
        self._load_state()

    def _load_state_unlocked(self) -> None:
        """Read state from disk. Must be called from within a FileLock context."""
        self._state = {}
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

    def _load_state(self) -> None:
        """Load state from disk, acquiring FileLock for a safe read."""
        with FileLock(self._budget_file):
            self._load_state_unlocked()

    def _write_state_unlocked(self) -> None:
        """Atomically write current in-memory state to disk (temp+rename).

        Must be called from within a FileLock context.
        """
        now = time.time()
        hour_ago = now - 3600
        data = {"date": self._today, "senders": {}}
        for sender, state in self._state.items():
            state.tasks_this_hour = [t for t in state.tasks_this_hour if t > hour_ago]
            data["senders"][sender] = {
                "tokens_today": state.tokens_today,
                "tasks_this_hour": state.tasks_this_hour,
                "tasks_today": state.tasks_today,
                "active_tasks": state.active_tasks,
            }
        # Write to a temp file in the same directory, then atomically rename.
        fd, tmp_path = tempfile.mkstemp(
            dir=self._budget_file.parent, suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w") as fh:
                fh.write(json.dumps(data, indent=2))
            os.replace(tmp_path, self._budget_file)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def _check_date_rollover(self) -> None:
        """Reset state if day has changed."""
        today = datetime.now().strftime("%Y-%m-%d")
        if today != self._today:
            self._today = today
            self._budget_file = self._state_dir / f"budget-{today}.json"
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
        """Check whether a task from actor_id is allowed under current governance rules.

        This is a read-only check against the current in-memory state. For an
        atomic check-and-record use check_and_record() or submit_task().
        """
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
        if daily_limit > 0 and sender.tokens_today + estimated_tokens > daily_limit:
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
            total_tokens = sum(s.tokens_today for s in self._state.values())
            if total_tokens + estimated_tokens > global_limit:
                return TaskCheckResult(
                    allowed=False,
                    trust_tier=tier_name,
                    auto_accept=auto_accept,
                    reason=f"Global budget exceeded: {total_tokens}/{global_limit} tokens today",
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

        # Check global queue depth
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
        """Check and atomically record a task submission if allowed."""
        with FileLock(self._budget_file):
            self._load_state_unlocked()
            result = self.check_task(actor_id, estimated_tokens=estimated_tokens, effort=effort)
            if result.allowed:
                sender = self._get_sender(actor_id)
                sender.tasks_this_hour.append(time.time())
                sender.tasks_today += 1
                sender.active_tasks += 1
                self._write_state_unlocked()
        return result

    def submit_task(
        self,
        actor_id: str,
        estimated_tokens: int = 0,
        effort: int = 0,
    ) -> TaskCheckResult:
        """Check governance rules and record a task submission if allowed.

        Preferred public API over check_and_record (same semantics, clearer name).
        """
        return self.check_and_record(actor_id, estimated_tokens=estimated_tokens, effort=effort)

    def _record_task_submission(self, actor_id: str) -> None:
        """Unconditionally record a task submission (internal use only).

        Callers outside this class should use submit_task() which also
        enforces governance rules.
        """
        with FileLock(self._budget_file):
            self._load_state_unlocked()
            sender = self._get_sender(actor_id)
            sender.tasks_this_hour.append(time.time())
            sender.tasks_today += 1
            sender.active_tasks += 1
            self._write_state_unlocked()

    def record_task_submission(self, actor_id: str) -> None:
        """Record a task submission unconditionally.

        Deprecated: prefer submit_task() which enforces governance rules.
        Kept for backward compatibility.
        """
        self._record_task_submission(actor_id)

    def record_usage(self, actor_id: str, tokens: int) -> None:
        """Record token usage for an actor."""
        with FileLock(self._budget_file):
            self._check_date_rollover()
            self._load_state_unlocked()
            sender = self._get_sender(actor_id)
            sender.tokens_today += tokens
            self._write_state_unlocked()

    def record_task_completion(self, actor_id: str) -> None:
        """Record that a task was completed by actor_id."""
        with FileLock(self._budget_file):
            self._load_state_unlocked()
            sender = self._get_sender(actor_id)
            sender.active_tasks = max(0, sender.active_tasks - 1)
            self._write_state_unlocked()

    def get_usage(self, actor_id: str) -> dict:
        """Get usage stats for an actor."""
        self._check_date_rollover()
        sender = self._get_sender(actor_id)
        return {"tokens_today": sender.tokens_today, "tasks_today": sender.tasks_today}

    def daily_summary(self) -> dict:
        """Get a summary of today's usage across all senders."""
        total_tokens = sum(s.tokens_today for s in self._state.values())
        by_sender = {
            actor: {"tokens": s.tokens_today, "tasks": s.tasks_today}
            for actor, s in self._state.items()
        }
        return {"date": self._today, "total_tokens": total_tokens, "by_sender": by_sender}
