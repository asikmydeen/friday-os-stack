"""Catalog decisions.

discover lists a pin and refuses every install. An empty pin lists
nothing. This package does not fetch upstream and does not start a
container.
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
