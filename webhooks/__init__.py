"""Webhook receiver.

An app posts here. Friday does not, and the executor does not. A valid
header stores one typed event. Friday may say the fixed sentence for that
type. The raw body stays in the log.
"""

from webhooks.receiver import (
    HEADER,
    SENTENCES,
    MemoryStore,
    Receipt,
    receive,
    speak,
)

__all__ = [
    "HEADER",
    "SENTENCES",
    "MemoryStore",
    "Receipt",
    "receive",
    "speak",
]
