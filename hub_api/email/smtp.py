"""Sending email through stdlib SMTP, off the event loop.

``smtplib`` is a blocking API: opening a connection, negotiating TLS, and
handing off a message all block the calling thread for however long the
conversation takes. Run directly inside a coroutine that would stall the
whole event loop, so every send happens in a worker thread instead.
"""

import asyncio
import smtplib
from email.message import EmailMessage

from hub_api.email.base import EmailSendError


class SmtpEmailSender:
    """Deliver mail through a configured SMTP relay.

    Raises :class:`~hub_api.email.base.EmailSendError` rather than
    pretending to succeed when no host is configured -- an unconfigured
    transactional email provider (plan §3.1) is a launch blocker for the
    password route, and pretending otherwise would hide that.
    """

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        sender: str,
        use_tls: bool = True,
    ) -> None:
        """Store the SMTP endpoint and credentials sends go out with."""
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._sender = sender
        self._use_tls = use_tls

    async def send(self, to: str, subject: str, body: str) -> None:
        """Send a plain-text email, raising if it cannot be delivered."""
        if not self._host:
            raise EmailSendError(
                "no SMTP host is configured; set "
                "SPIKEFORGE_HUB_SMTP_HOST to enable outbound email"
            )
        message = _message(self._sender, to, subject, body)
        await asyncio.to_thread(self._send_sync, message)

    def _send_sync(self, message: EmailMessage) -> None:
        """Deliver ``message`` over a blocking SMTP connection."""
        try:
            with smtplib.SMTP(self._host, self._port, timeout=10) as client:
                if self._use_tls:
                    client.starttls()
                if self._username:
                    client.login(self._username, self._password)
                client.send_message(message)
        except (OSError, smtplib.SMTPException) as error:
            raise EmailSendError(f"could not send email: {error}") from error


def _message(
    sender: str, to: str, subject: str, body: str
) -> EmailMessage:
    """Return a plain-text email ready to hand to an SMTP client."""
    message = EmailMessage()
    message["From"] = sender
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    return message
