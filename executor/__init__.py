"""Executor.

Accepts a named approval from the Board and a waiting task from Friday.
The Board can list that owner's goals. A credential-shaped goal is left
off the list. /recover compares supplied objects with one journal. A
caller-supplied runtime creates the container step. Applied is recorded
only when that runtime says the container is up. A second resume does
not create it again. The host Docker daemon is not called. Without a
runtime it does not create a container. Catalog install stays closed.
With POSTGRES_HOST
set, POST /backup writes one manifest through backup_store. Without
that host the manifest stays in memory. A second store of the same
pause keeps the same id. Nothing is copied. Chat cannot record one.
With that host set, POST /approvals and POST /exchange call
approval_store and approval_exchange_owner. Without it the gate file
remains. A second exchange of the same body keeps the operation id.
Nothing is sent.
"""
