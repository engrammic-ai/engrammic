"""Google Gemini LLM provider using the VertexAI endpoint (SA-auth).

This provider talks to the VertexAI generateContent endpoint rather than the
free-tier generativelanguage.googleapis.com API. It authenticates via a GCP
service account (ADC-style) using google-auth.
"""

from __future__ import annotations

import asyncio
import os
import time
from datetime import UTC, datetime
from typing import Any

import httpx
from google.auth.transport.requests import (
    Request as GoogleAuthRequest,
)
from google.oauth2 import service_account

from context_service.config import get_settings
from context_service.config.logging import get_logger
from context_service.llm.base import LLMProvider, Usage, robust_json_loads, truncate

logger = get_logger(__name__)

_RETRY_DELAYS = (1.0, 3.0, 8.0)
_TOKEN_REFRESH_MARGIN_SECONDS = 300
_SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]


def _to_gemini_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Translate a JSON Schema dict to the subset Gemini's responseSchema accepts.

    Gemini's responseSchema supports OpenAPI 3.0 schema but drops several JSON
    Schema features:

    - additionalProperties is unsupported -- strip it.
    - Union types like type: ["string", "null"] become type: string with nullable: true.
    - null values in enum lists are dropped.
    - minimum / maximum on numbers are preserved.

    Returns a new dict; does not mutate the input.
    """
    if not isinstance(schema, dict):
        return schema

    out: dict[str, Any] = {}
    for key, value in schema.items():
        if key == "additionalProperties":
            continue
        if key == "type" and isinstance(value, list):
            non_null = [t for t in value if t != "null"]
            if len(non_null) == 1:
                out["type"] = non_null[0]
                if "null" in value:
                    out["nullable"] = True
            elif non_null:
                out["type"] = non_null[0]
            continue
        if key == "enum" and isinstance(value, list):
            out["enum"] = [v for v in value if v is not None]
            continue
        if key == "properties" and isinstance(value, dict):
            out["properties"] = {k: _to_gemini_schema(v) for k, v in value.items()}
            continue
        if key == "items" and isinstance(value, dict):
            out["items"] = _to_gemini_schema(value)
            continue
        out[key] = value
    return out


class VertexGeminiError(Exception):
    """Raised when VertexAI Gemini API operations fail."""


class VertexGeminiProvider(LLMProvider):
    """Gemini LLM provider using the VertexAI generateContent endpoint.

    Authentication uses a GCP service account file. Tokens are cached on the
    credentials object and refreshed proactively when close to expiry.
    """

    def __init__(
        self,
        project: str,
        location: str,
        model: str,
        credentials_path: str | None = None,
    ) -> None:
        self._project = project
        self._location = location
        self._model = model

        resolved_path = credentials_path or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        if not resolved_path:
            raise VertexGeminiError(
                "No service account credentials path provided and "
                "GOOGLE_APPLICATION_CREDENTIALS is not set"
            )
        # Local dev fallback: if Docker path doesn't exist, try ./secrets/
        if not os.path.exists(resolved_path) and resolved_path.startswith("/app/secrets/"):
            local_path = resolved_path.replace("/app/secrets/", "./secrets/")
            if os.path.exists(local_path):
                resolved_path = local_path
        self._credentials_path = resolved_path
        self._credentials: Any | None = None
        self._credentials_lock = asyncio.Lock()

        self._endpoint = (
            f"https://{location}-aiplatform.googleapis.com/v1/projects/{project}"
            f"/locations/{location}/publishers/google/models/{model}:generateContent"
        )
        self._client: httpx.AsyncClient | None = None

    @classmethod
    def from_settings(cls, model: str | None = None) -> VertexGeminiProvider:
        """Create provider from application settings."""
        settings = get_settings()
        return cls(
            project=settings.vertex_project or settings.vertex_project_id,
            location=settings.vertex_location,
            model=model or settings.default_llm_model,
            credentials_path=settings.vertex_credentials_path
            or settings.google_application_credentials
            or None,
        )

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers={"Content-Type": "application/json"},
            )
        return self._client

    def _load_credentials(self) -> Any:
        return service_account.Credentials.from_service_account_file(  # type: ignore[no-untyped-call]
            self._credentials_path,
            scopes=_SCOPES,
        )

    async def _ensure_token(self, force_refresh: bool = False) -> str:
        """Return a valid access token, refreshing if needed."""
        async with self._credentials_lock:
            if self._credentials is None:
                self._credentials = await asyncio.to_thread(self._load_credentials)

            creds: Any = self._credentials
            needs_refresh = force_refresh or creds.token is None or creds.expired
            if not needs_refresh and creds.expiry is not None:
                now = datetime.now(UTC).replace(tzinfo=None)
                remaining = (creds.expiry - now).total_seconds()
                if remaining < _TOKEN_REFRESH_MARGIN_SECONDS:
                    needs_refresh = True

            if needs_refresh:
                await asyncio.to_thread(creds.refresh, GoogleAuthRequest())

            token = creds.token
            if not token:
                raise VertexGeminiError("Failed to obtain access token from service account")
            return str(token)

    @staticmethod
    def _convert_messages(
        messages: list[dict[str, str]],
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        """Convert OpenAI chat-style messages to Vertex Gemini contents."""
        contents: list[dict[str, Any]] = []
        system_texts: list[str] = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                if content:
                    system_texts.append(content)
                continue
            mapped_role = "model" if role == "assistant" else "user"
            contents.append({"role": mapped_role, "parts": [{"text": content}]})

        system_instruction: dict[str, Any] | None = None
        if system_texts:
            system_instruction = {"parts": [{"text": "\n\n".join(system_texts)}]}
        return contents, system_instruction

    def _build_payload(
        self,
        messages: list[dict[str, str]],
        *,
        structured: bool,
        schema: dict[str, Any] | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        contents, system_instruction = self._convert_messages(messages)
        payload: dict[str, Any] = {"contents": contents}
        if system_instruction is not None:
            payload["systemInstruction"] = system_instruction
        gen_config: dict[str, Any] = {}
        if structured:
            gen_config["responseMimeType"] = "application/json"
            if schema is not None:
                gen_config["responseSchema"] = _to_gemini_schema(schema)
        if temperature is not None:
            gen_config["temperature"] = temperature
        if gen_config:
            payload["generationConfig"] = gen_config
        return payload

    async def _post_with_retry(
        self,
        client: httpx.AsyncClient,
        payload: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> httpx.Response:
        """POST to the Vertex endpoint with retry on transient errors."""
        last_exc: httpx.RequestError | None = None
        attempted_token_refresh = False
        post_kwargs: dict[str, Any] = {}
        if timeout is not None:
            post_kwargs["timeout"] = timeout
        for attempt in range(len(_RETRY_DELAYS) + 1):
            token = await self._ensure_token()
            try:
                response = await client.post(
                    self._endpoint,
                    json=payload,
                    headers={"Authorization": f"Bearer {token}"},
                    **post_kwargs,
                )
                response.raise_for_status()
                return response
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 401 and not attempted_token_refresh:
                    attempted_token_refresh = True
                    logger.warning(
                        "VertexGemini 401 - forcing token refresh and retrying",
                        error=str(e),
                    )
                    await self._ensure_token(force_refresh=True)
                    continue
                logger.error(
                    "VertexGemini API error",
                    status_code=e.response.status_code,
                    response_text=truncate(e.response.text),
                )
                raise VertexGeminiError(
                    f"VertexGemini API request failed: {type(e).__name__}: {e!r}"
                ) from e
            except httpx.RequestError as e:
                last_exc = e
                if attempt < len(_RETRY_DELAYS):
                    delay = _RETRY_DELAYS[attempt]
                    logger.warning(
                        "VertexGemini retry",
                        attempt=attempt + 1,
                        max_attempts=len(_RETRY_DELAYS),
                        error=str(e),
                    )
                    await asyncio.sleep(delay)
                    continue
                logger.error("VertexGemini API request error", error=str(e))
                raise VertexGeminiError(
                    f"Failed to connect to VertexGemini API: {type(e).__name__}: {e!r}"
                ) from e
        assert last_exc is not None
        raise VertexGeminiError(
            f"Failed to connect to VertexGemini API: {type(last_exc).__name__}: {last_exc!r}"
        ) from last_exc

    def _extract_usage(self, data: dict[str, Any]) -> Usage:
        meta = data.get("usageMetadata") or {}
        input_tokens = int(meta.get("promptTokenCount") or 0)
        output_tokens = int(meta.get("candidatesTokenCount") or 0)
        return Usage(
            model=self._model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    def _extract_text(self, data: dict[str, Any]) -> str:
        candidates = data.get("candidates")
        if not candidates or not isinstance(candidates, list):
            raise VertexGeminiError(
                f"Unexpected response structure: missing 'candidates' in {list(data.keys())}"
            )
        content = candidates[0].get("content", {})
        parts = content.get("parts")
        if not parts or not isinstance(parts, list):
            raise VertexGeminiError("No content parts in response")
        text = parts[0].get("text")
        if text is None:
            raise VertexGeminiError("No text in response content part")
        return str(text)

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        timeout: float | None = None,
        max_tokens: int = 4096,  # noqa: ARG002
    ) -> tuple[str, Usage]:
        client = await self._get_client()
        payload = self._build_payload(messages, structured=False, temperature=temperature)
        start = time.monotonic()
        response = await self._post_with_retry(client, payload, timeout=timeout)
        wall_ms = int((time.monotonic() - start) * 1000)
        data = response.json()
        usage = self._extract_usage(data)
        logger.debug("VertexGemini completion", model=self._model, wall_ms=wall_ms)
        return self._extract_text(data), usage

    async def extract_structured(
        self,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        *,
        timeout: float | None = None,
        max_tokens: int = 4096,  # noqa: ARG002
    ) -> tuple[dict[str, Any], Usage]:
        client = await self._get_client()
        payload = self._build_payload(messages, structured=True, schema=schema)
        start = time.monotonic()
        response = await self._post_with_retry(client, payload, timeout=timeout)
        wall_ms = int((time.monotonic() - start) * 1000)
        data = response.json()
        text = self._extract_text(data)
        result: dict[str, Any] = robust_json_loads(text)
        usage = self._extract_usage(data)
        logger.debug("VertexGemini extract_structured", model=self._model, wall_ms=wall_ms)
        return result, usage

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
