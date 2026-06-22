# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in Engrammic, please report it privately.

**Do not open a public GitHub issue for security vulnerabilities.**

Email: dev@engrammic.ai

Include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Any suggested fixes

We will acknowledge receipt within 48 hours and provide a timeline for resolution.

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.2.x   | Yes       |
| < 0.2   | No        |

## Security Practices

- All dependencies are pinned via `uv.lock`
- Secrets are never committed (see `.env.example` for required variables)
- Auth is required for all MCP and REST endpoints when `AUTH_ENABLED=true`
- Input validation at trust boundaries (evidence URLs, user input)
