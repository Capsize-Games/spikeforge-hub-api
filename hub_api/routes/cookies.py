"""Setting and clearing the session cookie.

``__Host-`` is not decoration: it requires Secure, forbids a Domain
attribute, and pins the cookie to this exact host, which is what stops a
sibling subdomain from setting a session for this one. It only works over
HTTPS, so local HTTP development sets ``cookie_secure`` false and gets an
unprefixed name.
"""

from fastapi import Response

from hub_api.config import Settings


def cookie_name(config: Settings) -> str:
    """Return the cookie name valid for this deployment's scheme."""
    if config.cookie_secure:
        return config.cookie_name
    return config.cookie_name.removeprefix("__Host-")


def set_session(response: Response, value: str, config: Settings) -> None:
    """Attach the session cookie to ``response``."""
    response.set_cookie(
        cookie_name(config),
        value,
        max_age=config.session_absolute_ttl_seconds,
        httponly=True,
        secure=config.cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_session(response: Response, config: Settings) -> None:
    """Remove the session cookie."""
    response.delete_cookie(cookie_name(config), path="/")
