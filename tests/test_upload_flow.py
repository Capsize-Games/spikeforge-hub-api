"""Reserve, receive, publish -- and every way it should be refused."""

from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from hub_api.auth import verification
from hub_api.config import Settings
from hub_api.db.base import utcnow
from hub_api.db.models import User
from hub_api.db.models.model_version import (
    PUBLISHED,
    RESERVED,
    UPLOADED,
    VERIFYING,
    ModelVersion,
)
from hub_api.db.models.verification_token import EMAIL_VERIFICATION
from hub_api.errors import (
    ConflictError,
    ForbiddenError,
    QuotaExceededError,
    UnprocessableUploadError,
)
from hub_api.quota import usage_for
from hub_api.storage.keys import object_key
from hub_api.storage.volume import VolumeStorage
from hub_api.uploads import publish, receive, reserve, sweep
from tests.conftest import make_user
from tests.helpers import digest, payload, request_for, stream

SIZE = 8192


async def test_a_full_upload_lands_and_publishes(
    session: AsyncSession,
    storage: VolumeStorage,
    user: User,
    config: Settings,
) -> None:
    data = payload(SIZE)
    slot = await reserve(
        session, storage, user, request_for(data), config
    )
    version = await receive(
        session, storage, slot.upload_id, user.id, stream(data)
    )
    assert version.state == UPLOADED
    assert version.object_key == object_key(digest(data))
    assert await storage.size(version.object_key) == SIZE

    published = await publish(session, version, config)
    assert published.state == PUBLISHED
    assert published.published_at is not None


async def test_the_allowance_moves_only_once_the_bytes_land(
    session: AsyncSession,
    storage: VolumeStorage,
    user: User,
    config: Settings,
) -> None:
    data = payload(SIZE)
    slot = await reserve(session, storage, user, request_for(data), config)

    reserved = await usage_for(session, user.id, user.storage_limit)
    assert reserved.used_bytes == 0
    assert reserved.reserved_bytes == SIZE

    await receive(session, storage, slot.upload_id, user.id, stream(data))
    committed = await usage_for(session, user.id, user.storage_limit)
    assert committed.used_bytes == SIZE
    assert committed.reserved_bytes == 0


async def test_an_upload_that_does_not_fit_is_refused_before_transfer(
    session: AsyncSession,
    storage: VolumeStorage,
    user: User,
    config: Settings,
) -> None:
    user.storage_limit = SIZE - 1
    with pytest.raises(QuotaExceededError) as caught:
        await reserve(
            session, storage, user, request_for(payload(SIZE)), config
        )
    # The refusal has to carry the numbers, or it is a support request.
    assert caught.value.extra["available_bytes"] == SIZE - 1
    assert caught.value.extra["requested_bytes"] == SIZE


async def test_an_oversized_artifact_is_refused(
    session: AsyncSession,
    storage: VolumeStorage,
    user: User,
    config: Settings,
) -> None:
    too_big = config.max_artifact_bytes + 1
    with pytest.raises(
        QuotaExceededError, match="larger than a single upload"
    ):
        await reserve(
            session,
            storage,
            user,
            request_for(b"", size_bytes=too_big, sha256=digest(b"")),
            config,
        )


async def test_bytes_beyond_the_reservation_are_cut_off(
    session: AsyncSession,
    storage: VolumeStorage,
    user: User,
    config: Settings,
) -> None:
    data = payload(SIZE)
    slot = await reserve(session, storage, user, request_for(data), config)
    # A caller who reserved 8 KiB and sends 32 KiB must be stopped during the
    # stream, not after it: the point of the cap is that the bytes never land.
    with pytest.raises(QuotaExceededError):
        await receive(
            session,
            storage,
            slot.upload_id,
            user.id,
            stream(payload(SIZE * 4)),
        )
    assert await storage.size(object_key(digest(data))) is None


async def test_a_wrong_digest_is_refused_and_the_name_freed(
    session: AsyncSession,
    storage: VolumeStorage,
    user: User,
    config: Settings,
) -> None:
    data = payload(SIZE)
    other = payload(SIZE, seed=b"b")
    slot = await reserve(
        session,
        storage,
        user,
        request_for(data, sha256=digest(other)),
        config,
    )
    with pytest.raises(UnprocessableUploadError, match="digest"):
        await receive(
            session, storage, slot.upload_id, user.id, stream(data)
        )
    # Nothing was stored, nothing was charged, and the version name is free
    # again so a caller who mis-declared can simply retry.
    usage = await usage_for(session, user.id, user.storage_limit)
    assert usage.used_bytes == 0
    assert usage.reserved_bytes == 0
    retried = await reserve(
        session, storage, user, request_for(data), config
    )
    assert retried.upload_id != slot.upload_id


