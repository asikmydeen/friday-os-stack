"""MCP grant decisions.

Visible tools are the intersection of granted and offered. This package
does not open a listener and does not create an approval.
"""

from mcpbus.grants import Decision, accept_tool, inbound, visible, wire_as_grant

__all__ = [
    "Decision",
    "accept_tool",
    "inbound",
    "visible",
    "wire_as_grant",
]
