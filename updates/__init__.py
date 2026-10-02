"""Update and code-profile decisions.

A signature with no verifier is refused. A verifier that accepts the
checksum line still does not apply the update. ship-mcp is recorded by
name and does not start taskrunner. An optional coding-plan base URL
is recorded by name and is not called. An open-ended apt upgrade is
refused, and a reflash is not an upgrade.
"""

from updates.packages import package_change, reflash
from updates.plan import record_plan, use_plan
from updates.ship import record_surface, submit
from updates.signed import Decision, checksum_line, code_profile, propose

__all__ = [
    "Decision",
    "checksum_line",
    "code_profile",
    "package_change",
    "propose",
    "record_plan",
    "record_surface",
    "reflash",
    "submit",
    "use_plan",
]
