"""The body the verification sandbox posts back."""

from pydantic import BaseModel, ConfigDict, Field


class VerificationReport(BaseModel):
    """The sandbox's pass/fail verdict for one version.

    Only ``passed`` is ever read back out of storage, by
    ``hub_api.catalog.trust.label_for``. Everything else -- ``reasons``, and
    whatever NIR/compat/energy summary the sandbox includes -- is opaque
    here and stored exactly as received (``extra="allow"`` keeps unknown
    fields rather than dropping them), so a change to the sandbox's report
    shape needs no change on this side.
    """

    model_config = ConfigDict(extra="allow")

    passed: bool
    #: Named reasons a human can act on. Required for a failing report by
    #: ``hub_api.uploads.verify.apply_report`` -- "verification failed" is
    #: not a reason, per the honesty bar in ``documentation/model-hub.md``.
    reasons: list[str] = Field(default_factory=list)
