"""Registration, sign-in, and provider linking."""

import pytest
from capsize_auth.oauth2 import OAuthProfile
from sqlalchemy.ext.asyncio import AsyncSession

from hub_api.auth import accounts, handles
from hub_api.config import Settings
from hub_api.errors import ConflictError, UnauthorizedError
from tests.conftest import make_user

STRONG = "quartz-lantern-9-drifting"


def profile(**overrides: object) -> OAuthProfile:
    fields: dict[str, object] = {
        "provider": "github",
        "subject": "5150",
        "email": "octocat@example.com",
        "email_verified": True,
        "username": "octocat",
    }
    fields.update(overrides)
    return OAuthProfile(
        provider=str(fields["provider"]),
        subject=str(fields["subject"]),
        email=str(fields["email"]),
        email_verified=bool(fields["email_verified"]),
        username=str(fields["username"]),
    )


async def test_registration_creates_a_usable_account(
    session: AsyncSession, config: Settings
) -> None:
    user = await accounts.register(
        session, "New.Person@Example.com ", STRONG, config
    )
    assert user.email == "new.person@example.com"
    # Dots are not handle-legal, so they become hyphens.
    assert user.handle == "new-person"
    assert user.password_hash is not None
    # An address is not proven by typing it, so publishing waits.
    assert not user.email_verified


async def test_a_weak_password_is_refused_with_a_reason(
    session: AsyncSession, config: Settings
) -> None:
    with pytest.raises(accounts.WeakPasswordError) as caught:
        await accounts.register(session, "a@example.com", "password", config)
    assert caught.value.detail != ""


async def test_registering_a_known_address_is_refused(
    session: AsyncSession, config: Settings
) -> None:
    await accounts.register(session, "a@example.com", STRONG, config)
    with pytest.raises(ConflictError, match="already exists"):
        await accounts.register(session, "A@Example.com", STRONG, config)


async def test_sign_in_accepts_the_right_password(
    session: AsyncSession, config: Settings
) -> None:
    await accounts.register(session, "a@example.com", STRONG, config)
    assert await accounts.sign_in(session, "A@example.com", STRONG)


async def test_sign_in_refuses_a_wrong_password(
    session: AsyncSession, config: Settings
) -> None:
    await accounts.register(session, "a@example.com", STRONG, config)
    with pytest.raises(UnauthorizedError) as caught:
        await accounts.sign_in(session, "a@example.com", "wrong")
    wrong_password = caught.value.detail

    with pytest.raises(UnauthorizedError) as caught:
        await accounts.sign_in(session, "nobody@example.com", STRONG)
    # The two refusals must be indistinguishable, or the form reveals which
    # addresses are registered.
    assert caught.value.detail == wrong_password


async def test_a_provider_login_creates_an_account(
    session: AsyncSession, config: Settings
) -> None:
    user = await accounts.link_or_create(session, profile(), config)
    assert user.handle == "octocat"
    assert user.email_verified


async def test_the_same_provider_account_returns_the_same_user(
    session: AsyncSession, config: Settings
) -> None:
    first = await accounts.link_or_create(session, profile(), config)
    again = await accounts.link_or_create(session, profile(), config)
    assert first.id == again.id


async def test_a_verified_address_adopts_the_existing_account(
    session: AsyncSession, config: Settings
) -> None:
    owner = await accounts.register(
        session, "octocat@example.com", STRONG, config
    )
    linked = await accounts.link_or_create(session, profile(), config)
    assert linked.id == owner.id


async def test_an_unverified_address_does_not_adopt_an_account(
    session: AsyncSession, config: Settings
) -> None:
    # Otherwise anyone who can set an address at a provider could take over
    # the hub account that owns it. It cannot become a second account on the
    # same address either, so the refusal has to say what to do instead.
    await accounts.register(session, "octocat@example.com", STRONG, config)
    with pytest.raises(ConflictError, match="link this provider"):
        await accounts.link_or_create(
            session, profile(email_verified=False), config
        )


async def test_an_unverified_address_still_creates_a_fresh_account(
    session: AsyncSession, config: Settings
) -> None:
    user = await accounts.link_or_create(
        session, profile(email_verified=False), config
    )
    assert user.email == "octocat@example.com"
    # Unverified at the provider means unverified here: publishing waits
    # until the address is proven.
    assert not user.email_verified


async def test_a_provider_with_no_address_cannot_create_an_account(
    session: AsyncSession, config: Settings
) -> None:
    with pytest.raises(ConflictError, match="did not return an email"):
        await accounts.link_or_create(session, profile(email=""), config)


async def test_two_providers_link_to_one_account(
    session: AsyncSession, config: Settings
) -> None:
    first = await accounts.link_or_create(session, profile(), config)
    second = await accounts.link_or_create(
        session,
        profile(provider="gitlab", subject="99", username="octocat"),
        config,
    )
    assert first.id == second.id


async def test_a_taken_handle_gets_a_suffix(
    session: AsyncSession, config: Settings
) -> None:
    # A different address, so this is a genuinely new account competing for
    # a handle rather than the adoption path.
    await make_user(session, config, handle="octocat")
    user = await accounts.link_or_create(
        session, profile(email="other@example.com"), config
    )
    assert user.handle == "octocat-2"


async def test_a_reserved_handle_is_never_allocated(
    session: AsyncSession, config: Settings
) -> None:
    allocated = await handles.allocate(session, "reference")
    assert allocated == "reference-2"


async def test_an_unusable_candidate_falls_back(
    session: AsyncSession, config: Settings
) -> None:
    assert await handles.allocate(session, "!!!", "") == "user"
