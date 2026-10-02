"""Webhook receiver.

An app posts here. Friday does not post, and the executor does not.
A valid header stores one typed event. With POSTGRES_HOST set, that
row is webhook_store. Without it, the event stays in memory. Friday
reads the fixed sentence for that type. The raw body stays in the log.
webhooks/secret.py records one generated secret by name. The value
stays in the process.
"""

from webhooks.receiver import (
    HEADER,
    SENTENCES,
    MemoryStore,
    Receipt,
    receive,
    speak,
)
from webhooks.secret import Book, Decision, matches, names, register, show

__all__ = [
    "HEADER",
    "SENTENCES",
    "Book",
    "Decision",
    "MemoryStore",
    "Receipt",
    "matches",
    "names",
    "receive",
    "register",
    "show",
    "speak",
]
