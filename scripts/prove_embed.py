"""Ask a throwaway Ollama for one nomic-embed-text vector.

The length has to be 768. The vector is not printed.
"""

from __future__ import annotations

import os
import sys

from memoryd.embed import ollama_embed


def main() -> int:
    try:
        vector = ollama_embed(os.environ.get("OLLAMA_URL", ""))("lighthouse")
    except OSError as exc:
        print(f"prove-embed: {exc}", file=sys.stderr)
        return 1
    if len(vector) != 768:
        print(f"prove-embed: length {len(vector)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
