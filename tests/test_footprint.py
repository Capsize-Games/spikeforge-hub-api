"""The two limits that protect the host rather than the user."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from hub_api.config import Settings
from hub_api.db.models import User
from hub_api.errors import QuotaExceededError, ServiceUnavailableError
from hub_api.quota.footprint import check_footprint, check_free_space
from hub_api.storage.volume import VolumeStorage
from hub_api.uploads import receive, reserve
from tests.conftest import make_user
from tests.helpers import payload, request_for, stream

SIZE = 8192


async def test_an_empty_hub_has_room(
    session: AsyncSession, config: Settings
) -> None:
    await check_footprint(session, SIZE, config)


async def test_the_footprint_cap_refuses_an_upload_beyond_it(
    session: AsyncSession,
    storage: VolumeStorage,
    user: User,
    config: Settings,
) -> None:
    # The cap is service-wide, so it must bite regardless of whose allowance
    # has room -- the volume's other tenant does not care who filled it.
    tight = Settings(
        **{**config.model_dump(), "footprint_cap_bytes": SIZE + 1}
    )
    first = await reserve(
        session, storage, user, request_for(payload(SIZE)), tight
    )
    await receive(
        session, storage, first.upload_id, user.id, stream(payload(SIZE))
    )
    other = await make_user(session, config, handle="second")
    with pytest.raises(QuotaExceededError, match="service-wide"):
        await reserve(
            session,
            storage,
            other,
            request_for(payload(SIZE), slug="theirs"),
            tight,
        )


async def test_the_free_space_floor_refuses_an_upload(
    storage: VolumeStorage, config: Settings
) -> None:
    # A floor above the whole filesystem stands in for a full volume: the
    # refusal has to happen even when the cap says there is room.
    free = await storage.free_bytes()
    floored = Settings(
        **{**config.model_dump(), "volume_free_floor_bytes": free + SIZE}
    )
    with pytest.raises(ServiceUnavailableError, match="free space"):
        await check_free_space(storage, SIZE, floored)


async def test_the_floor_reports_the_numbers(
    storage: VolumeStorage, config: Settings
) -> None:
    free = await storage.free_bytes()
    floored = Settings(
        **{**config.model_dump(), "volume_free_floor_bytes": free + SIZE}
    )
    with pytest.raises(ServiceUnavailableError) as caught:
        await check_free_space(storage, SIZE, floored)
    assert caught.value.extra["floor_bytes"] == free + SIZE
