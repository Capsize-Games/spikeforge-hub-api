"""Creating accounts, and signing in to them.

Two routes in: an address with a password, or a provider. They converge on one
``users`` row, so an account created through GitHub can later set a password,
and an account created with a password can link providers. That is why the
provider links live in their own table rather than as a column per provider.
"""

import sqlalchemy as sa
from capsize_auth import Principal, check_password_login, hash_password
from capsize_auth.oauth2 import OAuthProfile
from capsize_auth.password_policy import DEFAULT as PASSWORD_POLICY
from capsize_auth.password_policy import PasswordValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from hub_api.auth import handles
from hub_api.config import Settings
from hub_api.db.base import utcnow
from hub_api.db.models.identity import Identity
from hub_api.db.models.user import ACTIVE, User
from hub_api.errors import ConflictError, HubError, UnauthorizedError


class WeakPasswordError(HubError):
    """The chosen password does not meet the strength policy."""

    status = 422
    code = "weak_password"


def normalise_email(raw: str) -> str:
    """Return ``raw`` lower-cased and trimmed."""
    return raw.strip().lower()


def as_principal(user: User) -> Principal:
    """Return ``user`` in the shape the auth library expects."""
    return Principal(
        id=str(user.id),
        email=user.email,
        username=user.handle,
        status=user.state,
        token_version=user.token_version,
    )


async def by_email(session: AsyncSession, email: str) -> User | None:
    """Return the account with ``email``, or None."""
    found: User | None = await session.scalar(
        sa.select(User).where(User.email == normalise_email(email))
    )
    return found


async def register(
    session: AsyncSession, email: str, password: str, config: Settings
) -> User:
    """Create an account from an address and a password."""
    address = normalise_email(email)
    check_password_strength(password)
    if await by_email(session, address) is not None:
        raise ConflictError(
            "an account already exists for that address; sign in, or reset "
            "the password"
        )
    created = User(
        handle=await handles.allocate(session, address),
        email=address,
        password_hash=hash_password(password),
        storage_limit=config.default_storage_limit,
        can_publish=config.publishing_gate == "open",
    )
    session.add(created)
    await session.flush()
    return created


def check_password_strength(password: str) -> None:
    """Refuse a password the policy rejects, carrying its reason.

    Shared by every call site that accepts a new or changed password --
    register and password-reset confirm -- so neither can drift onto a
    weaker check.
    """
    try:
        PASSWORD_POLICY.check(password)
    except PasswordValidationError as error:
        raise WeakPasswordError(error.reason) from error


async def sign_in(
    session: AsyncSession, email: str, password: str
) -> User:
    """Return the account for valid credentials, or refuse.

    Every refusal is the same message. The library's outcome distinguishes a
    wrong password from a suspended account so this can be logged, but
    telling the form which one it was turns it into an account oracle.
    """
    found = await by_email(session, email)
    outcome = check_password_login(
        password,
        as_principal(found) if found else None,
        found.password_hash if found else None,
    )
    if not outcome.ok or found is None:
        raise UnauthorizedError("that address and password do not match")
    return found


async def link_or_create(
    session: AsyncSession, profile: OAuthProfile, config: Settings
) -> User:
    """Return the account for a provider profile, creating one if needed."""
    linked = await _by_identity(session, profile)
    if linked is not None:
        return linked
    existing = await _adoptable(session, profile)
    user = existing or await _from_profile(session, profile, config)
    session.add(
        Identity(
            user_id=user.id,
            provider=profile.provider,
            subject=profile.subject,
            email=profile.email,
            last_used_at=utcnow(),
        )
    )
    await session.flush()
    return user


async def _by_identity(
    session: AsyncSession, profile: OAuthProfile
) -> User | None:
    """Return the account already linked to this provider account."""
    identity = await session.scalar(
        sa.select(Identity).where(
            Identity.provider == profile.provider,
            Identity.subject == profile.subject,
        )
    )
    if identity is None:
        return None
    identity.last_used_at = utcnow()
    user = await session.get(User, identity.user_id)
    if user is None or user.state != ACTIVE:
        raise UnauthorizedError("the linked account is not active")
    return user


async def _adoptable(
    session: AsyncSession, profile: OAuthProfile
) -> User | None:
    """Return an existing account this provider login may attach to.

    Only when the provider states it verified the address. Adopting an
    account on an unverified address would let anyone who can set that
    address at a provider take over the account that owns it.
    """
    if not profile.email or not profile.email_verified:
        return None
    return await by_email(session, profile.email)


async def _check_address_free(
    session: AsyncSession, profile: OAuthProfile
) -> None:
    """Refuse a profile that cannot become a new account."""
    if not profile.email:
        raise ConflictError(
            f"{profile.provider} did not return an email address, so an "
            "account cannot be created from it. Sign up with an address "
            "first, then link this provider."
        )
    if await by_email(session, profile.email) is None:
        return
    # The address is taken and this login did not earn the right to adopt
    # it -- the provider did not say it was verified. A second account on
    # the same address is not possible, so say what can be done instead.
    raise ConflictError(
        "an account already exists for that address, and "
        f"{profile.provider} did not confirm you control it. Sign in to "
        "that account and link this provider from your settings."
    )


async def _from_profile(
    session: AsyncSession, profile: OAuthProfile, config: Settings
) -> User:
    """Create a new account from a provider profile."""
    await _check_address_free(session, profile)
    created = User(
        handle=await handles.allocate(
            session, profile.username, profile.email
        ),
        email=normalise_email(profile.email),
        email_verified=profile.email_verified,
        display_name=profile.display_name[:120],
        avatar_url=profile.avatar_url[:512],
        storage_limit=config.default_storage_limit,
        can_publish=config.publishing_gate == "open",
    )
    session.add(created)
    await session.flush()
    return created
