"""Test configuration: isolate custodian.models from heavy service-layer deps."""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Generator
from pathlib import Path
from types import ModuleType

import pytest

_SRC = Path(__file__).parent.parent / "src"


def _stub(name: str) -> ModuleType:
    m = ModuleType(name)
    sys.modules[name] = m
    return m


def _load_module_direct(dotted: str) -> ModuleType:
    """Load a module by file path, bypassing its package __init__."""
    parts = dotted.split(".")
    rel = Path(*parts).with_suffix(".py")
    path = _SRC / rel
    spec = importlib.util.spec_from_file_location(dotted, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[dotted] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _bootstrap_custodian_models() -> None:
    """Pre-load only the modules custodian.models actually needs."""
    if "context_service.custodian.models" in sys.modules:
        return

    # Import the real top-level package first so it is registered in sys.modules
    # as the true package object before we start adding sub-package stubs.
    import context_service  # noqa: F401

    # Stub only sub-packages that haven't been loaded yet.
    # Set __path__ so they behave as packages with submodules.
    for pkg in [
        "context_service.config",
        "context_service.core",
        "context_service.custodian",
        "context_service.extraction",
    ]:
        if pkg not in sys.modules:
            stub = ModuleType(pkg)
            parts = pkg.split(".")
            stub.__path__ = [str(_SRC / Path(*parts))]
            sys.modules[pkg] = stub
            # Also set the attribute on the parent so `import a.b.c` resolves.
            parent = sys.modules.get(".".join(parts[:-1]))
            if parent is not None:
                setattr(parent, parts[-1], stub)

    # Load config.settings directly so custodian.models can call get_settings().
    _load_module_direct("context_service.config.settings")

    # Load extraction.models directly (no config required).
    _load_module_direct("context_service.extraction.models")

    # Load custodian.models directly (bypasses custodian/__init__).
    _load_module_direct("context_service.custodian.models")


_bootstrap_custodian_models()


@pytest.fixture(autouse=True)
def reset_settings_cache() -> Generator[None, None, None]:
    """Reset the Settings singleton cache before and after each test.

    This prevents test pollution where one test's Settings modifications
    affect subsequent tests.
    """
    import context_service.config.settings as settings_mod

    settings_mod._settings_cache = None
    yield
    settings_mod._settings_cache = None
