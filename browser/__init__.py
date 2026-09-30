"""Browser-session decisions.

The model sees page text. Send, pay, delete, and publish wait. This
package does not start a browser.
"""

from browser.session import Decision, act, credential, placement

__all__ = [
    "Decision",
    "act",
    "credential",
    "placement",
]
