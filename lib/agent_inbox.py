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
allows revision. Only CANCELLED and ARCHIVED are terminal.
"""

import os
from datetime import datetime
from pathlib import Path

from org_workspace import OrgWorkspace, StateConfig, NodeView
from org_workspace.concurrency import FileLock

from lib.config import get_trust_tier_config


_TODO_HEADER = "#+TODO: TODO WAITING QUEUED WORKING | DONE CANCELLED ARCHIVED\n"

# CORRECT API: sequences + terminal_states
_TASK_STATE_CONFIG = StateConfig(
    sequences={"tasks": ["TODO", "WAITING", "QUEUED", "WORKING", "DONE", "CANCELLED", "ARCHIVED"]},
    terminal_states=frozenset(["CANCELLED", "ARCHIVED"]),
)


def _should_auto_accept(trust_tier: str) -> bool:
    tier_config = get_trust_tier_config(trust_tier)
    return tier_config.get("auto_accept", False)


def _assert_state(node: NodeView, expected: str, method: str) -> None:
    if node.todo != expected:
        raise ValueError(f"{method}: Expected state {expected}, got {node.todo}")


def _refresh_node(node: NodeView, ws: OrgWorkspace) -> None:
    """Update a NodeView's slots in-place from the current workspace state."""
    node_id = object.__getattribute__(node, "_node").properties.get("ID")
    if node_id:
        fresh = ws.find_by_id(node_id)
        if fresh is not None:
            object.__setattr__(node, "_node", fresh._node)
            object.__setattr__(node, "_generation", fresh._generation)
            object.__setattr__(node, "_gen_check", fresh._gen_check)


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
        self._inbox_path = self._root / "org" / "messaging" / "agents" / f"{agent_name}.org"
        self._ws = OrgWorkspace(state_config=state_config or _TASK_STATE_CONFIG)
        self._live_nodes: list[NodeView] = []
        self._ensure_file()
        self._ws.load(self._inbox_path)

    def _ensure_file(self) -> None:
        self._inbox_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(str(self._inbox_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, _TODO_HEADER.encode())
            os.close(fd)
        except FileExistsError:
            pass

    def _reload(self) -> None:
        self._ws.reload(self._inbox_path)

    def _refresh_live_nodes(self) -> None:
        for node in self._live_nodes:
            try:
                _refresh_node(node, self._ws)
            except Exception:
                pass

    def create_task(
        self,
        from_actor: str,
        content: str,
        trust_tier: str,
        tags: list[str],
        effort: int | None = None,
        estimated_tokens: int | None = None,
    ) -> NodeView:
        auto_accept = _should_auto_accept(trust_tier)
        state = "QUEUED" if auto_accept else "WAITING"
        now_str = datetime.now().strftime("[%Y-%m-%d %a %H:%M]")

        props: dict[str, str] = {
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

        self._refresh_live_nodes()
        self._live_nodes.append(node)
        return node

    def approve(self, node: NodeView) -> None:
        _assert_state(node, "WAITING", "approve")
        with FileLock(self._inbox_path):
            self._ws.set_property(node, "APPROVAL", "owner_approved")
            self._ws.transition(node, "QUEUED")
            self._ws.save(self._inbox_path)

    def reject(self, node: NodeView, reason: str = "") -> None:
        _assert_state(node, "WAITING", "reject")
        with FileLock(self._inbox_path):
            if reason:
                self._ws.set_property(node, "REJECTION_REASON", reason)
            self._ws.transition(node, "CANCELLED")
            self._ws.save(self._inbox_path)

    def cancel(self, node: NodeView, reason: str = "") -> None:
        _assert_state(node, "QUEUED", "cancel")
        with FileLock(self._inbox_path):
            if reason:
                self._ws.set_property(node, "CANCELLATION_REASON", reason)
            self._ws.transition(node, "CANCELLED")
            self._ws.save(self._inbox_path)

    def claim(self, node: NodeView) -> None:
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
                self._ws.set_property(node, "QUALITY_SCORE", f"{quality_score:.2f}")
            self._ws.transition(node, "DONE")
            self._ws.save(self._inbox_path)

    def retry(self, node: NodeView, reason: str = "") -> None:
        _assert_state(node, "WORKING", "retry")
        retry_count = int(node.properties.get("RETRY_COUNT", "0")) + 1
        with FileLock(self._inbox_path):
            self._ws.set_property(node, "RETRY_COUNT", str(retry_count))
            if reason:
                self._ws.set_property(node, "RETRY_REASON", reason)
            self._ws.transition(node, "QUEUED")
            self._ws.save(self._inbox_path)

    def request_revision(self, node: NodeView, feedback: str = "") -> None:
        _assert_state(node, "DONE", "request_revision")
        with FileLock(self._inbox_path):
            if feedback:
                self._ws.set_property(node, "REVISION_FEEDBACK", feedback)
            self._ws.transition(node, "QUEUED")
            self._ws.save(self._inbox_path)

    def find_by_state(self, *states: str) -> list[NodeView]:
        self._reload()
        return self._ws.find_by_state(*states)

    def find_awaiting_approval(self) -> list[NodeView]:
        self._reload()
        return [
            n for n in self._ws.find_by_state("WAITING")
            if n.properties.get("AWAITING") == "owner-approval"
        ]

    def counts(self) -> dict[str, int]:
        self._reload()
        all_nodes = list(self._ws.all_nodes())
        nodes = [n for n in all_nodes if n.level > 0]
        return {
            "queued": sum(1 for n in nodes if n.todo == "QUEUED"),
            "working": sum(1 for n in nodes if n.todo == "WORKING"),
            "done": sum(1 for n in nodes if n.todo == "DONE"),
            "waiting": sum(1 for n in nodes if n.todo == "WAITING"),
            "cancelled": sum(1 for n in nodes if n.todo == "CANCELLED"),
            "total": len(nodes),
        }

    @property
    def workspace(self) -> OrgWorkspace:
        return self._ws
