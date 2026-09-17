"""HMAC verification for signed service-to-service callbacks.

A caller here does not hold a credential we stored a hash of, the way a
bearer token does (:mod:`hub_api.auth.credentials`); it holds a secret
shared out of band and signs each request body with it. The comparison
still follows the same rule as an opaque token's
``capsize_auth.tokens.opaque.matches``: compare with
:func:`hmac.compare_digest` rather than ``==``, so a wrong guess cannot be
narrowed down by how long the comparison took.
"""

import hashlib
import hmac


def sign(secret: str, body: bytes) -> str:
    """Return the hex HMAC-SHA256 of ``body``, keyed with ``secret``."""
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def matches(secret: str, body: bytes, presented: str) -> bool:
    """Return whether ``presented`` is a valid signature of ``body``."""
    return hmac.compare_digest(sign(secret, body), presented)
