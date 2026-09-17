"""Run the service with uvicorn."""

import uvicorn

from hub_api.config import settings


def main() -> None:
    """Serve the application on the configured host and port."""
    config = settings()
    uvicorn.run(
        "hub_api.app:app",
        host=config.host,
        port=config.port,
        log_level=config.log_level,
    )


if __name__ == "__main__":
    main()
