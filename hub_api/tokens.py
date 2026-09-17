"""The service's token primitives, taken from ``capsize-auth``.

Re-exported through one module so the dependency has a single import site: if
the opaque-token implementation is ever swapped, this is the file that
changes.
"""

from capsize_auth.tokens import OpaqueToken, hash_token, new_token
from capsize_auth.tokens.opaque import matches

__all__ = ["OpaqueToken", "hash_token", "matches", "new_token"]
