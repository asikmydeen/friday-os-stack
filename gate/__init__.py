"""Approval gate.

The Board is the only actor that can create or exchange an approval.
Chat, a messaging door, and an inbound MCP caller cannot. A model
argument of confirmed=true is ignored.

Catalog install is refused for every app id, and that refusal does not
consume an approval. This package does not start containers.
"""

from gate.rules import (
    Decision,
    MemoryStore,
    complete_step,
    create_approval,
    record_task,
    resume_operation,
    resume_task,
    submit,
)

__all__ = [
    "Decision",
    "MemoryStore",
    "complete_step",
    "create_approval",
    "record_task",
    "resume_operation",
    "resume_task",
    "submit",
]
