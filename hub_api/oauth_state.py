"""The OAuth2 ``state`` parameter, carrying the PKCE verifier with it.

State is a signed, short-lived token rather than a database row, so the flow
works across worker processes and expires on its own. It carries two things:

* the **provider** it was issued for, checked on the way back, so a state
  minted for one provider cannot be replayed against another's callback;
* the **PKCE verifier**, so the browser round-trip does not need a server-side
  record of it. The verifier only ever travels inside a token signed by this
  service, never in a URL a provider or an intermediary can read.
"""

from functools import lru_cache

from capsize_auth.tokens import STATE, TokenSigner, TokenTTLs

from hub_api.config import Settings, settings
from hub_api.errors import UnauthorizedError


@lru_cache(maxsize=1)
def _signer() -> TokenSigner:
    """Return the signer for this service's own short-lived tokens."""
    config = settings()
    if not config.token_secret:
        raise RuntimeError(
            "SPIKEFORGE_HUB_TOKEN_SECRET is unset. There is deliberately no "
            "development fallback: a fallback secret that reaches "
            "production is indistinguishable from having none. Generate one "
            'with: python -c "import secrets; print(secrets.token_hex(32))"'
        )
    return TokenSigner(
        secret=config.token_secret,
        ttls=TokenTTLs(state=config.authorization_code_ttl_seconds),
        issuer=config.base_url,
    )


def write_state(provider: str, verifier: str, config: Settings) -> str:
    """Return a signed state token for ``provider``."""
    return _signer().issue(STATE, subject=provider, pkce=verifier)


def read_state(state: str, provider: str, config: Settings) -> str:
    """Return the PKCE verifier carried by ``state``, or refuse it."""
    claims = _signer().decode(state, STATE)
    if claims is None:
        raise UnauthorizedError(
            "the sign-in attempt expired or could not be verified; "
            "start again"
        )
    if claims.get("sub") != provider:
        raise UnauthorizedError(
            "this sign-in attempt was for another provider"
        )
    verifier = claims.get("pkce")
    if not isinstance(verifier, str):
        raise UnauthorizedError("the sign-in attempt carried no PKCE verifier")
    return verifier
