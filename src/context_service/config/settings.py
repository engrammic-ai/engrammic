"""Application settings.

Ported pattern from contextr/app/core/settings.py.
"""

from functools import lru_cache

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Service
    service_name: str = "context-service"
    environment: str = "development"
    debug: bool = False
    # 127.0.0.1 is safer by default. Container deployments override via the
    # HOST env var (or by passing --host 0.0.0.0 to uvicorn) when the service
    # needs to be reachable from outside the container.
    host: str = "127.0.0.1"
    port: int = 8000
    reload: bool = False

    # Auth
    auth_enabled: bool = False
    workos_api_key: SecretStr | None = None
    workos_client_id: str | None = None
    # Sealed-session secret used by WorkOS SDK v6 to seal/unseal session
    # cookies (32-byte URL-safe base64). Required for authenticate_with_session_cookie.
    workos_cookie_password: SecretStr | None = None
    dev_org_id: str = "dev-org"
    dev_user_id: str = "dev-user"

    @model_validator(mode="after")
    def _validate_auth(self) -> "Settings":
        if self.environment == "production" and not self.auth_enabled:
            raise ValueError("AUTH_ENABLED must be true when ENVIRONMENT=production")
        if self.auth_enabled and (
            self.workos_api_key is None
            or self.workos_client_id is None
            or self.workos_cookie_password is None
        ):
            raise ValueError(
                "WORKOS_API_KEY, WORKOS_CLIENT_ID, and WORKOS_COOKIE_PASSWORD "
                "are required when AUTH_ENABLED=true"
            )
        return self

    # Graph (Memgraph)
    memgraph_uri: str = "bolt://localhost:7687"
    memgraph_user: str = ""
    memgraph_password: str = ""

    # Vector (Qdrant)
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = ""

    # Redis
    redis_url: str = "redis://localhost:6379"

    # Embeddings
    jina_api_key: str = ""
    vertex_project_id: str = ""
    vertex_location: str = "us-central1"

    # LLM Providers
    google_application_credentials: str = ""
    gemini_api_key: str = ""
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    default_llm_model: str = "gemini-2.0-flash"

    # Observability
    otel_endpoint: str = ""
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
