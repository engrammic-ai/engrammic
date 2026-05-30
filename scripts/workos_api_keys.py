#!/usr/bin/env python3
"""WorkOS API key management script.

Create, list, and revoke API keys for organizations and users.

Usage:
    # Create org API key
    uv run python scripts/workos_api_keys.py create-org-key <org_id> --name "My Key" --permissions posts:read posts:write

    # Create user API key
    uv run python scripts/workos_api_keys.py create-user-key <user_id> --org <org_id> --name "User Key"

    # List org API keys
    uv run python scripts/workos_api_keys.py list-org-keys <org_id>

    # List user API keys
    uv run python scripts/workos_api_keys.py list-user-keys <user_id>

    # Validate an API key
    uv run python scripts/workos_api_keys.py validate <api_key_value>

    # Delete an API key
    uv run python scripts/workos_api_keys.py delete <key_id>

Environment:
    WORKOS_API_KEY: Your WorkOS API key (sk_test_... or sk_live_...)
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import httpx

WORKOS_API_BASE = "https://api.workos.com"


def get_api_key() -> str:
    key = os.getenv("WORKOS_API_KEY")
    if not key:
        print("Error: WORKOS_API_KEY environment variable not set", file=sys.stderr)
        sys.exit(1)
    return key


def make_request(
    method: str,
    path: str,
    *,
    json_body: dict | None = None,
    params: dict | None = None,
) -> dict | None:
    """Make authenticated request to WorkOS API."""
    api_key = get_api_key()
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    url = f"{WORKOS_API_BASE}{path}"

    with httpx.Client() as client:
        response = client.request(
            method,
            url,
            headers=headers,
            json=json_body,
            params=params,
            timeout=30.0,
        )

        if response.status_code == 204:
            return None

        if response.status_code >= 400:
            print(f"Error {response.status_code}: {response.text}", file=sys.stderr)
            sys.exit(1)

        return response.json()


def create_org_api_key(
    org_id: str,
    name: str,
    permissions: list[str] | None = None,
) -> dict:
    """Create an API key for an organization."""
    body: dict = {"name": name}
    if permissions:
        body["permissions"] = permissions

    result = make_request("POST", f"/organizations/{org_id}/api_keys", json_body=body)
    return result or {}


def create_user_api_key(
    user_id: str,
    name: str,
    org_id: str | None = None,
) -> dict:
    """Create an API key for a user."""
    body: dict = {"name": name}
    if org_id:
        body["organization_id"] = org_id

    result = make_request("POST", f"/user_management/users/{user_id}/api_keys", json_body=body)
    return result or {}


def list_org_api_keys(org_id: str, limit: int = 10) -> dict:
    """List API keys for an organization."""
    result = make_request("GET", f"/organizations/{org_id}/api_keys", params={"limit": limit})
    return result or {}


def list_user_api_keys(user_id: str, org_id: str | None = None, limit: int = 10) -> dict:
    """List API keys for a user."""
    params: dict = {"limit": limit}
    if org_id:
        params["organization_id"] = org_id

    result = make_request("GET", f"/user_management/users/{user_id}/api_keys", params=params)
    return result or {}


def validate_api_key(value: str) -> dict | None:
    """Validate an API key and return its metadata."""
    result = make_request("POST", "/api_keys/validations", json_body={"value": value})
    return result


def delete_api_key(key_id: str) -> None:
    """Delete (revoke) an API key. This cannot be undone."""
    make_request("DELETE", f"/api_keys/{key_id}")
    print(f"Deleted API key: {key_id}")


def main() -> None:
    parser = argparse.ArgumentParser(description="WorkOS API key management")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # create-org-key
    p_create_org = subparsers.add_parser("create-org-key", help="Create org API key")
    p_create_org.add_argument("org_id", help="Organization ID")
    p_create_org.add_argument("--name", required=True, help="Key name")
    p_create_org.add_argument(
        "--permissions", nargs="*", help="Permissions (e.g., posts:read posts:write)"
    )

    # create-user-key
    p_create_user = subparsers.add_parser("create-user-key", help="Create user API key")
    p_create_user.add_argument("user_id", help="User ID")
    p_create_user.add_argument("--name", required=True, help="Key name")
    p_create_user.add_argument("--org", help="Organization ID (optional)")

    # list-org-keys
    p_list_org = subparsers.add_parser("list-org-keys", help="List org API keys")
    p_list_org.add_argument("org_id", help="Organization ID")
    p_list_org.add_argument("--limit", type=int, default=10, help="Max results")

    # list-user-keys
    p_list_user = subparsers.add_parser("list-user-keys", help="List user API keys")
    p_list_user.add_argument("user_id", help="User ID")
    p_list_user.add_argument("--org", help="Filter by organization ID")
    p_list_user.add_argument("--limit", type=int, default=10, help="Max results")

    # validate
    p_validate = subparsers.add_parser("validate", help="Validate an API key")
    p_validate.add_argument("value", help="API key value to validate")

    # delete
    p_delete = subparsers.add_parser("delete", help="Delete (revoke) an API key")
    p_delete.add_argument("key_id", help="API key ID to delete")

    args = parser.parse_args()

    if args.command == "create-org-key":
        result = create_org_api_key(args.org_id, args.name, args.permissions)
        print(json.dumps(result, indent=2))
        if "value" in result:
            print(f"\n*** Save this key now - it won't be shown again: {result['value']}")

    elif args.command == "create-user-key":
        result = create_user_api_key(args.user_id, args.name, args.org)
        print(json.dumps(result, indent=2))
        if "value" in result:
            print(f"\n*** Save this key now - it won't be shown again: {result['value']}")

    elif args.command == "list-org-keys":
        result = list_org_api_keys(args.org_id, args.limit)
        print(json.dumps(result, indent=2))

    elif args.command == "list-user-keys":
        result = list_user_api_keys(args.user_id, args.org, args.limit)
        print(json.dumps(result, indent=2))

    elif args.command == "validate":
        result = validate_api_key(args.value)
        if result:
            print(json.dumps(result, indent=2))
        else:
            print("Invalid API key")
            sys.exit(1)

    elif args.command == "delete":
        delete_api_key(args.key_id)


if __name__ == "__main__":
    main()
