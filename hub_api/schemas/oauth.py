"""Bodies for the first-party desktop OAuth endpoints."""

from typing import Literal

from pydantic import BaseModel, Field


class OAuthTokenBody(BaseModel):
    """A request to redeem a grant for an access/refresh pair.

    Which fields are required depends on ``grant_type``; that is checked in
    ``hub_api.auth.grants`` rather than here, so the error names the grant
    that was missing something rather than a bare schema mismatch.
    """

    grant_type: Literal["authorization_code", "device_code"]
    code: str | None = Field(default=None, max_length=512)
    redirect_uri: str | None = Field(default=None, max_length=512)
    code_verifier: str | None = Field(default=None, max_length=256)
    device_code: str | None = Field(default=None, max_length=512)


class DeviceCodeStartBody(BaseModel):
    """A request to begin a device-flow sign-in attempt."""

    client_id: str = Field(min_length=1, max_length=64)
    scope: str = Field(default="", max_length=255)
