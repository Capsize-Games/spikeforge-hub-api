"""The email protocol every transport implements.

No vendor is chosen yet (plan §3.1): the transactional email provider for
this deployment is still an open decision. What exists today is stdlib
SMTP (:mod:`hub_api.email.smtp`), which is enough to unblock verification
and password reset without betting the shape of the interface on a
provider that has not been picked.
"""

from typing import Protocol


class EmailSendError(Exception):
    """Raised when an email could not be handed off for delivery."""


class EmailSender(Protocol):
    """Something that can deliver a plain-text email."""

    async def send(self, to: str, subject: str, body: str) -> None:
        """Send ``body`` to ``to``, or raise :class:`EmailSendError`."""
