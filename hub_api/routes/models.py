"""Browsing and downloading the community namespace.

Every route here is anonymous: discovery and download need no account, which
is the point of a hub. Publishing is the only thing that requires one.
"""

from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import RedirectResponse

from hub_api.catalog import index, queries
from hub_api.catalog.trust import label_for
from hub_api.db.models.hub_model import HubModel
from hub_api.db.models.model_version import REJECTED, ModelVersion
from hub_api.deps import ConfigDep, SessionDep
from hub_api.errors import NotFoundError

router = APIRouter(prefix="/v1")


@router.get("/index.json")
async def catalog_index(
    session: SessionDep, config: ConfigDep
) -> dict[str, Any]:
    """Return the whole published namespace in the toolkit's schema.

    Served as one document because that is what the client caches and then
    loads offline through its existing validator.
    """
    rows = await queries.published(session, limit=1000)
    return index.document(
        [
            index.entry_for(
                model, version, handle, config.artifact_public_base
            )
            for model, version, handle in rows
        ]
    )


@router.get("/models")
async def list_models(
    session: SessionDep,
    config: ConfigDep,
    q: str = Query(default="", max_length=120),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    """List published versions, newest first."""
    rows = await queries.published(session, query=q, limit=limit)
    return {
        "models": [
            _summarise(model, version, handle)
            for model, version, handle in rows
        ]
    }


def _summarise(
    model: HubModel, version: ModelVersion, handle: str
) -> dict[str, Any]:
    """Return the listing shape for one published version."""
    return {
        "id": f"@{handle}/{model.slug}",
        "owner": handle,
        "name": model.slug,
        "version": version.version,
        "summary": model.summary,
        "license": model.license,
        "dataset": model.dataset,
        "size_bytes": version.size_bytes,
        "sha256": version.sha256,
        "trust": label_for(version),
        "published_at": (
            version.published_at.isoformat()
            if version.published_at
            else None
        ),
    }


@router.get("/models/{handle}/{slug}")
async def show_model(
    handle: str, slug: str, session: SessionDep
) -> dict[str, Any]:
    """Return a model's latest published version, or why it was rejected."""
    row = await queries.latest_version(session, handle, slug)
    if row is not None:
        return _shown(row)
    rejected = await queries.latest_rejected(session, handle, slug)
    if rejected is None:
        raise NotFoundError(f"no published model @{handle}/{slug}")
    return _rejection(rejected)


def _shown(row: queries.PublishedRow) -> dict[str, Any]:
    """Return the detail shape for a model's latest published version."""
    model, version, owner = row
    body = _summarise(model, version, owner)
    body["description"] = model.description
    body["dataset_license"] = model.dataset_license
    body["dataset_attribution"] = model.dataset_attribution
    body["verification"] = version.verification
    return body


def _rejection(row: queries.PublishedRow) -> dict[str, Any]:
    """Return why a model's most recent version did not publish.

    No trust label applies: the artifact was refused, not merely left
    unchecked, so this shape carries the named reasons instead --
    ``hub_api.uploads.verify`` refuses to store a failing report that has
    none, and a bare 404 here would bury them just as effectively as the
    bare "verification failed" message the honesty bar refuses.
    """
    model, version, owner = row
    report = version.verification or {}
    return {
        "id": f"@{owner}/{model.slug}",
        "owner": owner,
        "name": model.slug,
        "version": version.version,
        "state": REJECTED,
        "rejection_reasons": report.get("reasons", []),
        "verification": report,
    }


@router.get("/models/{handle}/{slug}/versions/{version}/download")
async def download(
    handle: str,
    slug: str,
    version: str,
    session: SessionDep,
    config: ConfigDep,
) -> RedirectResponse:
    """Redirect to the artifact's bytes, served by the edge proxy.

    The redirect rather than a streamed response is deliberate: this process
    has no reason to sit in the path of a file transfer it does not inspect,
    and on a host this size that matters. The target is content-addressed and
    public, which is all v1 needs -- a private model would require a signed
    path, and private models are out of scope.
    """
    row = await queries.one_version(session, handle, slug, version)
    if row is None:
        raise NotFoundError(
            f"no published version {version!r} of @{handle}/{slug}"
        )
    _model, found, _owner = row
    found.download_count += 1
    await session.commit()
    base = config.artifact_public_base.rstrip("/")
    return RedirectResponse(
        f"{base}/{found.object_key}", status_code=302
    )
