#!/usr/bin/env python3
"""Sync .env secrets to GCP Secret Manager."""

import os
import subprocess
import sys
from pathlib import Path

ENV_TO_SECRET_MAP = {
    "POSTGRES_PASSWORD": "postgres-password",
    "MEMGRAPH_PASSWORD": "memgraph-password",
    "ANTHROPIC_API_KEY": "anthropic-api-key",
    "OPENAI_API_KEY": "openai-api-key",
    "GEMINI_API_KEY": "google-api-key",
    "WORKOS_API_KEY": "workos-api-key",
}


def load_env(env_path: Path) -> dict[str, str]:
    """Parse .env file into dict."""
    values = {}
    if not env_path.exists():
        return values

    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if value:
            values[key] = value
    return values


def sync_secret(project: str, env: str, secret_name: str, value: str) -> bool:
    """Push a secret value to Secret Manager."""
    full_name = f"engrammic-{env}-{secret_name}"

    try:
        result = subprocess.run(
            [
                "gcloud",
                "secrets",
                "versions",
                "add",
                full_name,
                "--project",
                project,
                "--data-file=-",
            ],
            input=value.encode(),
            capture_output=True,
        )
        if result.returncode == 0:
            print(f"  {full_name}: synced")
            return True
        else:
            stderr = result.stderr.decode()
            if "NOT_FOUND" in stderr:
                print(f"  {full_name}: secret not found (run pulumi up first)")
            else:
                print(f"  {full_name}: failed - {stderr.strip()}")
            return False
    except Exception as e:
        print(f"  {full_name}: error - {e}")
        return False


def main():
    project = os.environ.get("GCP_PROJECT", "engrammic")
    env = os.environ.get("ENVIRONMENT", "dev")
    env_path = Path(".env")

    if not env_path.exists():
        print("No .env file found")
        sys.exit(1)

    print(f"Syncing secrets to {project} ({env} environment)...\n")

    env_values = load_env(env_path)
    synced = 0
    skipped = 0

    for env_key, secret_name in ENV_TO_SECRET_MAP.items():
        value = env_values.get(env_key, "")
        if not value:
            print(f"  {secret_name}: skipped (empty in .env)")
            skipped += 1
            continue
        if sync_secret(project, env, secret_name, value):
            synced += 1

    print(f"\nDone: {synced} synced, {skipped} skipped")


if __name__ == "__main__":
    main()
