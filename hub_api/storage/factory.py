"""Build the configured storage backend."""

from functools import lru_cache

from hub_api.config import settings
from hub_api.storage.base import Storage
from hub_api.storage.volume import VolumeStorage


@lru_cache(maxsize=1)
def storage() -> Storage:
    """Return the process-wide storage backend."""
    config = settings()
    return VolumeStorage(config.artifact_root, config.tmp_root)
