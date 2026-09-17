"""Requesting and confirming a password reset."""

from datetime import timedelta

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from hub_api.auth import accounts, sessions, verification
from hub_api.config import Settings
from hub_api.db.base import utcnow
from hub_api.db.models.session import Session
from hub_api.db.models.verification_token import (
    PASSWORD_RESET,
    VerificationToken,
)
from hub_api.errors import UnauthorizedError
from tests.conftest import RecordingEmailSender

STRONG = "quartz-lantern-9-drifting"
STRONGER = "opal-thicket-4-wandering"


async def test_a_reset_token_redeems_to_its_owner(
    session: AsyncSession, config: Settings
) -> None:
    user = await accounts.register(session, "a@example.com", STRONG, config)
    token = await verification.mint(session, user, PASSWORD_RESET, config)
    redeemed = await verification.redeem(session, token, PASSWORD_RESET)
    assert redeemed.id == user.id


async def test_a_reset_token_is_single_use(
    session: AsyncSession, config: Settings
) -> None:
    user = await accounts.register(session, "a@example.com", STRONG, config)
    token = await verification.mint(session, user, PASSWORD_RESET, config)
    await verification.redeem(session, token, PASSWORD_RESET)
    with pytest.raises(UnauthorizedError, match="already been used"):
        await verification.redeem(session, token, PASSWORD_RESET)


async def test_an_expired_reset_token_is_refused(
    session: AsyncSession, config: Settings
) -> None:
    user = await accounts.register(session, "a@example.com", STRONG, config)
    token = await verification.mint(session, user, PASSWORD_RESET, config)
    row = await session.scalar(
        sa.select(VerificationToken).where(
            VerificationToken.user_id == user.id
        )
    )
    assert row is not None
    row.expires_at = utcnow() - timedelta(seconds=1)
    await session.flush()
    with pytest.raises(UnauthorizedError, match="invalid or has expired"):
        await verification.redeem(session, token, PASSWORD_RESET)


async def test_sending_the_reset_email_carries_a_redeemable_link(
    session: AsyncSession, config: Settings, email: RecordingEmailSender
) -> None:
    user = await accounts.register(session, "a@example.com", STRONG, config)
    await verification.send_password_reset_email(session, user, config, email)
    assert len(email.sent) == 1
    sent = email.sent[0]
    assert sent.to == user.email
    token = sent.body.split("token=")[1].split()[0]
    redeemed = await verification.redeem(session, token, PASSWORD_RESET)
    assert redeemed.id == user.id


async def test_the_request_route_answers_alike_for_every_address(
    client: AsyncClient, session: AsyncSession, email: RecordingEmailSender
) -> None:
    # The same protection accounts.sign_in already gives the login form: a
    # different body for a known versus unknown address would make this
    # endpoint an account-existence oracle.
    await client.post(
        "/v1/auth/register",
        json={"email": "known@example.com", "password": STRONG},
    )
    email.sent.clear()

    known = await client.post(
        "/v1/auth/password/reset", json={"email": "known@example.com"}
    )
    unknown = await client.post(
        "/v1/auth/password/reset", json={"email": "nobody@example.com"}
    )
    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json()
    # Only the known address actually got a token minted and mailed.
    assert len(email.sent) == 1
    assert email.sent[0].to == "known@example.com"


async def test_confirming_sets_a_working_new_password(
    client: AsyncClient, session: AsyncSession, email: RecordingEmailSender
) -> None:
    await client.post(
        "/v1/auth/register",
        json={"email": "a@example.com", "password": STRONG},
    )
    email.sent.clear()
    await client.post(
        "/v1/auth/password/reset", json={"email": "a@example.com"}
    )
    token = email.sent[0].body.split("token=")[1].split()[0]

    resp = await client.post(
        "/v1/auth/password/reset/confirm",
        json={"token": token, "password": STRONGER},
    )
    assert resp.status_code == 200

    signed_in = await accounts.sign_in(session, "a@example.com", STRONGER)
    with pytest.raises(UnauthorizedError):
        await accounts.sign_in(session, "a@example.com", STRONG)
    assert signed_in.email == "a@example.com"


async def test_confirming_bumps_token_version_and_revokes_sessions(
    client: AsyncClient,
    session: AsyncSession,
    config: Settings,
    email: RecordingEmailSender,
) -> None:
    await client.post(
        "/v1/auth/register",
        json={"email": "a@example.com", "password": STRONG},
    )
    user = await accounts.by_email(session, "a@example.com")
    assert user is not None
    before = user.token_version
    await sessions.start(session, user, config)
    await session.commit()
    email.sent.clear()

    await client.post(
        "/v1/auth/password/reset", json={"email": "a@example.com"}
    )
    token = email.sent[0].body.split("token=")[1].split()[0]
    await client.post(
        "/v1/auth/password/reset/confirm",
        json={"token": token, "password": STRONGER},
    )

    await session.refresh(user)
    assert user.token_version == before + 1
    live = await session.scalar(
        sa.select(sa.func.count())
        .select_from(Session)
        .where(Session.user_id == user.id, Session.revoked_at.is_(None))
    )
    assert live == 0


async def test_confirming_rejects_a_weak_new_password(
    client: AsyncClient, session: AsyncSession, email: RecordingEmailSender
) -> None:
    await client.post(
        "/v1/auth/register",
        json={"email": "a@example.com", "password": STRONG},
    )
    email.sent.clear()
    await client.post(
        "/v1/auth/password/reset", json={"email": "a@example.com"}
    )
    token = email.sent[0].body.split("token=")[1].split()[0]

    resp = await client.post(
        "/v1/auth/password/reset/confirm",
        json={"token": token, "password": "password"},
    )
    assert resp.status_code == 422

    # The token is untouched by a refused attempt, so retrying with a
    # stronger password still works.
    retried = await client.post(
        "/v1/auth/password/reset/confirm",
        json={"token": token, "password": STRONGER},
    )
    assert retried.status_code == 200


async def test_confirming_rejects_an_unknown_token(
    client: AsyncClient, session: AsyncSession
) -> None:
    resp = await client.post(
        "/v1/auth/password/reset/confirm",
        json={"token": "bogus", "password": STRONGER},
    )
    assert resp.status_code == 401
