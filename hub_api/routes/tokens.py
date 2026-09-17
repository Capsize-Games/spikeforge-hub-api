"""Personal access tokens."""

import uuid
from typing import Any

import sqlalchemy as sa
from fastapi import APIRouter

from hub_api.auth import credentials
from hub_api.db.base import utcnow
from hub_api.db.models.token import PAT, Token
from hub_api.deps import ConfigDep, CurrentUser, SessionDep
from hub_api.errors import NotFoundError
from hub_api.schemas.auth import TokenBody

router = APIRouter(prefix="/v1/tokens")


@router.get("")
async def index(user: CurrentUser, session: SessionDep) -> dict[str, Any]:
    """List this account's personal access tokens, without their values."""
    rows = await session.scalars(
        sa.select(Token).where(
            Token.user_id == user.id,
            Token.kind == PAT,
            Token.revoked_at.is_(None),
        )
    )
    return {"tokens": [_describe(row) for row in rows]}


def _describe(row: Token) -> dict[str, Any]:
    """Return a token's metadata. The value itself is unrecoverable."""
    return {
        "id": str(row.id),
        "name": row.name,
        "scopes": list(row.scopes),
        "created_at": row.created_at.isoformat(),
        "last_used_at": (
            row.last_used_at.isoformat() if row.last_used_at else None
        ),
    }


@router.post("", status_code=201)
async def create(
    body: TokenBody,
    user: CurrentUser,
    session: SessionDep,
    config: ConfigDep,
) -> dict[str, Any]:
    """Mint a token and return its value, which is shown only now."""
    plaintext = await credentials.issue_pat(
        session, user, body.scopes, body.name, config
    )
    await session.commit()
    return {
        "token": plaintext,
        "name": body.name,
        "scopes": body.scopes,
        "note": "this value is not recoverable; store it now",
    }


@router.delete("/{token_id}", status_code=200)
async def revoke(
    token_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> dict[str, str]:
    """Revoke one of this account's tokens."""
    row = await session.scalar(
        sa.select(Token).where(
            Token.id == token_id,
            Token.user_id == user.id,
            Token.kind == PAT,
        )
    )
    if row is None:
        raise NotFoundError("no such token for this account")
    row.revoked_at = utcnow()
    await session.commit()
    return {"status": "revoked"}
