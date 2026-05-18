"""Integration tests for the OAuth 2.0 / PKCE flow.

Covers:
  - /.well-known/oauth-authorization-server metadata (RFC 8414)
  - /oauth/authorize happy path and error cases
  - /oauth/callback happy path and error cases
  - /oauth/token: authorization_code grant with PKCE
  - /oauth/token: refresh_token grant
  - /oauth/token: unsupported grant_type
  - /oauth/revoke
  - _resolve_oauth_token (MCP auth path)
  - OAuthService PKCE and hash helpers

WorkOS is always mocked (context_service.auth.workos_authkit functions).
Postgres is always mocked via a fake asynccontextmanager session.
No live Docker stack is required.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import sys
import types
import uuid
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from context_service.api.routes.oauth import router as oauth_router
from context_service.services.oauth import OAuthService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def generate_pkce_pair() -> tuple[str, str]:
    """Generate code_verifier and code_challenge for PKCE S256."""
    code_verifier = secrets.token_urlsafe(32)
    verifier_hash = hashlib.sha256(code_verifier.encode()).digest()
    code_challenge = base64.urlsafe_b64encode(verifier_hash).rstrip(b"=").decode()
    return code_verifier, code_challenge


def _make_app() -> FastAPI:
    """Minimal FastAPI app with only the OAuth router mounted."""
    app = FastAPI()
    app.include_router(oauth_router)
    return app


@asynccontextmanager
async def _fake_session(session_mock: Any):  # type: ignore[return]
    yield session_mock


def _make_fake_session() -> AsyncMock:
    return AsyncMock()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app() -> FastAPI:
    return _make_app()


@pytest.fixture
async def client(app: FastAPI) -> AsyncClient:  # type: ignore[override]
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as c:
        yield c  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Pure-logic tests (no HTTP, no DB)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestOAuthServiceHelpers:
    """Test pure static methods on OAuthService — no mocking required."""

    def test_hash_token_is_sha256_hex(self) -> None:
        token = "mysecrettoken"
        result = OAuthService._hash_token(token)
        expected = hashlib.sha256(token.encode()).hexdigest()
        assert result == expected
        assert len(result) == 64

    def test_hash_token_same_input_same_output(self) -> None:
        token = secrets.token_urlsafe(32)
        assert OAuthService._hash_token(token) == OAuthService._hash_token(token)

    def test_verify_pkce_valid_pair(self) -> None:
        verifier, challenge = generate_pkce_pair()
        assert OAuthService._verify_pkce(verifier, challenge) is True

    def test_verify_pkce_wrong_verifier(self) -> None:
        _, challenge = generate_pkce_pair()
        wrong_verifier = secrets.token_urlsafe(32)
        assert OAuthService._verify_pkce(wrong_verifier, challenge) is False

    def test_verify_pkce_empty_strings(self) -> None:
        assert OAuthService._verify_pkce("", "any") is False

    def test_generate_token_is_url_safe_string(self) -> None:
        token = OAuthService._generate_token()
        assert isinstance(token, str)
        assert len(token) > 0


# ---------------------------------------------------------------------------
# Metadata endpoint — no DB, no WorkOS
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestOAuthMetadata:
    async def test_metadata_returns_200(self, client: AsyncClient) -> None:
        resp = await client.get("/.well-known/oauth-authorization-server")
        assert resp.status_code == 200

    async def test_metadata_required_fields(self, client: AsyncClient) -> None:
        resp = await client.get("/.well-known/oauth-authorization-server")
        data = resp.json()
        required = {
            "issuer",
            "authorization_endpoint",
            "token_endpoint",
            "revocation_endpoint",
            "response_types_supported",
            "grant_types_supported",
            "code_challenge_methods_supported",
            "token_endpoint_auth_methods_supported",
        }
        assert required.issubset(data.keys())

    async def test_metadata_grant_types(self, client: AsyncClient) -> None:
        resp = await client.get("/.well-known/oauth-authorization-server")
        data = resp.json()
        assert "authorization_code" in data["grant_types_supported"]
        assert "refresh_token" in data["grant_types_supported"]

    async def test_metadata_pkce_method(self, client: AsyncClient) -> None:
        resp = await client.get("/.well-known/oauth-authorization-server")
        data = resp.json()
        assert "S256" in data["code_challenge_methods_supported"]

    async def test_metadata_endpoints_contain_issuer(self, client: AsyncClient) -> None:
        resp = await client.get("/.well-known/oauth-authorization-server")
        data = resp.json()
        issuer = data["issuer"]
        assert data["authorization_endpoint"].startswith(issuer)
        assert data["token_endpoint"].startswith(issuer)
        assert data["revocation_endpoint"].startswith(issuer)


# ---------------------------------------------------------------------------
# /oauth/authorize
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestOAuthAuthorize:
    """Tests for the /oauth/authorize route."""

    def _params(
        self,
        code_challenge: str = "test-challenge",
        response_type: str = "code",
        code_challenge_method: str = "S256",
        redirect_uri: str = "http://localhost:8080/callback",
    ) -> dict[str, str]:
        return {
            "response_type": response_type,
            "client_id": "test-client",
            "redirect_uri": redirect_uri,
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method,
            "state": secrets.token_urlsafe(16),
        }

    async def test_invalid_response_type_returns_400(self, client: AsyncClient) -> None:
        params = self._params(response_type="token")
        resp = await client.get("/oauth/authorize", params=params, follow_redirects=False)
        assert resp.status_code == 400
        assert "response_type" in resp.json()["detail"]

    async def test_invalid_code_challenge_method_returns_400(
        self, client: AsyncClient
    ) -> None:
        params = self._params(code_challenge_method="plain")
        resp = await client.get("/oauth/authorize", params=params, follow_redirects=False)
        assert resp.status_code == 400
        assert "S256" in resp.json()["detail"]

    async def test_disallowed_redirect_host_returns_400(
        self, client: AsyncClient
    ) -> None:
        params = self._params(redirect_uri="https://evil.example.com/callback")
        resp = await client.get("/oauth/authorize", params=params, follow_redirects=False)
        assert resp.status_code == 400
        assert "redirect_uri" in resp.json()["detail"]

    async def test_valid_authorize_redirects_to_workos(
        self, client: AsyncClient
    ) -> None:
        """Happy path: valid params redirect to WorkOS authorization URL."""
        verifier, challenge = generate_pkce_pair()
        params = self._params(code_challenge=challenge)

        fake_auth_request = MagicMock()
        fake_auth_request.id = uuid.uuid4()
        fake_auth_request.workos_state = None

        fake_session = _make_fake_session()
        fake_oauth_svc = AsyncMock()
        fake_oauth_svc.create_authorization_request = AsyncMock(return_value=fake_auth_request)

        workos_url = "https://authkit.example.com/authorize?state=xyz"

        with (
            patch(
                "context_service.api.routes.oauth.get_session",
                return_value=_fake_session(fake_session),
            ),
            patch(
                "context_service.api.routes.oauth.OAuthService",
                return_value=fake_oauth_svc,
            ),
            patch(
                "context_service.api.routes.oauth.get_authorization_url",
                new=AsyncMock(return_value=workos_url),
            ),
        ):
            resp = await client.get(
                "/oauth/authorize", params=params, follow_redirects=False
            )

        assert resp.status_code == 302
        assert resp.headers["location"] == workos_url

    async def test_workos_url_failure_returns_500(self, client: AsyncClient) -> None:
        """If WorkOS raises ValueError, the route returns 500."""
        verifier, challenge = generate_pkce_pair()
        params = self._params(code_challenge=challenge)

        fake_auth_request = MagicMock()
        fake_auth_request.id = uuid.uuid4()
        fake_auth_request.workos_state = None

        fake_oauth_svc = AsyncMock()
        fake_oauth_svc.create_authorization_request = AsyncMock(return_value=fake_auth_request)

        with (
            patch(
                "context_service.api.routes.oauth.get_session",
                return_value=_fake_session(_make_fake_session()),
            ),
            patch(
                "context_service.api.routes.oauth.OAuthService",
                return_value=fake_oauth_svc,
            ),
            patch(
                "context_service.api.routes.oauth.get_authorization_url",
                new=AsyncMock(side_effect=ValueError("WorkOS not configured")),
            ),
        ):
            resp = await client.get(
                "/oauth/authorize", params=params, follow_redirects=False
            )

        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# /oauth/callback
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestOAuthCallback:
    """Tests for the WorkOS callback handler."""

    async def test_error_param_returns_400(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/oauth/callback",
            params={"code": "x", "state": "y", "error": "access_denied"},
            follow_redirects=False,
        )
        assert resp.status_code == 400
        assert "access_denied" in resp.json()["detail"]

    async def test_unknown_state_returns_400(self, client: AsyncClient) -> None:
        fake_session = _make_fake_session()
        # scalar_one_or_none returns None (unknown state)
        fake_result = MagicMock()
        fake_result.scalar_one_or_none.return_value = None
        fake_session.execute = AsyncMock(return_value=fake_result)

        with patch(
            "context_service.api.routes.oauth.get_session",
            return_value=_fake_session(fake_session),
        ):
            resp = await client.get(
                "/oauth/callback",
                params={"code": "wos-code-123", "state": "unknown-state"},
                follow_redirects=False,
            )

        assert resp.status_code == 400
        assert "state" in resp.json()["detail"]

    async def test_workos_exchange_failure_returns_400(
        self, client: AsyncClient
    ) -> None:
        """If exchange_code_for_user raises ValueError, route returns 400."""
        fake_auth_request = MagicMock()
        fake_auth_request.id = uuid.uuid4()
        fake_auth_request.state = "original-state"
        fake_auth_request.redirect_uri = "http://localhost:8080/callback"

        fake_session = _make_fake_session()
        fake_result = MagicMock()
        fake_result.scalar_one_or_none.return_value = fake_auth_request
        fake_session.execute = AsyncMock(return_value=fake_result)

        with (
            patch(
                "context_service.api.routes.oauth.get_session",
                return_value=_fake_session(fake_session),
            ),
            patch(
                "context_service.api.routes.oauth.exchange_code_for_user",
                new=AsyncMock(side_effect=ValueError("invalid code")),
            ),
        ):
            resp = await client.get(
                "/oauth/callback",
                params={"code": "bad-wos-code", "state": "some-workos-state"},
                follow_redirects=False,
            )

        assert resp.status_code == 400
        assert "exchange" in resp.json()["detail"].lower()

    async def test_happy_path_redirects_with_code_and_state(
        self, client: AsyncClient
    ) -> None:
        """Successful callback redirects to the original redirect_uri with code+state."""
        original_state = "client-original-state"
        redirect_uri = "http://localhost:8080/callback"
        issued_code = "issued-auth-code-abc"

        fake_auth_request = MagicMock()
        fake_auth_request.id = uuid.uuid4()
        fake_auth_request.state = original_state
        fake_auth_request.redirect_uri = redirect_uri

        fake_db_user = MagicMock()
        fake_db_user.id = uuid.uuid4()
        fake_db_user.workos_user_id = "wos-user-xyz"
        fake_db_user.org_id = "org-test"
        fake_db_user.email = "test@example.com"

        fake_auth_code = MagicMock()

        fake_session = _make_fake_session()
        fake_result = MagicMock()
        fake_result.scalar_one_or_none.return_value = fake_auth_request
        fake_session.execute = AsyncMock(return_value=fake_result)

        fake_oauth_svc = AsyncMock()
        fake_oauth_svc.create_authorization_code = AsyncMock(
            return_value=(fake_auth_code, issued_code)
        )

        fake_user_svc = AsyncMock()
        fake_user_svc.upsert_user = AsyncMock(return_value=fake_db_user)

        user_info = {
            "id": "wos-user-xyz",
            "email": "test@example.com",
            "organization_id": "org-test",
        }

        with (
            patch(
                "context_service.api.routes.oauth.get_session",
                return_value=_fake_session(fake_session),
            ),
            patch(
                "context_service.api.routes.oauth.exchange_code_for_user",
                new=AsyncMock(return_value=user_info),
            ),
            patch(
                "context_service.api.routes.oauth.OAuthService",
                return_value=fake_oauth_svc,
            ),
            patch(
                "context_service.api.routes.oauth.UserService",
                return_value=fake_user_svc,
            ),
        ):
            resp = await client.get(
                "/oauth/callback",
                params={"code": "wos-code", "state": "wos-state"},
                follow_redirects=False,
            )

        assert resp.status_code == 302
        location = resp.headers["location"]
        assert location.startswith(redirect_uri)
        assert f"code={issued_code}" in location
        assert f"state={original_state}" in location


# ---------------------------------------------------------------------------
# /oauth/token — authorization_code grant
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestOAuthTokenAuthorizationCode:
    async def test_missing_code_returns_400(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/oauth/token",
            data={"grant_type": "authorization_code"},
        )
        assert resp.status_code == 400
        assert "code" in resp.json()["detail"]

    async def test_missing_code_verifier_returns_400(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/oauth/token",
            data={"grant_type": "authorization_code", "code": "some-code"},
        )
        assert resp.status_code == 400
        assert "code_verifier" in resp.json()["detail"]

    async def test_invalid_code_returns_400(self, client: AsyncClient) -> None:
        fake_oauth_svc = AsyncMock()
        fake_oauth_svc.exchange_code_for_tokens = AsyncMock(return_value=None)

        with (
            patch(
                "context_service.api.routes.oauth.get_session",
                return_value=_fake_session(_make_fake_session()),
            ),
            patch(
                "context_service.api.routes.oauth.OAuthService",
                return_value=fake_oauth_svc,
            ),
        ):
            resp = await client.post(
                "/oauth/token",
                data={
                    "grant_type": "authorization_code",
                    "code": "bad-code",
                    "code_verifier": "bad-verifier",
                },
            )

        assert resp.status_code == 400
        assert "Invalid" in resp.json()["detail"]

    async def test_valid_code_returns_tokens(self, client: AsyncClient) -> None:
        verifier, challenge = generate_pkce_pair()
        token_response = {
            "access_token": "at-abc",
            "refresh_token": "rt-abc",
            "expires_in": 3600,
            "token_type": "Bearer",
        }
        fake_oauth_svc = AsyncMock()
        fake_oauth_svc.exchange_code_for_tokens = AsyncMock(return_value=token_response)

        with (
            patch(
                "context_service.api.routes.oauth.get_session",
                return_value=_fake_session(_make_fake_session()),
            ),
            patch(
                "context_service.api.routes.oauth.OAuthService",
                return_value=fake_oauth_svc,
            ),
        ):
            resp = await client.post(
                "/oauth/token",
                data={
                    "grant_type": "authorization_code",
                    "code": "valid-code",
                    "code_verifier": verifier,
                },
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["access_token"] == "at-abc"
        assert data["refresh_token"] == "rt-abc"
        assert data["token_type"] == "Bearer"
        assert data["expires_in"] == 3600

    async def test_exchange_verifies_pkce_via_service(self, client: AsyncClient) -> None:
        """Service is called with both code and code_verifier."""
        verifier, _ = generate_pkce_pair()
        fake_oauth_svc = AsyncMock()
        fake_oauth_svc.exchange_code_for_tokens = AsyncMock(return_value=None)

        with (
            patch(
                "context_service.api.routes.oauth.get_session",
                return_value=_fake_session(_make_fake_session()),
            ),
            patch(
                "context_service.api.routes.oauth.OAuthService",
                return_value=fake_oauth_svc,
            ),
        ):
            await client.post(
                "/oauth/token",
                data={
                    "grant_type": "authorization_code",
                    "code": "some-code",
                    "code_verifier": verifier,
                },
            )

        fake_oauth_svc.exchange_code_for_tokens.assert_awaited_once_with(
            "some-code", verifier
        )


# ---------------------------------------------------------------------------
# /oauth/token — refresh_token grant
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestOAuthTokenRefresh:
    async def test_missing_refresh_token_returns_400(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/oauth/token",
            data={"grant_type": "refresh_token"},
        )
        assert resp.status_code == 400
        assert "refresh_token" in resp.json()["detail"]

    async def test_invalid_refresh_token_returns_400(self, client: AsyncClient) -> None:
        fake_oauth_svc = AsyncMock()
        fake_oauth_svc.refresh_access_token = AsyncMock(return_value=None)

        with (
            patch(
                "context_service.api.routes.oauth.get_session",
                return_value=_fake_session(_make_fake_session()),
            ),
            patch(
                "context_service.api.routes.oauth.OAuthService",
                return_value=fake_oauth_svc,
            ),
        ):
            resp = await client.post(
                "/oauth/token",
                data={"grant_type": "refresh_token", "refresh_token": "bad-rt"},
            )

        assert resp.status_code == 400
        assert "Invalid" in resp.json()["detail"]

    async def test_valid_refresh_token_returns_new_access_token(
        self, client: AsyncClient
    ) -> None:
        token_response = {
            "access_token": "new-at-xyz",
            "expires_in": 3600,
            "token_type": "Bearer",
        }
        fake_oauth_svc = AsyncMock()
        fake_oauth_svc.refresh_access_token = AsyncMock(return_value=token_response)

        with (
            patch(
                "context_service.api.routes.oauth.get_session",
                return_value=_fake_session(_make_fake_session()),
            ),
            patch(
                "context_service.api.routes.oauth.OAuthService",
                return_value=fake_oauth_svc,
            ),
        ):
            resp = await client.post(
                "/oauth/token",
                data={"grant_type": "refresh_token", "refresh_token": "valid-rt"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["access_token"] == "new-at-xyz"
        assert "refresh_token" not in data  # refresh response only has access_token
        assert data["token_type"] == "Bearer"

    async def test_refresh_token_passed_to_service(self, client: AsyncClient) -> None:
        fake_oauth_svc = AsyncMock()
        fake_oauth_svc.refresh_access_token = AsyncMock(return_value=None)

        with (
            patch(
                "context_service.api.routes.oauth.get_session",
                return_value=_fake_session(_make_fake_session()),
            ),
            patch(
                "context_service.api.routes.oauth.OAuthService",
                return_value=fake_oauth_svc,
            ),
        ):
            await client.post(
                "/oauth/token",
                data={"grant_type": "refresh_token", "refresh_token": "my-rt-token"},
            )

        fake_oauth_svc.refresh_access_token.assert_awaited_once_with("my-rt-token")


# ---------------------------------------------------------------------------
# /oauth/token — unsupported grant_type
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestOAuthTokenUnsupportedGrant:
    async def test_unsupported_grant_type_returns_400(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/oauth/token",
            data={"grant_type": "client_credentials"},
        )
        assert resp.status_code == 400
        assert "client_credentials" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# /oauth/revoke
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestOAuthRevoke:
    async def test_revoke_known_token_returns_200(self, client: AsyncClient) -> None:
        fake_oauth_svc = AsyncMock()
        fake_oauth_svc.revoke_token = AsyncMock(return_value=True)

        with (
            patch(
                "context_service.api.routes.oauth.get_session",
                return_value=_fake_session(_make_fake_session()),
            ),
            patch(
                "context_service.api.routes.oauth.OAuthService",
                return_value=fake_oauth_svc,
            ),
        ):
            resp = await client.post(
                "/oauth/revoke",
                data={"token": "valid-access-token"},
            )

        assert resp.status_code == 200

    async def test_revoke_unknown_token_still_returns_200(
        self, client: AsyncClient
    ) -> None:
        """RFC 7009 requires 200 even when token not found."""
        fake_oauth_svc = AsyncMock()
        fake_oauth_svc.revoke_token = AsyncMock(return_value=False)

        with (
            patch(
                "context_service.api.routes.oauth.get_session",
                return_value=_fake_session(_make_fake_session()),
            ),
            patch(
                "context_service.api.routes.oauth.OAuthService",
                return_value=fake_oauth_svc,
            ),
        ):
            resp = await client.post(
                "/oauth/revoke",
                data={"token": "nonexistent-token"},
            )

        assert resp.status_code == 200

    async def test_revoke_token_is_passed_to_service(self, client: AsyncClient) -> None:
        fake_oauth_svc = AsyncMock()
        fake_oauth_svc.revoke_token = AsyncMock(return_value=True)

        with (
            patch(
                "context_service.api.routes.oauth.get_session",
                return_value=_fake_session(_make_fake_session()),
            ),
            patch(
                "context_service.api.routes.oauth.OAuthService",
                return_value=fake_oauth_svc,
            ),
        ):
            await client.post(
                "/oauth/revoke",
                data={"token": "my-special-token"},
            )

        fake_oauth_svc.revoke_token.assert_awaited_once_with("my-special-token")


# ---------------------------------------------------------------------------
# _resolve_oauth_token (MCP auth path)
#
# context_service.mcp.server imports fastmcp.FastMCP at module level.
# In the test environment fastmcp is present but FastMCP is not exported,
# so we stub it before the import to avoid a collection-time ImportError.
# ---------------------------------------------------------------------------


def _import_resolve_oauth_token() -> Any:
    """Import _resolve_oauth_token from the MCP server module.

    In some environments fastmcp exists as a namespace package but does not
    export FastMCP.  We stub it before the first import of context_service.mcp
    so that the server module can be loaded without ImportError.
    """
    import fastmcp as _fastmcp_pkg  # noqa: PLC0415

    if not hasattr(_fastmcp_pkg, "FastMCP"):
        _fastmcp_pkg.FastMCP = MagicMock()  # type: ignore[attr-defined]

        _deps_key = "fastmcp.server.dependencies"
        if _deps_key not in sys.modules:
            _deps_mod = types.ModuleType(_deps_key)
            _deps_mod.get_http_headers = MagicMock()  # type: ignore[attr-defined]
            sys.modules[_deps_key] = _deps_mod

        _server_key = "fastmcp.server"
        if _server_key not in sys.modules:
            _server_mod = types.ModuleType(_server_key)
            sys.modules[_server_key] = _server_mod

    import context_service.mcp.server as mcp_server  # noqa: PLC0415

    return mcp_server._resolve_oauth_token


@pytest.mark.integration
class TestResolveoauthToken:
    """Tests for the _resolve_oauth_token helper in mcp/server.py."""

    # _resolve_oauth_token uses lazy imports inside the function body:
    #   from context_service.db.postgres import get_session
    #   from context_service.services.oauth import OAuthService
    # We must patch at those source locations, not at the server module.

    async def test_returns_none_for_invalid_token(self) -> None:
        _resolve_oauth_token = _import_resolve_oauth_token()

        fake_oauth_svc = AsyncMock()
        fake_oauth_svc.validate_access_token = AsyncMock(return_value=None)

        with (
            patch(
                "context_service.db.postgres.get_session",
                return_value=_fake_session(_make_fake_session()),
            ),
            patch(
                "context_service.services.oauth.OAuthService",
                return_value=fake_oauth_svc,
            ),
        ):
            result = await _resolve_oauth_token("bad-token")

        assert result is None

    async def test_returns_none_when_user_not_found(self) -> None:
        _resolve_oauth_token = _import_resolve_oauth_token()

        fake_oauth_token = MagicMock()
        fake_oauth_token.user_id = uuid.uuid4()

        fake_session = _make_fake_session()
        fake_session.get = AsyncMock(return_value=None)

        fake_oauth_svc = AsyncMock()
        fake_oauth_svc.validate_access_token = AsyncMock(return_value=fake_oauth_token)

        with (
            patch(
                "context_service.db.postgres.get_session",
                return_value=_fake_session(fake_session),
            ),
            patch(
                "context_service.services.oauth.OAuthService",
                return_value=fake_oauth_svc,
            ),
        ):
            result = await _resolve_oauth_token("token-with-missing-user")

        assert result is None

    async def test_returns_auth_context_for_valid_token(self) -> None:
        from context_service.auth.context import AuthContext

        _resolve_oauth_token = _import_resolve_oauth_token()

        user_id = uuid.uuid4()

        fake_oauth_token = MagicMock()
        fake_oauth_token.user_id = user_id

        fake_user = MagicMock()
        fake_user.id = user_id
        fake_user.org_id = "org-acme"
        fake_user.workos_user_id = "wos-user-999"
        fake_user.email = "bob@example.com"

        fake_session = _make_fake_session()
        fake_session.get = AsyncMock(return_value=fake_user)

        fake_oauth_svc = AsyncMock()
        fake_oauth_svc.validate_access_token = AsyncMock(return_value=fake_oauth_token)

        with (
            patch(
                "context_service.db.postgres.get_session",
                return_value=_fake_session(fake_session),
            ),
            patch(
                "context_service.services.oauth.OAuthService",
                return_value=fake_oauth_svc,
            ),
        ):
            result = await _resolve_oauth_token("valid-token")

        assert isinstance(result, AuthContext)
        assert result.org_id == "org-acme"
        assert result.user_id == "wos-user-999"
        assert result.email == "bob@example.com"
        assert result.is_dev is False

    async def test_auth_context_db_user_id_populated(self) -> None:
        _resolve_oauth_token = _import_resolve_oauth_token()

        user_id = uuid.uuid4()

        fake_oauth_token = MagicMock()
        fake_oauth_token.user_id = user_id

        fake_user = MagicMock()
        fake_user.id = user_id
        fake_user.org_id = "org-acme"
        fake_user.workos_user_id = "wos-user-999"
        fake_user.email = "bob@example.com"

        fake_session = _make_fake_session()
        fake_session.get = AsyncMock(return_value=fake_user)

        fake_oauth_svc = AsyncMock()
        fake_oauth_svc.validate_access_token = AsyncMock(return_value=fake_oauth_token)

        with (
            patch(
                "context_service.db.postgres.get_session",
                return_value=_fake_session(fake_session),
            ),
            patch(
                "context_service.services.oauth.OAuthService",
                return_value=fake_oauth_svc,
            ),
        ):
            result = await _resolve_oauth_token("valid-token")

        assert result is not None
        assert result.db_user_id == user_id
