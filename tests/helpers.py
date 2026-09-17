"""Small helpers shared by the upload tests."""

import hashlib
from collections.abc import AsyncIterator

from hub_api.uploads import UploadRequest


def payload(size_bytes: int, seed: bytes = b"a") -> bytes:
    """Return deterministic bytes of ``size_bytes``."""
    return (seed * size_bytes)[:size_bytes]


def digest(data: bytes) -> str:
    """Return the sha256 of ``data``."""
    return hashlib.sha256(data).hexdigest()


async def stream(data: bytes, chunk: int = 4096) -> AsyncIterator[bytes]:
    """Yield ``data`` in chunks, as a request body arrives."""
    for start in range(0, len(data), chunk):
        yield data[start : start + chunk]


def request_for(
    data: bytes,
    slug: str = "my-model",
    version: str = "1.0.0",
    sha256: str | None = None,
    size_bytes: int | None = None,
    license_id: str = "BSD-3-Clause",
) -> UploadRequest:
    """Return an upload request describing ``data``.

    ``sha256`` and ``size_bytes`` default to the truth about ``data`` and are
    overridable, because the interesting tests are the ones where a caller's
    declaration and its bytes disagree.
    """
    return UploadRequest(
        slug=slug,
        version=version,
        sha256=digest(data) if sha256 is None else sha256,
        size_bytes=len(data) if size_bytes is None else size_bytes,
        license=license_id,
    )
