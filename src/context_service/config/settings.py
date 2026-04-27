"""Application settings.

Ported pattern from contextr/app/core/settings.py.
"""

from functools import lru_cache

from pydantic import model_validator
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
    host: str = "0.0.0.0"
    port: int = 8000
    reload: bool = False

    # Auth
    auth_enabled: bool = False
    workos_api_key: str | None = None
    workos_client_id: str | None = None
    dev_org_id: str = "dev-org"
    dev_user_id: str = "dev-user"

    @model_validator(mode="after")
    def _validate_auth(self) -> "Settings":
        if self.environment == "production" and not self.auth_enabled:
            raise ValueError("AUTH_ENABLED must be true when ENVIRONMENT=production")
        if self.auth_enabled and (self.workos_api_key is None or self.workos_client_id is None):
            raise ValueError(
                "WORKOS_API_KEY and WORKOS_CLIENT_ID are required when AUTH_ENABLED=true"
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
