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
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import select

from context_service.auth.workos_authkit import exchange_code_for_user, get_authorization_url
from context_service.config.settings import get_settings
from context_service.db.postgres import get_session
from context_service.models.postgres.oauth import OAuthAuthorizationRequest
from context_service.services.oauth import OAuthService
from context_service.services.user import UserService

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["oauth"])


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

    parsed = urlparse(redirect_uri)
    if parsed.hostname not in settings.oauth.allowed_redirect_hosts:
        raise HTTPException(status_code=400, detail="Invalid redirect_uri host")

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
) -> RedirectResponse | dict[str, str]:
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
            org_id: str | None = user_info.get("organization_id")
            effective_org_id = org_id or workos_user_id
            silo_id = str(derive_silo_id(effective_org_id))

            user_svc = UserService(session)
            await user_svc.upsert_user(
                workos_user_id=workos_user_id,
                org_id=effective_org_id,
                silo_id=silo_id,
                email=email,
            )

        logger.info("oauth.callback.direct_signup_success", workos_user_id=user_info["id"])
        return {
            "status": "ok",
            "message": "Account created. You can now use Engrammic with your MCP client.",
        }

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
        org_id = user_info.get("organization_id")

        from context_service.services.models import derive_silo_id

        effective_org_id = org_id or workos_user_id
        silo_id = str(derive_silo_id(effective_org_id))

        user_svc = UserService(session)
        db_user = await user_svc.upsert_user(
            workos_user_id=workos_user_id,
            org_id=effective_org_id,
            silo_id=silo_id,
            email=email,
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
            result = await oauth_svc.exchange_code_for_tokens(code, code_verifier)
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
