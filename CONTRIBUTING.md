# Contributing to Engrammic

Thank you for your interest in contributing to Engrammic! We welcome community contributions to help build the future of Epistemic Augmented Generation (EAG).

## Development Setup

1. Clone the repository: `git clone https://github.com/engrammic-ai/engrammic.git`
2. Install dependencies via `uv`: `just install-dev`
3. Start the local stack (Memgraph, Qdrant, Redis): `just up`
4. Run the test suite: `just test`

## Contribution Guidelines

* **Linting & Formatting:** We enforce strict typing (`mypy`) and formatting (`ruff`). Run `just check` before submitting a PR.
* **Architecture:** Engrammic strictly enforces the CITE architecture. Please read the documentation in `../primitives/docs` before making architectural changes.
* **Commit Messages:** Use clear, descriptive commit messages.

## Submitting a Pull Request

1. Fork the repository and create your branch from `main`.
2. Write tests for any new features or bug fixes.
3. Ensure the test suite passes (`just ci`).
4. Submit your PR with a clear description of the problem and your solution.