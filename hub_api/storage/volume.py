"""Artifact storage on the host's attached volume.

Two invariants this module exists to hold:

* **Bytes never accumulate in memory.** A 256 MiB upload buffered on a host
  with roughly a gigabyte of available RAM is an out-of-memory kill that takes
  the other services on the box with it. Chunks are written straight through
  to a staging file, and the write itself is handed to a worker thread so the
  event loop is never blocked on disk.
* **A partially written artifact is never reachable under its final name.**
  Staging happens on the *same* filesystem as the destination so the promotion
  is an atomic rename rather than a copy.
"""

import asyncio
import hashlib
import os
import shutil
from collections.abc import AsyncIterator
from pathlib import Path

from hub_api.errors import QuotaExceededError
from hub_api.storage.blob import StoredBlob
from hub_api.storage.keys import object_key


class VolumeStorage:
    """Content-addressed artifact storage under a filesystem root."""

    def __init__(self, artifact_root: Path, tmp_root: Path) -> None:
        """Prepare the artifact and staging roots, creating them if absent."""
        self._artifacts = artifact_root
        self._tmp = tmp_root
        self._artifacts.mkdir(parents=True, exist_ok=True)
        self._tmp.mkdir(parents=True, exist_ok=True)

    def _staging(self, upload_id: str) -> Path:
        """Return the staging path for ``upload_id``."""
        return self._tmp / upload_id

    def _final(self, key: str) -> Path:
        """Return the stored path for ``key``."""
        return self._artifacts / key

    async def stage(
        self,
        upload_id: str,
        chunks: AsyncIterator[bytes],
        max_bytes: int,
    ) -> StoredBlob:
        """Stream ``chunks`` to staging, hashing and capping as they land."""
        try:
            return await self._write(
                self._staging(upload_id), chunks, max_bytes
            )
        except QuotaExceededError:
            await self.discard(upload_id)
            raise

    async def _write(
        self,
        path: Path,
        chunks: AsyncIterator[bytes],
        max_bytes: int,
    ) -> StoredBlob:
        """Write ``chunks`` to ``path``, refusing to pass ``max_bytes``."""
        digest = hashlib.sha256()
        written = 0
        with path.open("wb") as handle:
            async for chunk in chunks:
                written += len(chunk)
                if written > max_bytes:
                    raise QuotaExceededError(
                        "the upload is larger than the reservation allowed",
                        limit_bytes=max_bytes,
                    )
                digest.update(chunk)
                await asyncio.to_thread(handle.write, chunk)
            await asyncio.to_thread(handle.flush)
            await asyncio.to_thread(os.fsync, handle.fileno())
        return StoredBlob(sha256=digest.hexdigest(), size_bytes=written)

    async def promote(self, upload_id: str, sha256: str) -> str:
        """Move staged bytes to their content-addressed key and return it."""
        key = object_key(sha256)
        final = self._final(key)
        parent = final.parent
        await asyncio.to_thread(
            lambda: parent.mkdir(parents=True, exist_ok=True)
        )
        source = self._staging(upload_id)
        if final.exists():
            # Content-addressed: the bytes already stored are these bytes.
            await self.discard(upload_id)
            return key
        await asyncio.to_thread(os.replace, source, final)
        return key

    async def discard(self, upload_id: str) -> None:
        """Delete a staged transfer that will not be promoted."""
        staged = self._staging(upload_id)
        await asyncio.to_thread(lambda: staged.unlink(missing_ok=True))

    async def delete(self, key: str) -> None:
        """Delete a stored object, if it is still present."""
        path = self._final(key)
        await asyncio.to_thread(lambda: path.unlink(missing_ok=True))

    async def size(self, key: str) -> int | None:
        """Return a stored object's size, or None when it is absent."""
        path = self._final(key)
        if not path.exists():
            return None
        return await asyncio.to_thread(lambda: path.stat().st_size)

    async def free_bytes(self) -> int:
        """Return free space on the filesystem holding the artifacts."""
        usage = await asyncio.to_thread(shutil.disk_usage, self._artifacts)
        return usage.free

    def local_path(self, key: str) -> Path | None:
        """Return the readable local path for ``key``."""
        path = self._final(key)
        return path if path.exists() else None

    def signed_url(self, key: str, ttl_seconds: int) -> str | None:
        """Return None: this backend is served by the proxy instead."""
        return None
