"""Rendering the community namespace in the toolkit's own catalog schema.

The point of matching that schema exactly is that the client needs no second
code path: ``spikeforge_hub.catalog.load_catalog`` already validates this
shape, reports a malformed entry through ``issues()`` instead of dropping it,
and renders offline from a cached file. A hosted index in a different shape
would mean a second validator, which is a second place for the two to
disagree about what a valid entry is.

The only new value is ``source: "community"``. Everything else a curated
entry declares, a community entry declares too -- or leaves out honestly.
"""

from typing import Any

from hub_api.catalog.names import entry_id
from hub_api.catalog.trust import label_for
from hub_api.db.models.hub_model import HubModel
from hub_api.db.models.model_version import ModelVersion

#: Matches ``spikeforge_hub.catalog.SCHEMA_VERSION``. Bumping that without
#: bumping this serves clients a document they will refuse to load.
SCHEMA_VERSION = 1

#: What an uploaded artifact is, as far as this service is concerned. It
#: never opens the bundle, so the kind comes from the verification report
#: when there is one and is otherwise left unstated.
DEFAULT_KIND = "bundle"


def entry_for(
    model: HubModel,
    version: ModelVersion,
    handle: str,
    download_base: str,
) -> dict[str, Any]:
    """Return one catalog entry for a published version."""
    report = version.verification or {}
    return {
        "id": entry_id(handle, model.slug),
        "name": model.summary or model.slug,
        "framework": str(report.get("framework") or "spikeforge"),
        "kind": str(report.get("kind") or DEFAULT_KIND),
        "source": "community",
        "license": model.license,
        "notes": _notes(model, version),
        "url": f"{download_base.rstrip('/')}/{version.object_key}",
        "size_bytes": version.size_bytes,
        "dataset": model.dataset or None,
        "dataset_license": model.dataset_license or None,
        "dataset_attribution": model.dataset_attribution or None,
        "topology": report.get("topology"),
        "input_shape": report.get("input_shape"),
    }


def _notes(model: HubModel, version: ModelVersion) -> str:
    """Return the entry's notes, stating what was and was not checked.

    An uploader's description is theirs; the trust label is ours, and it goes
    in the same field so a reader cannot see one without the other.
    """
    parts = [f"Community upload, version {version.version}."]
    if model.description:
        parts.append(model.description)
    parts.append(f"Checks: {label_for(version)}.")
    return " ".join(parts)


def document(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Wrap ``entries`` in the catalog document the client expects."""
    return {"version": SCHEMA_VERSION, "entries": entries}
