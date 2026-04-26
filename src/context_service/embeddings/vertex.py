"""VertexAI text-embedding-005 service client with retry support."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import httpx

from context_service.config.logging import get_logger

if TYPE_CHECKING:
    from context_service.config.settings import Settings

logger = get_logger(__name__)


class VertexAIEmbeddingError(Exception):
    """Raised when VertexAI embedding operations fail."""

    pass


class VertexAIEmbeddingService:
    """VertexAI embedding client using httpx + google-auth ADC."""

    TASK_DEFAULT = "default"

    def __init__(
        self,
        project: str,
        region: str = "us-central1",
        model: str = "text-embedding-005",
        dimensions: int = 768,
        _embedding_cache: Any | None = None,
    ) -> None:
        """Initialize the VertexAI embedding service.

        Args:
            project: GCP project ID.
            region: GCP region for VertexAI.
            model: VertexAI embedding model name.
            dimensions: Output embedding dimensions.
            _embedding_cache: Ignored (kept for interface compat).
        """
        self._project = project
        self._region = region
        self._model = model
        self._dimensions = dimensions
        self._client: httpx.AsyncClient | None = None
        self._credentials: Any = None

    @property
    def dimensions(self) -> int:
        return self._dimensions

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        _embedding_cache: Any | None = None,
    ) -> VertexAIEmbeddingService:
        """Create a VertexAIEmbeddingService from application settings.

        Args:
            settings: Application settings instance.
            _embedding_cache: Ignored (kept for interface compat).

        Returns:
            Configured VertexAIEmbeddingService.

        Raises:
            ValueError: If Vertex project ID is not configured.
        """
        if not settings.vertex_project_id:
            raise ValueError("VERTEX_PROJECT_ID is required for VertexAI embedding service")

        return cls(
            project=settings.vertex_project_id,
            region=settings.vertex_location,
        )

    @property
    def _api_url(self) -> str:
        return (
            f"https://{self._region}-aiplatform.googleapis.com/v1/"
            f"projects/{self._project}/locations/{self._region}/"
            f"publishers/google/models/{self._model}:predict"
        )

    def _get_auth_token(self) -> str:
        """Get a valid OAuth2 token via Application Default Credentials."""
        import google.auth
        import google.auth.transport.requests

        if self._credentials is None:
            self._credentials, _ = google.auth.default(
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )

        if not self._credentials.valid:
            self._credentials.refresh(google.auth.transport.requests.Request())

        token: str = self._credentials.token
        return token

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._client is None:
            transport = httpx.AsyncHTTPTransport(retries=3)
            self._client = httpx.AsyncClient(
                transport=transport,
                timeout=30.0,
            )
        return self._client

    async def _request_with_backoff(
        self, client: httpx.AsyncClient, payload: dict[str, object]
    ) -> httpx.Response:
        """Make API request with exponential backoff on 429 rate limit."""
        token = await asyncio.get_event_loop().run_in_executor(None, self._get_auth_token)
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        max_retries = 3
        for attempt in range(max_retries + 1):
            try:
                response = await client.post(self._api_url, json=payload, headers=headers)
                if response.status_code == 429 and attempt < max_retries:
                    wait = 2**attempt
                    logger.warning(
                        "vertex_rate_limited",
                        wait_seconds=wait,
                        attempt=attempt + 1,
                    )
                    await asyncio.sleep(wait)
                    continue
                if 500 <= response.status_code < 600 and attempt < max_retries:
                    wait = 2**attempt
                    logger.warning(
                        "vertex_server_error",
                        status_code=response.status_code,
                        wait_seconds=wait,
                        attempt=attempt + 1,
                    )
                    await asyncio.sleep(wait)
                    continue
                response.raise_for_status()
                return response
            except httpx.HTTPStatusError:
                raise
            except httpx.RequestError as e:
                if attempt < max_retries:
                    wait = 2**attempt
                    logger.warning(
                        "vertex_request_error",
                        error=str(e),
                        wait_seconds=wait,
                        attempt=attempt + 1,
                    )
                    await asyncio.sleep(wait)
                    continue
                raise
        raise VertexAIEmbeddingError("Max retries exceeded")

    def _build_payload(self, texts: list[str]) -> dict[str, object]:
        """Build the VertexAI predict request payload."""
        instances = [{"content": text} for text in texts]
        return {
            "instances": instances,
            "parameters": {"outputDimensionality": self._dimensions},
        }

    def _parse_response(self, data: dict[str, Any]) -> list[list[float]]:
        """Parse embeddings from VertexAI predict response."""
        predictions = data.get("predictions")
        if not predictions or not isinstance(predictions, list):
            raise VertexAIEmbeddingError(
                f"Unexpected response: missing 'predictions' in {list(data.keys())}"
            )
        embeddings: list[list[float]] = [p["embeddings"]["values"] for p in predictions]
        return embeddings

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts.

        Args:
            texts: List of texts to embed.

        Returns:
            List of embedding vectors.

        Raises:
            VertexAIEmbeddingError: If the API request fails.
        """
        if not texts:
            return []

        client = await self._get_client()
        payload = self._build_payload(texts)

        try:
            response = await self._request_with_backoff(client, payload)
        except httpx.HTTPStatusError as e:
            logger.error(
                "vertex_api_error",
                status_code=e.response.status_code,
                response_text=e.response.text,
            )
            raise VertexAIEmbeddingError(f"VertexAI API request failed: {e}") from e
        except httpx.RequestError as e:
            logger.error("vertex_request_error", error=str(e))
            raise VertexAIEmbeddingError(f"Failed to connect to VertexAI API: {e}") from e

        data = response.json()
        embeddings = self._parse_response(data)
        logger.debug("vertex_embed_complete", count=len(embeddings))
        return embeddings

    async def embed_single(self, text: str) -> list[float]:
        """Generate embedding for a single text.

        Args:
            text: Text to embed.

        Returns:
            Embedding vector.

        Raises:
            VertexAIEmbeddingError: If the API request fails.
        """
        embeddings = await self.embed([text])
        return embeddings[0]

    async def embed_query(self, query: str) -> list[float]:
        """Generate embedding for a search query.

        VertexAI has no task type distinction, so this uses the same
        embedding method as embed_single.

        Args:
            query: Search query text.

        Returns:
            Query embedding vector.

        Raises:
            VertexAIEmbeddingError: If the API request fails.
        """
        embeddings = await self.embed([query])
        logger.debug("vertex_embed_query_complete")
        return embeddings[0]

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
