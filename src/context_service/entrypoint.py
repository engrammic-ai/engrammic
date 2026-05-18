"""Entrypoint for distroless container - reads PORT from environment."""
import os
import sys

if __name__ == "__main__":
    port = os.environ.get("PORT", "8000")
    sys.exit(
        os.execvp(
            "python",
            [
                "python",
                "-m",
                "uvicorn",
                "context_service.api.app:create_app",
                "--factory",
                "--host",
                "0.0.0.0",
                "--port",
                port,
            ],
        )
    )
