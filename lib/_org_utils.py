"""Shared org-workspace utilities for message and task stores."""

from org_workspace import OrgWorkspace, NodeView


def _refresh_node(node: NodeView, ws: OrgWorkspace) -> None:
    """Update a NodeView's slots in-place from the current workspace state.

    org-workspace bumps the file generation on every create_node call
    (via _reload_preserving_dirty). This helper re-fetches the fresh
    NodeView by ID and patches the stale node's __slots__ so callers
    don't need to re-bind their variable.
    """
    node_id = object.__getattribute__(node, "_node").properties.get("ID")
    if node_id:
        fresh = ws.find_by_id(node_id)
        if fresh is not None:
            object.__setattr__(node, "_node", fresh._node)
            object.__setattr__(node, "_generation", fresh._generation)
            object.__setattr__(node, "_gen_check", fresh._gen_check)
