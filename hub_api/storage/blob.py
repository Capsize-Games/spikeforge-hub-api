"""What a completed byte transfer is known to be."""

from dataclasses import dataclass


@dataclass(frozen=True)
class StoredBlob:
    """The measured result of streaming bytes into staging.

    ``sha256`` is computed by this service while the bytes arrive, never taken
    from the client: the caller's claimed digest is an assertion and this is
    the fact it gets compared against.
    """

    sha256: str
    size_bytes: int
