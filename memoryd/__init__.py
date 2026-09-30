"""Memory service.

Recall requires an owner. The pack holds at most 8 notes. The file store
does not open Postgres or Qdrant. The process does, when those hosts are set.
"""

from memoryd.store import RECALL_CAP, Decision, Notes

__all__ = ["RECALL_CAP", "Decision", "Notes"]
