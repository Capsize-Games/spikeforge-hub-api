"""Bodies for the identity endpoints."""

from pydantic import BaseModel, EmailStr, Field, field_validator

from hub_api.auth.credentials import READ, WRITE


class RegisterBody(BaseModel):
    """An address and a password for a new account."""

    email: EmailStr
    #: No maximum below argon2's own: a long passphrase is a good password,
    #: and a low cap on length is a policy that makes passwords worse.
    password: str = Field(min_length=8, max_length=1024)


class LoginBody(BaseModel):
    """Credentials for an existing account."""

    email: EmailStr
    password: str = Field(min_length=1, max_length=1024)


class TokenBody(BaseModel):
    """A request to mint a personal access token."""

    name: str = Field(default="", max_length=120)
    scopes: list[str] = Field(default_factory=lambda: [READ])

    @field_validator("scopes")
    @classmethod
    def _known_scopes(cls, value: list[str]) -> list[str]:
        """Refuse a scope that does not exist.

        A validator rather than a check inside the route, so an unknown
        scope is a request-validation failure with the offending field
        named -- not an exception raised after the request was accepted.
        """
        allowed = {READ, WRITE}
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise ValueError(
                f"unknown scopes: {', '.join(unknown)}; known scopes are "
                f"{READ} and {WRITE}"
            )
        return sorted(set(value))


class RefreshBody(BaseModel):
    """A refresh token presented for rotation."""

    refresh_token: str = Field(min_length=1, max_length=512)
