"""Build the configured email sender."""

from functools import lru_cache

from hub_api.config import settings
from hub_api.email.base import EmailSender
from hub_api.email.smtp import SmtpEmailSender


@lru_cache(maxsize=1)
def email_sender() -> EmailSender:
    """Return the process-wide email sender.

    Built even when no SMTP host is configured: the failure happens inside
    ``send()``, at the moment an email is actually attempted, rather than
    here at wiring time -- mirroring how :func:`hub_api.storage.factory`
    builds its backend from settings without validating them up front.
    """
    config = settings()
    return SmtpEmailSender(
        host=config.smtp_host,
        port=config.smtp_port,
        username=config.smtp_username,
        password=config.smtp_password,
        sender=config.smtp_from,
        use_tls=config.smtp_use_tls,
    )
