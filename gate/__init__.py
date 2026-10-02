"""Approval gate.

The Board is the only actor that can create or exchange an approval.
Chat, a messaging door, and an inbound MCP caller cannot. A model
argument of confirmed=true is ignored.

Catalog install is refused for every app id, and that refusal does not
consume an approval. recover() compares a journal with objects the
caller supplies. A caller-supplied runtime creates the container step.
Applied is recorded only when that runtime says the container is up. A
second resume does not create it again. It does not call the host
Docker daemon. Without a runtime it does not create a container.
gate/journal.py records a running or blocked task step, keeps a noticed
tool off until the
Board accepts that name, and stores a page, webhook, or tool body as
evidence rather than as the goal. A sensitive step stays waiting until
an approval for that step and that same owner is already exchanged.
It does not create an approval.
With POSTGRES_HOST set, gate/sqlstore.py calls approval_store and
approval_exchange_owner. Without that host the process file remains.
A second exchange of the same body keeps the operation id. A forbidden
mount is refused before the connection opens. Nothing is sent.
This package does not call the host Docker daemon.
"""

from gate.recover import Recovery, recover
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
    "Recovery",
    "complete_step",
    "create_approval",
    "record_task",
    "recover",
    "resume_operation",
    "resume_task",
    "submit",
]
