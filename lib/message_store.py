"""Message storage layer built on org-workspace.

All message CRUD operations go through this module.
Handles message creation, querying, state transitions,
threading, and file delivery notifications.

Message IDs are timestamp-unique (not content-addressed):
format is msg-YYYYMMDD-HHMMSS-{hash[:8]} where hash includes
microseconds to minimize collision risk within the same second.

Generation contract:
- Write methods (create_*, mark_*, archive) do NOT reload — they
  operate on the in-memory workspace and save to disk. Returned
  NodeViews remain valid until the next reload() call.
- Read methods (find_*) reload from disk first to reflect changes
  from other processes. They invalidate previously held NodeViews.
"""

import hashlib
import os
from datetime import datetime
from pathlib import Path

from org_workspace import OrgWorkspace, StateConfig, NodeView
from org_workspace.concurrency import FileLock

from lib._org_utils import _refresh_node


_TODO_HEADER = "#+TODO: TODO WAITING QUEUED WORKING | DONE CANCELLED ARCHIVED\n"

_MSG_STATE_CONFIG = StateConfig(
    sequences={"messaging": ["TODO", "WAITING", "DONE", "ARCHIVED", "CANCELLED"]},
    terminal_states=frozenset(["ARCHIVED", "CANCELLED"]),
)


def _unique_msg_id(from_actor: str, to_actor: str, content: str) -> str:
    """Generate a timestamp-unique message ID."""
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
        self._live_nodes: list[NodeView] = []  # nodes returned to callers
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
                pass

    def _refresh_live_nodes(self) -> None:
        """Refresh all tracked live nodes after a workspace generation bump."""
        for node in self._live_nodes:
            try:
                _refresh_node(node, self._ws)
            except Exception:
                pass  # Best-effort; stale nodes are replaced on next find_*

    def create_message(
        self,
        from_actor: str,
        to_actor: str,
        content: str,
        reply_to: str | None = None,
        priority: str | None = None,
        **extra_props: str,
    ) -> NodeView:
        """Create a new message in the inbox.

        Returns a NodeView that stays valid across subsequent create_message
        calls (tracked and refreshed when the workspace generation bumps).
        """
        msg_id = _unique_msg_id(from_actor, to_actor, content)
        now_str = datetime.now().strftime("[%Y-%m-%d %a %H:%M]")
        heading = now_str

        props: dict[str, str] = {
            "FROM": from_actor,
            "TO": to_actor,
            **extra_props,
        }
        if reply_to:
            props["REPLY_TO"] = reply_to
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

        # create_node calls _reload_preserving_dirty which bumps the generation.
        # Refresh all previously returned nodes so they stay valid.
        self._refresh_live_nodes()
        self._live_nodes.append(node)
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
        """Create a file delivery notification in the inbox.

        Returns a NodeView valid until the next find_* call.
        """
        file_id = _unique_file_id(from_actor, filename)
        now_str = datetime.now().strftime("[%Y-%m-%d %a %H:%M]")
        heading = now_str

        with FileLock(self._inbox_path):
            node = self._ws.create_node(
                file=self._inbox_path,
                heading=heading,
                state="TODO",
                tags=["unread", "file_delivery"],
                body="File delivery via Fairdrop. Download to process.",
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

        self._refresh_live_nodes()
        self._live_nodes.append(node)
        return node

    def find_unread(self) -> list[NodeView]:
        """Find all unread messages (reloads from disk)."""
        self._ws.reload(self._inbox_path)
        return [n for n in self._ws.find_by_tag("unread") if n.todo == "TODO"]

    def find_messages(self) -> list[NodeView]:
        """Find all message nodes, any state (reloads from disk)."""
        self._ws.reload(self._inbox_path)
        return [n for n in self._ws.find_by_tag("message")]

    def find_file_deliveries(self, unread_only: bool = True) -> list[NodeView]:
        """Find file delivery notifications (reloads from disk)."""
        self._ws.reload(self._inbox_path)
        nodes = self._ws.find_by_tag("file_delivery")
        if unread_only:
            nodes = [n for n in nodes if "unread" in n.shallow_tags]
        return nodes

    def find_thread(self, thread_root_id: str) -> list[NodeView]:
        """Find all messages in a thread (reloads from disk)."""
        self._ws.reload(self._inbox_path)
        return [
            n
            for n in self._ws.all_nodes()
            if n.properties.get("THREAD") == thread_root_id
        ]

    def find_by_id(self, msg_id: str) -> NodeView | None:
        """Find a message by its ID (in-memory, no reload)."""
        return self._ws.find_by_id(msg_id)

    def mark_read(self, node: NodeView) -> None:
        """Mark message as read (TODO -> DONE).

        Operates on in-memory node — no reload. The node remains valid.
        """
        with FileLock(self._inbox_path):
            tags = list(node.shallow_tags - {"unread"})
            self._ws.set_tags(node, tags)
            self._ws.transition(node, "DONE")
            self._ws.save(self._inbox_path)

    def archive(self, node: NodeView) -> None:
        """Archive a message (DONE -> ARCHIVED).

        Operates on in-memory node — no reload.
        """
        with FileLock(self._inbox_path):
            self._ws.transition(node, "ARCHIVED")
            self._ws.save(self._inbox_path)

    @property
    def workspace(self) -> OrgWorkspace:
        """Access underlying workspace (for advanced queries)."""
        return self._ws
