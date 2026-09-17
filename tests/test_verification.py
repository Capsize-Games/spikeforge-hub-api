"""Minting and redeeming email-verification tokens, and the routes on top."""

from datetime import timedelta

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from hub_api.app import build
from hub_api.auth import accounts, verification
from hub_api.config import Settings
from hub_api.config import settings as settings_dep
from hub_api.db.base import utcnow
from hub_api.db.engine import db_session
from hub_api.db.models.verification_token import (
    EMAIL_VERIFICATION,
    PASSWORD_RESET,
    VerificationToken,
)
from hub_api.email.base import EmailSendError
from hub_api.email.factory import email_sender as email_sender_dep
from hub_api.errors import UnauthorizedError
from tests.conftest import RecordingEmailSender, make_user

STRONG = "quartz-lantern-9-drifting"


class FailingEmailSender:
    """An :class:`~hub_api.email.base.EmailSender` that always refuses.

    A second, real implementation of the protocol -- not a monkeypatch --
    used to exercise what a route does when the transport is down.
    """

    async def send(self, to: str, subject: str, body: str) -> None:
        """Raise, as if no relay could be reached."""
        raise EmailSendError("no relay reachable")


async def test_a_minted_token_redeems_to_its_owner(
    session: AsyncSession, config: Settings
) -> None:
    user = await make_user(session, config, email_verified=False)
    token = await verification.mint(session, user, EMAIL_VERIFICATION, config)
    redeemed = await verification.redeem(session, token, EMAIL_VERIFICATION)
    assert redeemed.id == user.id


async def test_a_token_cannot_be_redeemed_twice(
    session: AsyncSession, config: Settings
) -> None:
    user = await make_user(session, config, email_verified=False)
    token = await verification.mint(session, user, EMAIL_VERIFICATION, config)
    await verification.redeem(session, token, EMAIL_VERIFICATION)
    with pytest.raises(UnauthorizedError, match="already been used"):
        await verification.redeem(session, token, EMAIL_VERIFICATION)


async def test_an_expired_token_is_refused(
    session: AsyncSession, config: Settings
) -> None:
    user = await make_user(session, config, email_verified=False)
    token = await verification.mint(session, user, EMAIL_VERIFICATION, config)
    row = await session.scalar(
        sa.select(VerificationToken).where(
            VerificationToken.user_id == user.id
        )
    )
    assert row is not None
    row.expires_at = utcnow() - timedelta(seconds=1)
    await session.flush()
    with pytest.raises(UnauthorizedError, match="invalid or has expired"):
        await verification.redeem(session, token, EMAIL_VERIFICATION)


async def test_an_unknown_token_is_refused(
    session: AsyncSession, config: Settings
) -> None:
    with pytest.raises(UnauthorizedError, match="invalid or has expired"):
        await verification.redeem(session, "bogus", EMAIL_VERIFICATION)


async def test_a_token_is_scoped_to_its_purpose(
    session: AsyncSession, config: Settings
) -> None:
    user = await make_user(session, config, email_verified=False)
    token = await verification.mint(session, user, EMAIL_VERIFICATION, config)
    with pytest.raises(UnauthorizedError):
        await verification.redeem(session, token, PASSWORD_RESET)


async def test_sending_the_verification_email_carries_a_redeemable_link(
    session: AsyncSession, config: Settings, email: RecordingEmailSender
) -> None:
    user = await make_user(session, config, email_verified=False)
    await verification.send_verification_email(session, user, config, email)
    assert len(email.sent) == 1
    sent = email.sent[0]
    assert sent.to == user.email
    token = sent.body.split("token=")[1].split()[0]
    redeemed = await verification.redeem(session, token, EMAIL_VERIFICATION)
    assert redeemed.id == user.id


async def _client(
    session: AsyncSession, config: Settings, sender: object
) -> AsyncClient:
    """Build a client wired like ``tests.conftest``'s, with a chosen sender.

    A bespoke build rather than the shared ``client`` fixture, so a test can
    swap in :class:`FailingEmailSender` where the shared fixture always
    wires the successful :class:`RecordingEmailSender`.
    """
    app = build()
    app.dependency_overrides[db_session] = lambda: session
    app.dependency_overrides[settings_dep] = lambda: config
    app.dependency_overrides[email_sender_dep] = lambda: sender
    return AsyncClient(
        transport=ASGITransport(app=app), base_url="http://hub.test"
    )


async def test_registering_creates_the_account_even_if_mail_fails(
    session: AsyncSession, config: Settings
) -> None:
    # An unconfigured or unreachable mail transport must not make account
    # creation itself start failing.
    async with await _client(session, config, FailingEmailSender()) as c:
        resp = await c.post(
            "/v1/auth/register",
            json={"email": "new@example.com", "password": STRONG},
        )
    assert resp.status_code == 201
    assert resp.json()["email_verified"] is False
    assert await accounts.by_email(session, "new@example.com") is not None


async def test_verify_redeems_the_token_over_http(
    client: AsyncClient, session: AsyncSession, email: RecordingEmailSender
) -> None:
    await client.post(
        "/v1/auth/register",
        json={"email": "a@example.com", "password": STRONG},
    )
    token = email.sent[0].body.split("token=")[1].split()[0]
    resp = await client.post("/v1/auth/verify", json={"token": token})
    assert resp.status_code == 200
    assert resp.json() == {"email_verified": True}
    user = await accounts.by_email(session, "a@example.com")
    assert user is not None
    assert user.email_verified


async def test_resend_sends_a_fresh_email_while_unverified(
    client: AsyncClient, session: AsyncSession, email: RecordingEmailSender
) -> None:
    await client.post(
        "/v1/auth/register",
        json={"email": "a@example.com", "password": STRONG},
    )
    email.sent.clear()
    resp = await client.post("/v1/auth/verify/resend")
    assert resp.status_code == 200
    assert resp.json() == {"status": "verification email sent"}
    assert len(email.sent) == 1


async def test_resend_is_a_no_op_once_verified(
    client: AsyncClient, session: AsyncSession, email: RecordingEmailSender
) -> None:
    await client.post(
        "/v1/auth/register",
        json={"email": "a@example.com", "password": STRONG},
    )
    user = await accounts.by_email(session, "a@example.com")
    assert user is not None
    user.email_verified = True
    await session.commit()
    email.sent.clear()

    resp = await client.post("/v1/auth/verify/resend")
    assert resp.status_code == 200
    assert resp.json() == {"status": "already verified"}
    assert email.sent == []


async def test_resend_returns_503_when_the_transport_fails(
    session: AsyncSession, config: Settings
) -> None:
    app = build()
    app.dependency_overrides[db_session] = lambda: session
    app.dependency_overrides[settings_dep] = lambda: config
    app.dependency_overrides[email_sender_dep] = lambda: RecordingEmailSender()
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://hub.test"
    ) as c:
        await c.post(
            "/v1/auth/register",
            json={"email": "a@example.com", "password": STRONG},
        )
        app.dependency_overrides[email_sender_dep] = (
            lambda: FailingEmailSender()
        )
        resp = await c.post("/v1/auth/verify/resend")
    assert resp.status_code == 503
