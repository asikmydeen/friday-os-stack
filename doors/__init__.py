"""Door decisions.

reach.py decides and does not listen. server.py delivers a turn to
Friday when DOOR_ENABLED is yes. The adapter cannot approve. token.py
records one messaging-door secret by name and does not start that
listener. The mesh opens the Board. The tunnel stays off. hostnames.py
records one public name and does not start a tunnel. remove_node
decides a cleanup and does not delete a peer. peers.py records one
pre-auth key by name and does not call Headscale. mattermost.py records
a roster and does not call Mattermost.
"""

from doors.reach import (
    Decision,
    adapter_touch,
    deliver,
    join_mesh,
    mesh_open,
    remove_node,
    tunnel,
)

__all__ = [
    "Decision",
    "adapter_touch",
    "deliver",
    "join_mesh",
    "mesh_open",
    "remove_node",
    "tunnel",
]
