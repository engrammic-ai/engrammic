"""OAuth routes for MCP authentication.

Implements the OAuth 2.0 authorization code flow with PKCE for MCP clients,
delegating identity to WorkOS AuthKit.

Endpoints:
  GET  /.well-known/oauth-authorization-server  - RFC 8414 server metadata
  POST /oauth/register                           - RFC 7591 dynamic client registration
  GET  /oauth/authorize                          - Start flow, redirect to WorkOS
  GET  /oauth/callback                           - Handle WorkOS callback
  POST /oauth/token                              - Exchange code or refresh tokens
  POST /oauth/revoke                             - Revoke token (RFC 7009)
"""

from __future__ import annotations

import secrets
import uuid
from typing import Any
from urllib.parse import urlencode, urlparse

import structlog
from fastapi import APIRouter, Form, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import select

from context_service.auth.org_provisioning import resolve_or_create_org
from context_service.auth.workos_authkit import exchange_code_for_user, get_authorization_url
from context_service.config.settings import get_settings
from context_service.db.postgres import get_session
from context_service.models.postgres.oauth import OAuthAuthorizationRequest
from context_service.services.oauth import OAuthService
from context_service.services.user import UserService

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["oauth"])


def _success_page_html(email: str) -> str:
    """Generate a branded success page for direct signup flow."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Welcome to Engrammic</title>
    <style>
        :root {{
            --bg: #1c1c1c;
            --fg: #f5f2ed;
            --muted: #a0998f;
            --accent: #a63d2f;
        }}
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: var(--bg);
            color: var(--fg);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 2rem;
        }}
        .container {{
            max-width: 480px;
            text-align: center;
        }}
        h1 {{
            font-size: 1.5rem;
            font-weight: 500;
            margin-bottom: 1rem;
        }}
        .checkmark {{
            width: 64px;
            height: 64px;
            border-radius: 50%;
            background: var(--accent);
            display: flex;
            align-items: center;
            justify-content: center;
            margin: 0 auto 1.5rem;
        }}
        .checkmark svg {{
            width: 32px;
            height: 32px;
            stroke: white;
            stroke-width: 3;
            fill: none;
        }}
        .email {{
            color: var(--muted);
            margin-bottom: 2rem;
            font-size: 0.875rem;
        }}
        .cta {{
            display: inline-block;
            background: var(--accent);
            color: white;
            padding: 0.875rem 1.5rem;
            border-radius: 8px;
            text-decoration: none;
            font-weight: 500;
            font-size: 0.875rem;
        }}
        .cta:hover {{
            opacity: 0.9;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="checkmark">
            <svg viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"></polyline></svg>
        </div>
        <h1>You're all set</h1>
        <p class="email">{email}</p>
        <a href="https://join.engrammic.ai" class="cta">Get started</a>
    </div>
</body>
</html>"""


@router.get(
    "/.well-known/oauth-authorization-server",
    operation_id="oauth_metadata",
    summary="RFC 8414 OAuth authorization server metadata",
)
async def oauth_metadata() -> dict[str, str | list[str]]:
    """Return OAuth 2.0 authorization server metadata per RFC 8414."""
    settings = get_settings()
    issuer = settings.oauth.issuer
    return {
        "issuer": issuer,
        "authorization_endpoint": f"{issuer}/oauth/authorize",
        "token_endpoint": f"{issuer}/oauth/token",
        "revocation_endpoint": f"{issuer}/oauth/revoke",
        "registration_endpoint": f"{issuer}/oauth/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "scopes_supported": ["read", "write"],
    }


@router.get(
    "/.well-known/oauth-protected-resource",
    operation_id="protected_resource_metadata",
    summary="RFC 9728 OAuth protected resource metadata",
)
async def protected_resource_metadata() -> dict[str, str | list[str]]:
    """Return OAuth 2.0 protected resource metadata per RFC 9728.

    Tells MCP clients where to find the authorization server.
    """
    settings = get_settings()
    issuer = settings.oauth.issuer
    return {
        "resource": f"{issuer}/mcp",
        "authorization_servers": [issuer],
        "scopes_supported": ["read", "write"],
        "bearer_methods_supported": ["header"],
    }


@router.post(
    "/oauth/register",
    operation_id="oauth_register",
    summary="RFC 7591 dynamic client registration",
)
async def register_client(request_body: dict[str, Any] | None = None) -> dict[str, Any]:
    """Register a new OAuth client dynamically (RFC 7591).

    Since we use PKCE for all clients, we don't require client secrets.
    Any client can register and receive a client_id.
    """
    client_id = f"client_{uuid.uuid4().hex[:16]}"
    redirect_uris = []
    client_name = "Unknown Client"

    if request_body:
        redirect_uris = request_body.get("redirect_uris", [])
        client_name = request_body.get("client_name", client_name)

    return {
        "client_id": client_id,
        "client_name": client_name,
        "redirect_uris": redirect_uris,
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
    }


