"""Friday, the conversation process.

No host port. Ask goes through the memory service. This package does
not create an approval. `state.py` records the state book in the
process and does not open SQLite. `durable.py` writes that book to
the file named by FRIDAY_STATE. Ask does not import either module.
"""
