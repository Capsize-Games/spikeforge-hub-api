"""Environment-driven settings, with the plan's limits as the defaults.

Every default here is a decision recorded in ``plans/hub_accounts_plan.md`` in
the spikeforge repository, so changing one is a policy change and not a tuning
knob. Two in particular protect the *host* rather than the user:
``footprint_cap_bytes`` is the share of the attached volume this service may
ever claim, and ``volume_free_floor_bytes`` is the free space below which it
refuses uploads regardless of that cap -- the volume's other tenant is a
growing video library.
"""

from pathlib import Path
from typing import Literal

from capsize_commons.config import CapsizeSettings
from capsize_commons.config import get_settings as _cached_settings
from pydantic import Field
from pydantic_settings import SettingsConfigDict

_GIB = 1024**3
_MIB = 1024**2


class Settings(CapsizeSettings):
    """Runtime configuration read from ``SPIKEFORGE_HUB_*`` variables."""

    model_config = SettingsConfigDict(
        env_prefix="SPIKEFORGE_HUB_",
        env_file=".env",
        extra="ignore",
    )

    base_url: str = "https://hub.spikeforge.net"
    database_url: str = "postgresql+psycopg:///spikeforge_hub"

    #: Only ``volume`` exists today. The storage protocol is written so a
    #: presigned-PUT backend slots in without touching the upload flow.
    storage_backend: Literal["volume"] = "volume"
    artifact_root: Path = Path(
        "/mnt/HC_Volume_106876357/spikeforge/artifacts"
    )
    tmp_root: Path = Path("/mnt/HC_Volume_106876357/spikeforge/tmp")

    #: Service-wide ceiling on stored artifact bytes (§5.2).
    footprint_cap_bytes: int = 10 * _GIB
    #: Refuse uploads below this much free space on the artifact filesystem.
    volume_free_floor_bytes: int = 5 * _GIB

    #: Per-account defaults; ``users.storage_limit`` overrides the first.
    default_storage_limit: int = _GIB
    max_artifact_bytes: int = 256 * _MIB
    max_models_per_user: int = 50
    max_versions_per_model: int = 20
    max_uploads_per_day: int = 50

    reservation_ttl_seconds: int = 900
    session_absolute_ttl_seconds: int = 30 * 24 * 3600
    session_idle_ttl_seconds: int = 7 * 24 * 3600
    access_token_ttl_seconds: int = 3600
    refresh_token_ttl_seconds: int = 90 * 24 * 3600
    authorization_code_ttl_seconds: int = 300
    device_code_ttl_seconds: int = 900

    #: ``invite`` keeps publishing closed while moderation is one person
    #: (§12); ``open`` lets any signed-in account publish.
    publishing_gate: Literal["invite", "open"] = "invite"

    #: When True a committed version waits for the verification sandbox
    #: before it is published. Until that plane exists, setting it False
    #: publishes with the honest ``unchecked`` trust label rather than
    #: leaving every upload invisible.
    require_verification: bool = True

    #: Signing secret for this service's own tokens. Required in production;
    #: there is no development fallback, because a fallback secret that
    #: reaches production is indistinguishable from no secret at all.
    token_secret: str = ""

    #: ``{provider: [client_id, client_secret]}`` for the OAuth2 providers
    #: this deployment has enabled, as JSON. A provider absent here is not
    #: offered, so the sign-in page renders only buttons that work.
    oauth_providers: dict[str, list[str]] = Field(default_factory=dict)

    #: Shared secret the verification job signs its report callback with.
    verification_secret: str = ""

    #: Comma-separated origins allowed to call the API with credentials.
    cors_origins: str = "https://dash.spikeforge.net"

    #: Where published artifact bytes are served from. Downloads redirect
    #: here rather than streaming through this process: serving a file is
    #: the edge proxy's job, and the application has no reason to be in the
    #: path of a transfer it does not inspect.
    artifact_public_base: str = "https://cdn.spikeforge.net"

    cookie_name: str = "__Host-sfh_session"
    #: Off only for local HTTP development; ``__Host-`` requires Secure.
    cookie_secure: bool = True

    log_level: str = Field(default="info")
    #: Bind address. The default serves every interface, which is what a
    #: container behind a reverse proxy needs; it publishes no host port, so
    #: the only route in is the proxy.
    host: str = "0.0.0.0"
    port: int = 8878

    @property
    def oauth_redirect_template(self) -> str:
        """Return the callback URL shape shared by every provider."""
        return f"{self.base_url.rstrip('/')}/oauth/{{provider}}/callback"

    @property
    def allowed_origins(self) -> list[str]:
        """Return the CORS origin allow-list as a list."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


def settings() -> Settings:
    """Return the process-wide settings, read once."""
    return _cached_settings(Settings)
