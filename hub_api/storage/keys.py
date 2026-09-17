"""Content-addressed object keys.

An artifact's key is derived from its own sha256 rather than from the model and
version that point at it, which makes deduplication free and makes the stored
file name self-verifying. The human-readable mapping lives in
``model_versions.object_key``; sharding on the first two hex characters keeps
any one directory small.
"""

import re

_SHA256 = re.compile(r"^[0-9a-f]{64}$")

#: Suffix every stored artifact carries, matching the toolkit's bundle format.
SUFFIX = ".spkf"


def is_sha256(value: str) -> bool:
    """Return whether ``value`` is a lowercase hex sha256 digest."""
    return bool(_SHA256.match(value))


def object_key(sha256: str) -> str:
    """Return the storage key for an artifact with digest ``sha256``."""
    if not is_sha256(sha256):
        raise ValueError(f"not a lowercase hex sha256 digest: {sha256!r}")
    return f"{sha256[:2]}/{sha256}{SUFFIX}"


def report_key(model_version_id: str) -> str:
    """Return the storage key for a version's verification report."""
    return f"reports/{model_version_id}/verification.json"
