"""Nudge the verification sandbox when a version starts waiting on it.

The sandbox (a separate GitHub Actions runner in the ``spikeforge`` repo,
tracked there as issue #48) is triggered by a ``repository_dispatch``
event rather than by polling this service on a schedule:

- The event this repo fires happens exactly once, at the moment a version
  enters ``VERIFYING``. A poll would spend GitHub Actions minutes asking an
  idle endpoint "anything yet?" on a host this project deliberately keeps
  frugal (see AGENTS.md's shared-host invariants).
- A poll would also mean exposing a second, listing-shaped endpoint for the
  same untrusted-ish caller this issue's security note is already trying to
  keep narrowly scoped -- more surface than the one callback this issue
  adds.
- Plan Sect.7.2 already assumes ``repository_dispatch`` as the trigger; this
  keeps that decision and this implementation in agreement.

Disabled by leaving ``verification_dispatch_repo`` or
``verification_dispatch_token`` empty, which is the default: a deployment
with no sandbox wired up yet must not fail a commit over a webhook it has
nowhere to send.
"""

import logging
from typing import Any

import httpx

from hub_api.config import Settings
from hub_api.db.models.model_version import ModelVersion

_API_BASE = "https://api.github.com"
_logger = logging.getLogger(__name__)


async def notify(config: Settings, version: ModelVersion) -> None:
    """Fire a repository_dispatch event for ``version``, best-effort.

    A delivery failure here must not fail the commit that already moved
    the version into ``VERIFYING`` -- that state transition is the
    database's source of truth, and a lost webhook is recoverable by
    re-running the sandbox workflow by hand, which the commit is not.
    """
    if not (
        config.verification_dispatch_repo
        and config.verification_dispatch_token
    ):
        return
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                _dispatch_url(config),
                json=_payload(config, version),
                headers=_headers(config),
            )
            response.raise_for_status()
    except httpx.HTTPError:
        _logger.warning(
            "repository_dispatch for version %s did not deliver; the "
            "sandbox will need to be triggered by hand",
            version.id,
            exc_info=True,
        )


def _dispatch_url(config: Settings) -> str:
    """Return the GitHub API URL for this deployment's sandbox repo."""
    return (
        f"{_API_BASE}/repos/{config.verification_dispatch_repo}/dispatches"
    )


def _headers(config: Settings) -> dict[str, str]:
    """Return the headers GitHub's dispatch endpoint requires."""
    return {
        "Authorization": f"Bearer {config.verification_dispatch_token}",
        "Accept": "application/vnd.github+json",
    }


def _payload(config: Settings, version: ModelVersion) -> dict[str, Any]:
    """Return the client payload naming the one version to check."""
    callback = (
        f"{config.base_url.rstrip('/')}"
        f"/internal/v1/verifications/{version.id}"
    )
    return {
        "event_type": config.verification_dispatch_event,
        "client_payload": {
            "version_id": str(version.id),
            "sha256": version.sha256,
            "object_key": version.object_key,
            "callback_url": callback,
        },
    }
