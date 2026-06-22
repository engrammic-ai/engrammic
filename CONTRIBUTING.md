# Contributing to Engrammic

Thanks for your interest in contributing to Engrammic.

## Getting Started

```bash
# Clone the repo
git clone https://github.com/engrammic-ai/engrammic.git
cd engrammic

# Install dependencies (requires uv)
just install-dev

# Run checks
just check

# Run tests
just test
```

## Development Workflow

1. Fork the repo and create a branch from `main`
2. Make your changes
3. Run `just check` (lint + typecheck must pass)
4. Run `just test` for relevant tests
5. Open a PR against `main`

## Code Style

- Python 3.13+
- Strict mypy, ruff for linting
- No emojis in code or docs
- Depend on `engine/protocols.py`, not concrete stores
- Always use `uv run` (never system Python)

## Architecture

See `context/architecture.md` for service architecture. Key concepts:

- **CITE schema**: 5 nodes (Memory, Claim, Fact, Belief, Commitment), 6 edges
- **MCP surface**: 7 tools (remember, learn, recall, trace, forget, tick, update)
- **SAGE pipeline**: Custodian, Synthesizer, Groundskeeper, Validator

## Pull Requests

- Keep PRs focused on a single change
- Include tests for new functionality
- Update docs if behavior changes
- `just check` must pass

## Issues

- Search existing issues before opening a new one
- Use issue templates when available
- Include reproduction steps for bugs

## License

By contributing, you agree that your contributions will be licensed under Apache-2.0.
