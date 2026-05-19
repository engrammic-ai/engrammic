#!/usr/bin/env python3
"""Validate that all critical modules can be imported.

Run this at Docker build time to catch missing dependencies early.
Exit 0 if all imports succeed, exit 1 with details on failure.
"""

import os
import sys
from importlib import import_module

# Core modules required by all images
CORE_MODULES = [
    "context_service.config.settings",
    "context_service.stores.qdrant",
    "context_service.engine.memgraph_store",
]

# API-specific modules (requires auth group)
API_MODULES = [
    "context_service.entrypoint",
    "context_service.api.app",
    "context_service.auth.workos_authkit",
    "context_service.auth.workos_client",
    "context_service.api.auth_dep",
    "context_service.mcp.server",
]

# Dagster-specific modules
DAGSTER_MODULES = [
    "context_service.pipelines.definitions",
]

# Determine which modules to validate based on BUILD_TARGET env var
BUILD_TARGET = os.environ.get("BUILD_TARGET", "api")

if BUILD_TARGET == "dagster":
    CRITICAL_MODULES = CORE_MODULES + DAGSTER_MODULES
else:
    CRITICAL_MODULES = CORE_MODULES + API_MODULES


def validate_imports() -> int:
    """Import all critical modules and report failures."""
    failures: list[tuple[str, str]] = []

    print(f"Validating imports for BUILD_TARGET={BUILD_TARGET}")
    print(f"Checking {len(CRITICAL_MODULES)} modules...\n")

    for module_name in CRITICAL_MODULES:
        try:
            import_module(module_name)
            print(f"  OK: {module_name}")
        except ImportError as e:
            failures.append((module_name, str(e)))
            print(f"FAIL: {module_name} - {e}")
        except Exception as e:
            # Some modules may fail for non-import reasons (missing config, etc.)
            # That's OK at build time - we just want to verify deps are installed
            print(f"WARN: {module_name} - {type(e).__name__}: {e}")

    if failures:
        print(f"\n{len(failures)} import(s) failed:")
        for module, error in failures:
            print(f"  - {module}: {error}")
        return 1

    print(f"\nAll {len(CRITICAL_MODULES)} critical imports validated.")
    return 0


if __name__ == "__main__":
    sys.exit(validate_imports())
