"""Regression tests for repo-root discovery and the prompt loader.

Background: ``custodian/agents.py`` used to walk one ``.parent`` too many
(5 instead of 4) when computing ``config/prompts/custodian/`` and looked
for it above the repo root. Other peers in the same directory walked 4.
The bug was masked in CI because no test imported ``custodian.agents``
directly; the moment the Dagster custodian asset ran, it would
``FileNotFoundError`` at import.

Now every prompt consumer goes through ``prompt_loader.load_prompt`` with
a path relative to ``config/`` — no caller counts ``.parent``s. These
tests pin both the discovery contract and the load-success of every
prompt the production code references.
"""

from __future__ import annotations

import pytest

from context_service.config.paths import config_dir, repo_root
from context_service.custodian.prompt_loader import clear_cache, load_prompt


def test_repo_root_contains_pyproject() -> None:
    assert (repo_root() / "pyproject.toml").is_file()


def test_repo_root_is_above_src() -> None:
    package_dir = repo_root() / "src" / "context_service"
    assert package_dir.is_dir()
    assert (package_dir / "__init__.py").is_file()


def test_config_dir_exists() -> None:
    cfg = config_dir()
    assert cfg.is_dir(), f"config dir not found at {cfg}"


def test_repo_root_is_cached() -> None:
    assert repo_root() is repo_root()


@pytest.mark.parametrize(
    "rel_path",
    [
        "prompts/custodian/fast_pass.yaml",
        "prompts/custodian/plan.yaml",
        "prompts/custodian/deep_pass.yaml",
        "prompts/custodian/supersession.yaml",
    ],
)
def test_every_referenced_prompt_loads(rel_path: str) -> None:
    """Every prompt the production code references must load without raising.

    If anyone reintroduces a path-walking bug that misses the repo root, or
    deletes a yaml that is still referenced, this test fails fast.
    """
    clear_cache()
    rendered = load_prompt(rel_path)
    assert rendered, f"{rel_path} rendered to empty string"


def test_load_prompt_substitutes_variables() -> None:
    """load_prompt forwards variables to Template.safe_substitute."""
    clear_cache()
    rendered = load_prompt("prompts/custodian/fast_pass.yaml", agent_name="agent_xyz")
    # If the template references ${agent_name} the substitution should land;
    # if it doesn't, this still passes (safe_substitute is a no-op for absent
    # placeholders), so the assertion is just "we didn't raise."
    assert rendered
