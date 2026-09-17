"""Licence declarations, held to the curated catalog's own rule.

The toolkit's catalog accepts a concrete SPDX-style identifier or the
explicit ``unverified-candidate`` marker, and refuses free text. The same rule
applies here, for the same reason: "MIT-ish", "open source" and "see repo"
tell a person nothing about what they may do with an artifact, and a field
that accepts them stops being a declaration.

This is a *shape* check, not a claim that the licence is appropriate or that
the uploader had the right to choose it. Nothing in this service verifies
that, and the trust labels in the index must not imply it does.
"""

import re

from hub_api.errors import HubError

#: The marker the curated catalog uses for a licence that could not be read
#: from the publisher's own page. Carried here so an uploader can be honest
#: about not knowing rather than guessing.
UNVERIFIED_CANDIDATE = "unverified-candidate"

#: SPDX ids are letters, digits, dots, hyphens and plus signs; expressions
#: may join them with WITH/AND/OR.
_TOKEN = r"[A-Za-z0-9][A-Za-z0-9.+-]{0,62}"
_EXPRESSION = re.compile(
    rf"^{_TOKEN}(?: (?:WITH|AND|OR) {_TOKEN})*$"
)

#: Words that show up in place of a licence and are refused outright, so the
#: error can say something more useful than "malformed".
_NON_ANSWERS = frozenset(
    {
        "unknown",
        "none",
        "other",
        "custom",
        "proprietary",
        "see-repo",
        "see-readme",
        "tbd",
        "n/a",
        "na",
    }
)


class InvalidLicenseError(HubError):
    """A licence field is neither an SPDX-style id nor the marker."""

    status = 422
    code = "invalid_license"


def validate(raw: str, field: str = "license") -> str:
    """Return ``raw`` as a usable licence declaration, or refuse it."""
    value = raw.strip()
    if value == UNVERIFIED_CANDIDATE:
        return value
    if value.lower() in _NON_ANSWERS or not value:
        raise InvalidLicenseError(
            f"{field} must be a concrete SPDX-style identifier (for example "
            f"'BSD-3-Clause' or 'CC-BY-4.0'), or the exact marker "
            f"'{UNVERIFIED_CANDIDATE}' when the licence could not be read "
            f"from the publisher's own page",
            field=field,
        )
    if not _EXPRESSION.match(value):
        raise InvalidLicenseError(
            f"{field} is not a valid SPDX-style identifier or expression",
            field=field,
        )
    return value