async def test_a_short_body_is_refused(
    session: AsyncSession,
    storage: VolumeStorage,
    user: User,
    config: Settings,
) -> None:
    data = payload(SIZE)
    slot = await reserve(session, storage, user, request_for(data), config)
    with pytest.raises(UnprocessableUploadError, match="byte count"):
        await receive(
            session,
            storage,
            slot.upload_id,
            user.id,
            stream(payload(SIZE // 2)),
        )


async def test_a_version_cannot_be_republished(
    session: AsyncSession,
    storage: VolumeStorage,
    user: User,
    config: Settings,
) -> None:
    data = payload(SIZE)
    slot = await reserve(session, storage, user, request_for(data), config)
    await receive(session, storage, slot.upload_id, user.id, stream(data))
    with pytest.raises(ConflictError, match="immutable"):
        await reserve(session, storage, user, request_for(data), config)


async def test_an_unverified_address_may_not_publish(
    session: AsyncSession,
    storage: VolumeStorage,
    config: Settings,
) -> None:
    unverified = await make_user(
        session, config, handle="unproven", email_verified=False
    )
    with pytest.raises(ForbiddenError, match="verify your email"):
        await reserve(
            session, storage, unverified, request_for(payload(SIZE)), config
        )


async def test_redeeming_a_verification_token_lets_the_account_publish(
    session: AsyncSession,
    storage: VolumeStorage,
    config: Settings,
) -> None:
    unverified = await make_user(
        session, config, handle="nowproven", email_verified=False
    )
    token = await verification.mint(
        session, unverified, EMAIL_VERIFICATION, config
    )
    redeemed = await verification.redeem(
        session, token, EMAIL_VERIFICATION
    )
    # Redeeming only proves the token; the route sets the flag itself.
    redeemed.email_verified = True
    await session.flush()

    reservation = await reserve(
        session, storage, redeemed, request_for(payload(SIZE)), config
    )
    assert reservation.size_bytes == SIZE


async def test_the_invite_gate_refuses_an_uninvited_account(
    session: AsyncSession,
    storage: VolumeStorage,
    config: Settings,
) -> None:
    gated = Settings(
        **{**config.model_dump(), "publishing_gate": "invite"}
    )
    uninvited = await make_user(
        session, config, handle="waiting", can_publish=False
    )
    with pytest.raises(ForbiddenError, match="invite-only"):
        await reserve(
            session, storage, uninvited, request_for(payload(SIZE)), gated
        )


async def test_verification_holds_a_version_back_when_required(
    session: AsyncSession,
    storage: VolumeStorage,
    user: User,
    config: Settings,
) -> None:
    strict = Settings(
        **{**config.model_dump(), "require_verification": True}
    )
    data = payload(SIZE)
    slot = await reserve(session, storage, user, request_for(data), strict)
    version = await receive(
        session, storage, slot.upload_id, user.id, stream(data)
    )
    assert (await publish(session, version, strict)).state == VERIFYING


async def test_a_reservation_holds_no_bytes_yet(
    session: AsyncSession,
    storage: VolumeStorage,
    user: User,
    config: Settings,
) -> None:
    data = payload(SIZE)
    slot = await reserve(session, storage, user, request_for(data), config)
    version = await session.get(ModelVersion, slot.upload_id)
    assert version is not None
    assert version.state == RESERVED
    assert version.object_key == ""
    assert await storage.size(object_key(digest(data))) is None


async def test_an_expired_reservation_cannot_be_used_or_charged(
    session: AsyncSession,
    storage: VolumeStorage,
    user: User,
    config: Settings,
) -> None:
    data = payload(SIZE)
    slot = await reserve(session, storage, user, request_for(data), config)
    version = await session.get(ModelVersion, slot.upload_id)
    assert version is not None
    version.expires_at = utcnow() - timedelta(seconds=1)
    await session.flush()

    # An expired reservation stops holding the allowance on its own, with no
    # janitor run needed for the accounting to be right.
    usage = await usage_for(session, user.id, user.storage_limit)
    assert usage.reserved_bytes == 0
    with pytest.raises(ConflictError, match="expired"):
        await receive(
            session, storage, slot.upload_id, user.id, stream(data)
        )


async def test_the_janitor_reclaims_an_expired_reservation(
    session: AsyncSession,
    storage: VolumeStorage,
    user: User,
    config: Settings,
) -> None:
    slot = await reserve(
        session, storage, user, request_for(payload(SIZE)), config
    )
    version = await session.get(ModelVersion, slot.upload_id)
    assert version is not None
    version.expires_at = utcnow() - timedelta(seconds=1)
    await session.flush()
    assert await sweep(session, storage) == 1
    assert await session.get(ModelVersion, slot.upload_id) is None


async def test_the_janitor_leaves_a_live_reservation_alone(
    session: AsyncSession,
    storage: VolumeStorage,
    user: User,
    config: Settings,
) -> None:
    slot = await reserve(
        session, storage, user, request_for(payload(SIZE)), config
    )
    assert await sweep(session, storage) == 0
    assert await session.get(ModelVersion, slot.upload_id) is not None


async def test_identical_bytes_from_two_accounts_store_once(
    session: AsyncSession,
    storage: VolumeStorage,
    user: User,
    config: Settings,
) -> None:
    data = payload(SIZE)
    other = await make_user(session, config, handle="second")
    for account in (user, other):
        slot = await reserve(
            session, storage, account, request_for(data), config
        )
        await receive(
            session, storage, slot.upload_id, account.id, stream(data)
        )
    # Content-addressed, so one file -- but each owner is charged, so a
    # deletion by one cannot silently unshare the other's bytes.
    assert await storage.size(object_key(digest(data))) == SIZE
    for account in (user, other):
        usage = await usage_for(session, account.id, account.storage_limit)
        assert usage.used_bytes == SIZE
