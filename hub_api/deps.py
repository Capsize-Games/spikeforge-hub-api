"""FastAPI dependencies: settings, storage, a session, and the caller.

A caller arrives one of two ways -- a browser with a session cookie, or a
client with a bearer credential -- and both resolve to the same account. The
cookie is checked second so a bearer token always wins when both are present:
a scripted call should not silently borrow the scope of whoever happens to be
signed in to the same browser.
"""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from hub_api.auth import credentials, sessions
from hub_api.config import Settings, settings
from hub_api.db.engine import db_session
from hub_api.db.models.user import User
from hub_api.errors import ForbiddenError, UnauthorizedError
from hub_api.routes.cookies import cookie_name
from hub_api.storage.base import Storage
from hub_api.storage.factory import storage

SessionDep = Annotated[AsyncSession, Depends(db_session)]
ConfigDep = Annotated[Settings, Depends(settings)]
StorageDep = Annotated[Storage, Depends(storage)]


def _bearer(request: Request) -> str | None:
    """Return the presented bearer credential, if any."""
    header = request.headers.get("authorization", "")
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return None
    return value.strip()


async def current_user(
    request: Request, session: SessionDep, config: ConfigDep
) -> User:
    """Return the authenticated account, or refuse the request."""
    presented = _bearer(request)
    if presented is not None:
        user, token = await credentials.resolve(session, presented)
        request.state.scopes = list(token.scopes)
        return user
    cookie = request.cookies.get(cookie_name(config))
    if cookie:
        found = await sessions.resolve(session, cookie, config)
        if found is not None:
            # A browser session is the account itself, so it carries every
            # scope a credential could have been granted.
            request.state.scopes = list(credentials.ALL_SCOPES)
            return found
    raise UnauthorizedError("sign in to use this endpoint")


CurrentUser = Annotated[User, Depends(current_user)]


async def optional_user(
    request: Request, session: SessionDep, config: ConfigDep
) -> User | None:
    """Return the caller when there is one, without refusing anonymity."""
    try:
        return await current_user(request, session, config)
    except UnauthorizedError:
        return None


MaybeUser = Annotated[User | None, Depends(optional_user)]


def _scope_guard(scope: str) -> Callable[..., Awaitable[User]]:
    """Return a dependency callable demanding ``scope`` of the caller."""

    async def guard(request: Request, user: CurrentUser) -> User:
        """Refuse a credential that was not granted ``scope``."""
        granted = getattr(request.state, "scopes", [])
        if scope not in granted:
            raise ForbiddenError(
                f"this credential does not carry the {scope!r} scope",
                required_scope=scope,
            )
        return user

    return guard


#: A caller holding the write scope. Built once at import: a dependency
#: constructed inside a signature default is evaluated per definition, which
#: is the shape of bug that leaves one route silently unguarded.
WriteUser = Annotated[User, Depends(_scope_guard(credentials.WRITE))]
ReadUser = Annotated[User, Depends(_scope_guard(credentials.READ))]
