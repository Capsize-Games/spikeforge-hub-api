"""What the service is willing to say it knows about an artifact.

The curated catalog's value is that every claim in it has been checked.
Community uploads are, by definition, claims nobody here has checked, so they
get their own vocabulary and it is deliberately modest:

``machine-checked``
    The bundle's own checksums matched, it loaded with weights-only
    deserialisation, it produced a NIR graph, the drift check passed, and an
    energy report was generated. It does **not** mean the accuracy claim was
    reproduced, the licence was read by a human, or the model is any good.

``unchecked``
    Stored and checksummed on arrival, and nothing more.

There is no ``verified`` label, because this service cannot earn that word.
Interface copy must not imply otherwise.
"""

from hub_api.db.models.model_version import PUBLISHED, ModelVersion

MACHINE_CHECKED = "machine-checked"
UNCHECKED = "unchecked"


def label_for(version: ModelVersion) -> str:
    """Return the trust label for ``version``."""
    report = version.verification or {}
    if version.state == PUBLISHED and report.get("passed") is True:
        return MACHINE_CHECKED
    return UNCHECKED
