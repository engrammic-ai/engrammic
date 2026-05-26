"""Entrypoint for self-hosted container - runs migrations then starts server."""

import os
import subprocess
import sys


def run_migrations() -> bool:
    """Run alembic migrations. Returns True on success."""
    print("Running database migrations...")
    result = subprocess.run(
        ["python", "-m", "alembic", "upgrade", "head"],
        capture_output=False,
    )
    if result.returncode != 0:
        print("Migration failed!", file=sys.stderr)
        return False
    print("Migrations complete.")
    return True


if __name__ == "__main__":
    run_migrations_flag = os.environ.get("RUN_MIGRATIONS", "true").lower()

    if run_migrations_flag in ("true", "1", "yes") and not run_migrations():
        sys.exit(1)

    port = os.environ.get("PORT", "8000")
    print(f"Starting server on port {port}...")
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
