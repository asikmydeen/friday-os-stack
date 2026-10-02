"""Guest lifecycle decisions.

Install stays closed. Adopt records an app that is already running.
A managed uninstall records grant and tunnel removal, keeps the library,
and does not stop the container. A separate confirm does not delete the
files. guests/registry.py reads caller-supplied rows and does not stop
an app. guests/accounts.py tells a person with no token to connect an
account and does not write the owner's tracker. guests/bundle.py records
the Movies and TV wiring plan and does not apply it. guests/home.py
records Home Assistant as its own entry and does not apply it.
guests/known.py records one log for a known app and does not read a
container. guests/start.py records that the Board asked to start one
known managed app and does not start it. guests/stop.py records that
the Board asked to stop one known managed app and does not stop it.
guests/pull.py records that the Board asked to pull one known managed
app and does not pull the image. guests/call.py records that the Board
asked the named advisor to call one known app, including an adopted app, and does not make
the call. guests/upgrade.py records that the Board asked to upgrade one
known managed app. A new tool stays off until the Board accepts that
name. The image is not upgraded. This package does not start or stop a
container, does not pull an image, does not upgrade one, and does not
call an app.
"""

from guests.lifecycle import (
    Decision,
    adopt,
    bundle,
    confirm_delete,
    disconnect,
    install_guest,
    record_removal,
    uninstall,
)

__all__ = [
    "Decision",
    "adopt",
    "bundle",
    "confirm_delete",
    "disconnect",
    "install_guest",
    "record_removal",
    "uninstall",
]
