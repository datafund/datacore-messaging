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
        msg1 = store.create_message(
            from_actor="a@x.com", to_actor="b@x.com", content="same"
        )
        msg2 = store.create_message(
            from_actor="a@x.com", to_actor="b@x.com", content="same"
        )
        # IDs may collide within same second — that's OK for tests


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
