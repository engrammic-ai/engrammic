"""Entry point for running the application with `python -m context_service`."""

import os

import uvicorn

from context_service.config.settings import get_settings


def main() -> None:
    """Run the context service server."""
    settings = get_settings()

    reload = os.getenv("RELOAD", "").lower() in ("true", "1", "yes") or settings.reload

    uvicorn.run(
        "context_service.api.app:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        reload=reload,
    )


if __name__ == "__main__":
    main()
