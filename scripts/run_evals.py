from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import click

REPO_ROOT = Path(__file__).parent.parent

PROVIDER_CHOICES = click.Choice(["anthropic", "openai", "gemini", "vertex"])


@click.command()
@click.option("--scenario", help="Run a specific scenario by keyword (e.g. recall, claim_promotion).")
@click.option("--with-llm", is_flag=True, help="Enable eval cases that call live LLM APIs.")
@click.option(
    "--provider",
    default="anthropic",
    show_default=True,
    type=PROVIDER_CHOICES,
    help="LLM provider to use when --with-llm is active.",
)
@click.option("--output", metavar="PATH", help="Write eval results as JSON to this file.")
@click.option("-v", "--verbose", is_flag=True, help="Verbose pytest output.")
@click.option(
    "--no-docker-check",
    is_flag=True,
    help="Skip the Memgraph connectivity check (useful in CI with external health checks).",
)
def main(
    scenario: str | None,
    with_llm: bool,
    provider: str,
    output: str | None,
    verbose: bool,
    no_docker_check: bool,
) -> None:
    """Run HIL quality evals against the live context-service stack."""
    args = ["uv", "run", "pytest", "tests/evals/", "-m", "evals"]

    if scenario:
        args.extend(["-k", scenario])

    if with_llm:
        args.append("--with-llm")
        args.append(f"--llm-provider={provider}")

    if output:
        args.append(f"--eval-output={output}")

    if no_docker_check:
        args.append("--ignore-glob=*integration*")

    if verbose:
        args.append("-v")
    else:
        args.append("-q")

    result = subprocess.run(args, cwd=str(REPO_ROOT))
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
