"""Catalog decisions.

discover lists a pin and refuses every install. An empty pin lists
nothing. catalog/render.py judges a caller-supplied description and
does not install it. catalog/propose.py records one draft wire an
advisor supplies. Tools stay off until the Board accepts that name.
It does not read the draft wires and does not install.
catalog/allowlist.py allowlists jellyfin on one Board fire and leaves
every other catalog id closed. Install of an id that is not allowlisted
stays closed, and install of jellyfin stays closed too. It does not
store a sentence. This package does not fetch upstream and does not
start a container.
"""

from catalog.discover import (
    Decision,
    Listing,
    discover,
    draft_ids,
    request_install,
    review_install,
)

__all__ = [
    "Decision",
    "Listing",
    "discover",
    "draft_ids",
    "request_install",
    "review_install",
]
