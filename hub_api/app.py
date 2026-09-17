"""The FastAPI application.

Assembly only: routing, error rendering, and the CORS allow-list. Anything
with a decision in it lives in a module the tests can call directly.
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from hub_api.config import settings
from hub_api.errors import HubError
from hub_api.routes import (
    auth,
    health,
    me,
    models,
    tokens,
    uploads,
)


def build() -> FastAPI:
    """Return the configured application."""
    config = settings()
    app = FastAPI(
        title="spikeforge hub",
        version="0.1.0",
        description=(
            "Accounts, storage quotas, and community model hosting for "
            "spikeforge."
        ),
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["authorization", "content-type"],
    )
    app.add_exception_handler(HubError, _render_problem)
    for module in (health, auth, me, models, tokens, uploads):
        app.include_router(module.router)
    return app


async def _render_problem(
    request: Request, error: Exception
) -> JSONResponse:
    """Render a :class:`HubError` as an RFC 9457 problem document."""
    if not isinstance(error, HubError):
        raise error
    return JSONResponse(
        status_code=error.status,
        content=error.problem(str(request.url.path)),
        media_type="application/problem+json",
    )


app = build()
