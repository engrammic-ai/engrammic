# Supported MCP Clients

Engrammic supports OAuth authentication with all major MCP clients and agentic platforms.

## IDE Integrations

| Client | Status | Redirect Host | Notes |
|--------|--------|---------------|-------|
| **Cursor** | Verified | `anysphere.cursor-mcp` | Custom URI scheme `cursor://` |
| **Claude Desktop** | Verified | `claude.ai` | Custom URI scheme `claude://` |
| **Claude Code** | Verified | `anthropic.claude-code` | CLI and IDE extension |
| **VS Code + Copilot** | Supported | `vscode.dev`, `vscode-redirect.azurewebsites.net` | Native MCP from v1.101+ |
| **Windsurf** | Supported | `codeium.windsurf-mcp` | Codeium's AI IDE |
| **Zed** | Supported | `zed.dev` | Rust-based editor |
| **JetBrains IDEs** | Supported | `jetbrains.com` | IntelliJ, PyCharm, WebStorm, etc. (2025.2+) |
| **Cline** | Supported | `cline.bot` | VS Code extension |
| **Continue.dev** | Supported | `continue.dev` | Open-source AI assistant |
| **Replit** | Supported | `replit.com` | Browser-based IDE |

## Agentic Platforms

| Platform | Status | Redirect Host | Notes |
|----------|--------|---------------|-------|
| **Dust.tt** | Supported | `dust.tt`, `eu.dust.tt` | Enterprise AI OS |
| **Kiro (AWS)** | Supported | `kiro.dev` | Amazon's agentic IDE |
| **Amazon Q** | Supported | `amazon.com`, `aws.amazon.com` | AWS AI assistant |
| **Sourcegraph Cody** | Supported | `sourcegraph.com` | Code intelligence |
| **Tabnine** | Supported | `tabnine.com` | AI code completion |

## Local Development

For local development and testing, the following hosts are always allowed:
- `localhost`
- `127.0.0.1`

## Adding Custom Hosts

To allow additional redirect hosts for custom integrations, set the environment variable:

```bash
OAUTH__ALLOWED_REDIRECT_HOSTS='["localhost","127.0.0.1","myapp.example.com"]'
```

Note: This replaces the default list, so include any hosts you need.

## OAuth Flow

1. Client connects to MCP endpoint without token
2. Server returns `401` with `WWW-Authenticate: Bearer resource_metadata="https://beta.engrammic.ai/.well-known/oauth-protected-resource"`
3. Client fetches protected resource metadata, discovers authorization server
4. Client initiates OAuth flow with PKCE
5. User authenticates via WorkOS (Google, GitHub, email)
6. Client receives tokens and can call MCP tools

## Troubleshooting

### "Invalid redirect_uri host" error

The redirect host your client is using isn't in our allowlist. Check:
1. Your client version supports MCP OAuth
2. The host matches one in the table above
3. For custom integrations, configure `OAUTH__ALLOWED_REDIRECT_HOSTS`

### "Authorization required" but no OAuth prompt

Your client may not support MCP OAuth yet. Check:
1. Client is recent version with OAuth support
2. Try clearing MCP auth cache (client-specific)
3. Check client logs for OAuth discovery attempts

### Token expired

Access tokens expire after 1 hour. Clients should automatically refresh using the refresh token (valid 90 days).
