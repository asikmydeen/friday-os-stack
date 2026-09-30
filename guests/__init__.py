"""Guest lifecycle decisions.

Install stays closed. Adopt records an app that is already running.
This package does not start a container.
"""

from guests.lifecycle import Decision, adopt, bundle, disconnect, install_guest, uninstall

__all__ = [
    "Decision",
    "adopt",
    "bundle",
    "disconnect",
    "install_guest",
    "uninstall",
]
