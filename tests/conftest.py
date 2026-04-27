"""Test configuration: isolate custodian.models from heavy service-layer deps."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

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

    # Ensure package stubs exist so sub-module imports resolve.
    for pkg in ["context_service", "context_service.custodian", "context_service.extraction"]:
        sys.modules.setdefault(pkg, ModuleType(pkg))

    # Load extraction.models directly (no config required).
    _load_module_direct("context_service.extraction.models")

    # Load custodian.models directly (bypasses custodian/__init__).
    _load_module_direct("context_service.custodian.models")


_bootstrap_custodian_models()
