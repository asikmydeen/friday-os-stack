"""Browser-session decisions.

session.py decides and does not listen. A page kept there is evidence,
and the session is discarded when the task finishes or the owner stops
it. broker.py records one site secret and returns the name only. The
model is not given the value. server.py fetches one page when
BROWSER_ENABLED is yes and does not call those records. The model sees
page text. Send, pay, delete, and publish wait. This package does not
create an approval.
"""

from browser.session import Decision, act, credential, discard, note_page, placement, shown

__all__ = [
    "Decision",
    "act",
    "credential",
    "discard",
    "note_page",
    "placement",
    "shown",
]
