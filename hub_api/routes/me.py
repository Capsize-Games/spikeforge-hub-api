"""The signed-in account, and what it has used."""

from typing import Any

from fastapi import APIRouter

from hub_api.config import Settings
from hub_api.deps import ConfigDep, CurrentUser, SessionDep
from hub_api.quota import Usage, usage_for

router = APIRouter(prefix="/v1")


@router.get("/me")
async def me(
    user: CurrentUser, session: SessionDep, config: ConfigDep
) -> dict[str, Any]:
    """Return the account's profile and storage position."""
    usage = await usage_for(session, user.id, user.storage_limit)
    return {
        "handle": user.handle,
        "email": user.email,
        "email_verified": user.email_verified,
        "display_name": user.display_name,
        "avatar_url": user.avatar_url,
        "can_publish": _can_publish(user, config),
        "storage": _storage(usage),
        "limits": _limits(config),
    }


def _storage(usage: Usage) -> dict[str, int]:
    """Return the storage position, with the numbers a client needs."""
    return {
        "used_bytes": usage.used_bytes,
        "reserved_bytes": usage.reserved_bytes,
        "limit_bytes": usage.limit_bytes,
        "available_bytes": usage.available_bytes,
    }


def _limits(config: Settings) -> dict[str, int]:
    """Return the ceilings, so a client can refuse before we do."""
    return {
        "max_artifact_bytes": config.max_artifact_bytes,
        "max_models": config.max_models_per_user,
        "max_versions_per_model": config.max_versions_per_model,
        "max_uploads_per_day": config.max_uploads_per_day,
    }


def _can_publish(user: CurrentUser, config: ConfigDep) -> bool:
    """Return whether this account may publish right now."""
    if not user.email_verified:
        return False
    return config.publishing_gate == "open" or user.can_publish
