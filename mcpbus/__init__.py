"""MCP grant decisions.

grants.py decides and does not listen. A connection grant names one
server, one secret reference, one role, and tool names. Those names stay
out of the prompt until the Board accepts each one. A secret value is
not stored. The server is not called. server.py answers tools/list and
tools/call when MCP_ENABLED is yes. outbound.py calls one granted server
when OUTBOUND_ENABLED is yes. A mutating call waits. token.py records
one generated secret and returns the name MCP_TOKEN only. It does not
start the listener. ref.py records one generated secret for calling a
granted server and returns the name MCP_SECRET_REF only. It does not
call that server. outbound.py does not call that record. This package
does not create an approval.
"""

from mcpbus.grants import (
    Connection,
    Decision,
    GrantBook,
    accept_grant_tool,
    accept_tool,
    inbound,
    prompt_for,
    record_grant,
    visible,
    wire_as_grant,
)

__all__ = [
    "Connection",
    "Decision",
    "GrantBook",
    "accept_grant_tool",
    "accept_tool",
    "inbound",
    "prompt_for",
    "record_grant",
    "visible",
    "wire_as_grant",
]
