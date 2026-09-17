"""Handles, slugs, and version strings.

The community namespace shares a list with the curated catalog, whose ids
look like ``reference/mnist-fc-small`` and ``nir/conv_net``. A community
entry is ``@handle/slug``, and the ``@`` is what keeps the two unambiguous in
a list, a URL, and a command-line argument.

Every prefix the curated catalog uses is reserved, so no account can publish
something that reads like a curated entry.
"""

import re

from hub_api.errors import ConflictError, HubError

_HANDLE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,37}[a-z0-9])?$")
_SLUG = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{0,62}[a-z0-9])?$")
_VERSION = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9.+_-]{0,63}$")

#: Handles no account may take: the curated catalog's own prefixes, the
#: framework names it publishes under, and the service's own route names.
RESERVED_HANDLES = frozenset(
    {
        "reference",
        "bundled",
        "nir",
        "snntorch",
        "spikingjelly",
        "norse",
        "lava",
        "spikeforge",
        "capsize",
        "admin",
        "api",
        "hub",
        "internal",
        "oauth",
        "login",
        "logout",
        "activate",
        "settings",
        "about",
        "help",
        "support",
        "static",
        "assets",
        "docs",
        "www",
        "root",
        "me",
        "new",
    }
)


class InvalidNameError(HubError):
    """A handle, slug, or version does not match its shape."""

    status = 422
    code = "invalid_name"


def normalise_handle(raw: str) -> str:
    """Return ``raw`` as a valid handle, or refuse it.

    Lower-cased on the way in so the unique index does the right thing and
    two accounts cannot differ only by case -- which would let one
    impersonate the other.
    """
    handle = raw.strip().lower()
    if not _HANDLE.match(handle):
        raise InvalidNameError(
            "a handle is 1-39 characters of lowercase letters, digits and "
            "hyphens, and may not start or end with a hyphen"
        )
    if handle in RESERVED_HANDLES:
        raise ConflictError(f"the handle {handle!r} is reserved")
    return handle


def validate_slug(raw: str) -> str:
    """Return ``raw`` as a valid model slug, or refuse it."""
    slug = raw.strip().lower()
    if not _SLUG.match(slug):
        raise InvalidNameError(
            "a model name is 1-64 characters of lowercase letters, digits, "
            "dots, underscores and hyphens, and may not start or end with a "
            "separator"
        )
    return slug


def validate_version(raw: str) -> str:
    """Return ``raw`` as a valid version string, or refuse it."""
    version = raw.strip()
    if not _VERSION.match(version):
        raise InvalidNameError(
            "a version is 1-64 characters of letters, digits, dots, plus "
            "signs, underscores and hyphens, starting with a letter or digit"
        )
    return version


def entry_id(handle: str, slug: str) -> str:
    """Return the catalog id for a community model."""
    return f"@{handle}/{slug}"
