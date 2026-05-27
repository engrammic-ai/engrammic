#!/usr/bin/env python3
"""Fetch secrets from GCP Secret Manager and export as env vars.

Usage: eval $(python fetch_secrets.py)
"""

import os
import sys

SECRETS = {
    "POSTGRES_PASSWORD": "engrammic-beta-postgres-password",
}


def main() -> None:
    try:
        from google.cloud import secretmanager
    except ImportError:
        return

    client = secretmanager.SecretManagerServiceClient()
    project = os.environ.get("GCP_PROJECT", "engrammic")

    for env_var, secret_id in SECRETS.items():
        if os.environ.get(env_var):
            continue
        try:
            name = f"projects/{project}/secrets/{secret_id}/versions/latest"
            response = client.access_secret_version(request={"name": name})
            value = response.payload.data.decode("UTF-8")
            print(f'export {env_var}="{value}"')
        except Exception as e:
            print(f"# Failed to fetch {secret_id}: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
