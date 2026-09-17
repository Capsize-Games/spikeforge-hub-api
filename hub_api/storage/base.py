"""The storage protocol every backend implements.

One implementation exists today (:mod:`hub_api.storage.volume`, writing to the
host's attached volume). The protocol is deliberately shaped so a
presigned-upload backend can be added without changing the two-phase upload
flow: ``stage`` is where the bytes land before they are named, ``promote``
gives them their content-addressed name, and ``signed_url`` is the hand-off a
remote backend would return to the client instead.
"""

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Protocol

from hub_api.storage.blob import StoredBlob


class Storage(Protocol):
    """Byte storage for artifacts, addressed by content."""

    async def stage(
        self,
        upload_id: str,
        chunks: AsyncIterator[bytes],
        max_bytes: int,
    ) -> StoredBlob:
        """Stream ``chunks`` into staging, hashing and capping as they land.

        Raises :class:`~hub_api.errors.QuotaExceededError` as soon as
        the stream passes ``max_bytes``, without waiting for it to end.
        """

    async def promote(self, upload_id: str, sha256: str) -> str:
        """Move staged bytes to their content-addressed key and return it."""

    async def discard(self, upload_id: str) -> None:
        """Delete a staged transfer that will not be promoted."""

    async def delete(self, key: str) -> None:
        """Delete a stored object, if it is still present."""

    async def size(self, key: str) -> int | None:
        """Return a stored object's size, or None when it is absent."""

    async def free_bytes(self) -> int:
        """Return free space on the filesystem holding the artifacts."""

    def local_path(self, key: str) -> Path | None:
        """Return a readable local path, when the backend has one.

        The volume backend returns a path so downloads can be handed to the
        edge proxy; a remote backend returns None and answers ``signed_url``
        instead.
        """

    def signed_url(self, key: str, ttl_seconds: int) -> str | None:
        """Return a time-limited direct URL, when the backend offers one."""
