"""Which OAuth2 providers this deployment has enabled.

The set comes from configuration, not from code. A provider the library ships
a preset for is not offered until credentials are registered for it, which is
what lets the sign-in page render exactly the buttons that will work.
"""

from functools import lru_cache

from capsize_auth.oauth2 import ProviderRegistry

from hub_api.config import settings


@lru_cache(maxsize=1)
def providers() -> ProviderRegistry:
    """Return the process-wide provider registry."""
    config = settings()
    registry = ProviderRegistry(config.oauth_redirect_template)
    for name, credentials in config.oauth_providers.items():
        if len(credentials) != 2:
            raise ValueError(
                f"oauth_providers[{name!r}] must be "
                "[client_id, client_secret]"
            )
        registry.register_preset(name, credentials[0], credentials[1])
    return registry