@router.get(
    "/oauth/authorize",
    operation_id="oauth_authorize",
    summary="Start OAuth authorization flow",
)
async def authorize(
    response_type: str = Query(..., description="Must be 'code'"),
    client_id: str = Query(..., description="OAuth client identifier"),
    redirect_uri: str = Query(..., description="URI to redirect after authorization"),
    code_challenge: str = Query(..., description="PKCE code challenge (S256)"),
    code_challenge_method: str = Query(default="S256", description="Must be 'S256'"),
    state: str = Query(..., description="Opaque state value for CSRF protection"),
    scope: str = Query(default="read write", description="Requested scopes"),
) -> RedirectResponse:
    """Start the OAuth authorization code flow with PKCE.

    Validates the redirect_uri host, stores the authorization request, then
    redirects the user to WorkOS for authentication.
    """
    settings = get_settings()

    if response_type != "code":
        raise HTTPException(status_code=400, detail="response_type must be 'code'")

    if code_challenge_method != "S256":
        raise HTTPException(status_code=400, detail="Only S256 code_challenge_method is supported")

    # RFC 8252 pattern validation (PKCE already required above)
    # - Loopback (127.0.0.1, localhost, ::1) with any port: allowed for CLI/desktop
    # - Custom schemes (non-http/https): allowed for native apps
    # - HTTPS with valid host: allowed for web clients
    # HTTP to non-loopback is rejected
    parsed = urlparse(redirect_uri)
    hostname = parsed.hostname or ""
    scheme = (parsed.scheme or "").lower()

    is_loopback = hostname in ("127.0.0.1", "localhost", "::1")
    is_custom_scheme = scheme not in ("http", "https", "")
    is_https = scheme == "https" and hostname
    is_http_loopback = scheme == "http" and is_loopback

    # Reject dangerous pseudo-schemes that could enable XSS or local file access
    dangerous_schemes = {"file", "javascript", "data", "vbscript", "about"}
    if is_custom_scheme and scheme in dangerous_schemes:
        raise HTTPException(status_code=400, detail="Invalid redirect_uri scheme")

    if not (is_custom_scheme or is_https or is_http_loopback):
        raise HTTPException(
            status_code=400,
            detail="Invalid redirect_uri: must be HTTPS, loopback HTTP, or custom scheme",
        )

    workos_state = secrets.token_urlsafe(32)

    async with get_session() as session:
        oauth_svc = OAuthService(session)
        auth_request = await oauth_svc.create_authorization_request(
            state=state,
            code_challenge=code_challenge,
            redirect_uri=redirect_uri,
            client_id=client_id,
            scope=scope,
        )
        # workos_state is not in the service method signature; set it directly
        # on the model before the session commits.
        auth_request.workos_state = workos_state

    try:
        workos_url = await get_authorization_url(
            redirect_uri=f"{settings.oauth.issuer}/oauth/callback",
            state=workos_state,
        )
    except ValueError as exc:
        logger.error("oauth.authorize.workos_url_failed", error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to generate authorization URL") from exc

    logger.info(
        "oauth.authorize.redirecting",
        client_id=client_id,
        state=state,
    )
    return RedirectResponse(url=workos_url, status_code=302)


@router.get(
    "/oauth/callback",
    operation_id="oauth_callback",
    summary="Handle WorkOS OAuth callback",
    response_model=None,
)
async def callback(
    code: str = Query(..., description="Authorization code from WorkOS"),
    state: str = Query(default=None, description="WorkOS state parameter (maps to workos_state)"),
    error: str = Query(default=None, description="Error from WorkOS"),
    error_description: str = Query(default=None, description="Error description from WorkOS"),
) -> RedirectResponse | HTMLResponse:
    """Handle the WorkOS OAuth callback.

    Exchanges the WorkOS code for user info, upserts the user, creates an
    authorization code, then redirects back to the MCP client.
    """
    if error:
        logger.warning(
            "oauth.callback.workos_error",
            error=error,
            error_description=error_description,
        )
        raise HTTPException(
            status_code=400,
            detail=f"WorkOS authorization error: {error}",
        )

    # Direct signup flow (no MCP client) - state is None
    if state is None:
        try:
            user_info = await exchange_code_for_user(code)
        except ValueError as exc:
            logger.error("oauth.callback.direct_signup_failed", error=str(exc))
            raise HTTPException(status_code=400, detail="Failed to verify signup") from exc

        async with get_session() as session:
            from context_service.services.models import derive_silo_id

            workos_user_id: str = user_info["id"]
            email: str = user_info.get("email", "")
            name: str | None = user_info.get("name")
            session_org_id: str | None = user_info.get("organization_id")

            effective_org_id = await resolve_or_create_org(
                session,
                workos_user_id=workos_user_id,
                session_org_id=session_org_id,
                name=name,
                email=email,
            )
            silo_id = str(derive_silo_id(effective_org_id))

            user_svc = UserService(session)
            await user_svc.upsert_user(
                workos_user_id=workos_user_id,
                org_id=effective_org_id,
                silo_id=silo_id,
                email=email,
                name=name,
            )

        logger.info("oauth.callback.direct_signup_success", workos_user_id=user_info["id"])
        return HTMLResponse(content=_success_page_html(email), status_code=200)

    # MCP OAuth flow - look up the authorization request by workos_state
    async with get_session() as session:
        stmt = select(OAuthAuthorizationRequest).where(
            OAuthAuthorizationRequest.workos_state == state
        )
        result = await session.execute(stmt)
        auth_request = result.scalar_one_or_none()

        if auth_request is None:
            logger.warning("oauth.callback.unknown_workos_state", workos_state=state)
            raise HTTPException(status_code=400, detail="Unknown or expired state parameter")

        # Exchange WorkOS code for user info
        try:
            user_info = await exchange_code_for_user(code)
        except ValueError as exc:
            logger.error("oauth.callback.exchange_failed", error=str(exc))
            raise HTTPException(
                status_code=400, detail="Failed to exchange authorization code"
            ) from exc

        workos_user_id = user_info["id"]
        email = user_info.get("email", "")
        name = user_info.get("name")
        session_org_id = user_info.get("organization_id")

        from context_service.services.models import derive_silo_id

        effective_org_id = await resolve_or_create_org(
            session,
            workos_user_id=workos_user_id,
            session_org_id=session_org_id,
            name=name,
            email=email,
        )
        silo_id = str(derive_silo_id(effective_org_id))

        user_svc = UserService(session)
        db_user = await user_svc.upsert_user(
            workos_user_id=workos_user_id,
            org_id=effective_org_id,
            silo_id=silo_id,
            email=email,
            name=name,
        )

        oauth_svc = OAuthService(session)
        _auth_code, issued_code = await oauth_svc.create_authorization_code(
            user_id=db_user.id,
            request_id=auth_request.id,
        )

        redirect_uri = auth_request.redirect_uri
        original_state = auth_request.state

    params = urlencode({"code": issued_code, "state": original_state})
    redirect_url = f"{redirect_uri}?{params}"

    logger.info(
        "oauth.callback.success",
        workos_user_id=workos_user_id,
        redirect_uri=redirect_uri,
    )
    return RedirectResponse(url=redirect_url, status_code=302)


@router.post(
    "/oauth/token",
    operation_id="oauth_token",
    summary="Exchange authorization code or refresh token for access tokens",
)
async def token(
    grant_type: str = Form(..., description="'authorization_code' or 'refresh_token'"),
    code: str = Form(default=None, description="Authorization code (authorization_code grant)"),
    code_verifier: str = Form(default=None, description="PKCE verifier (authorization_code grant)"),
    client_id: str = Form(..., description="OAuth client identifier"),
    refresh_token: str = Form(default=None, description="Refresh token (refresh_token grant)"),
) -> dict[str, str | int]:
    """Exchange an authorization code or refresh token for access tokens.

    Supports grant types: authorization_code, refresh_token.
    """
    async with get_session() as session:
        oauth_svc = OAuthService(session)

        if grant_type == "authorization_code":
            if not code or not code_verifier:
                raise HTTPException(status_code=400, detail="code and code_verifier are required")
            result = await oauth_svc.exchange_code_for_tokens(code, code_verifier, client_id)
            if result is None:
                raise HTTPException(status_code=400, detail="Invalid or expired authorization code")
            return result

        if grant_type == "refresh_token":
            if not refresh_token:
                raise HTTPException(status_code=400, detail="refresh_token is required")
            result = await oauth_svc.refresh_access_token(refresh_token)
            if result is None:
                raise HTTPException(status_code=400, detail="Invalid or expired refresh token")
            return result

        raise HTTPException(
            status_code=400,
            detail=f"Unsupported grant_type: {grant_type}",
        )


@router.post(
    "/oauth/revoke",
    status_code=200,
    operation_id="oauth_revoke",
    summary="Revoke an access or refresh token (RFC 7009)",
)
async def revoke(
    token: str = Form(..., description="Access or refresh token to revoke"),
) -> Response:
    """Revoke an access or refresh token per RFC 7009.

    Always returns 200 per the spec, even if the token was not found.
    """
    async with get_session() as session:
        oauth_svc = OAuthService(session)
        await oauth_svc.revoke_token(token)

    return Response(status_code=200)
