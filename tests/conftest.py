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
