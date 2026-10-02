#!/usr/bin/env python3
"""EXPERIMENTAL placeholder.

Optional Mattermost door described in README "Build order", step 2.
doors/mattermost.py records the roster and the membership rule.
This script does not call Mattermost and does not write the bridge.
"""

import sys


def main() -> int:
    print("bootstrap-mattermost.py does not call Mattermost.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
