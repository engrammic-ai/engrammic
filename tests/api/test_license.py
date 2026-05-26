"""License renewal endpoint tests."""

from __future__ import annotations

import os
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from context_service.api.routes.license import router


def _make_app() -> FastAPI:
    """Build a minimal FastAPI app with the license router mounted."""
    app = FastAPI()
    app.include_router(router)
    return app


def test_renew_returns_503_without_private_key() -> None:
    """Returns 503 if LICENSE_PRIVATE_KEY not configured."""
    app = _make_app()
    env = {k: v for k, v in os.environ.items() if k != "LICENSE_PRIVATE_KEY"}
    with patch.dict(os.environ, env, clear=True):
        client = TestClient(app)
        response = client.post(
            "/license/renew",
            headers={"Authorization": "Bearer ENGR_test"},
        )
    assert response.status_code == 503


def test_renew_returns_401_without_bearer() -> None:
    """Returns 401 if Authorization header missing Bearer prefix."""
    app = _make_app()
    with patch.dict(os.environ, {"LICENSE_PRIVATE_KEY": "fake-key"}):
        client = TestClient(app)
        response = client.post(
            "/license/renew",
            headers={"Authorization": "ENGR_test"},
        )
    assert response.status_code == 401
