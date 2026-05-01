"""Application settings loaded from environment variables.

Sensitive settings (API keys, passwords) are loaded from environment variables.
Non-sensitive runtime settings are loaded from config/settings.yaml via
RuntimeConfig for hot-reload capability.

Settings precedence:
1. Environment variables (always override - for sensitive values)
2. config/settings.yaml (runtime settings, hot-reloadable)
3. Default values in code
"""

from __future__ import annotations

import contextvars
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Load .env file before any settings classes are instantiated
# override=False ensures docker-compose/runtime env vars take precedence over .env file
load_dotenv(override=False)


class CustodianSettings(BaseModel):
    """Custodian phase settings: budgets, flags, and model identifiers."""

    model_config = {"extra": "ignore"}

    enabled: bool = Field(default=False, description="Master gate for the Custodian subsystem")
    auto_publish_after_pass: bool = Field(
        default=False,
        description="If true, findings are published automatically at end of pass",
    )

    cluster_min_members_for_deep_pass: int = Field(
        default=5,
        description="Clusters below this member count skip the deep phase",
    )

    fast_pass_nominal_tokens: int = Field(default=2_000)
    fast_pass_hard_tokens: int = Field(default=6_000)
    fast_pass_request_limit: int = Field(default=5)
    fast_pass_tool_calls_limit: int = Field(default=8)
    plan_nominal_tokens: int = Field(default=4_500)
    deep_pass_nominal_tokens: int = Field(default=10_000)
    deep_pass_hard_tokens: int = Field(default=19_500)
    deep_pass_total_tokens_backstop: int = Field(default=20_000)
    deep_pass_soft_signal_ratio: float = Field(default=0.69)
    stitch_nominal_tokens: int = Field(default=1_200)
    stitch_hard_tokens: int = Field(default=1_500)

    max_cost_usd: float = Field(default=5.0)
    max_visits: int = Field(default=300)
    max_total_tokens: int = Field(default=5_000_000)
    per_visit_token_ceiling: int = Field(default=17_000)

    redis_trace_ttl_days: int = Field(default=30)
    concurrent_visit_limit: int = Field(default=4)
    per_visit_timeout_seconds: int = Field(default=120)

    flash_model: str = Field(default="google-vertex:gemini-2.5-flash")
    pro_model: str = Field(default="google-vertex:gemini-2.5-pro")
    pro_escalation_ab_sample_ratio: float = Field(default=0.10)

    min_edge_confidence: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Minimum confidence for proposed edges; below this they are structurally rejected",
    )


class RetrievalTuning(BaseModel):
    """Retrieval-ranking tuning knobs."""

    model_config = {"extra": "ignore"}

    walker_alpha: float = Field(default=0.4)
    walker_beta: float = Field(default=0.3)
    walker_gamma: float = Field(default=0.15)
    walker_delta: float = Field(default=0.15)
    walker_base_cost: float = Field(default=1.0)

    walker_tier_weight_hot: float = Field(default=1.0)
    walker_tier_weight_warm: float = Field(default=0.5)
    walker_tier_weight_cold: float = Field(default=0.25)
    walker_tier_weight_null: float = Field(default=0.1)
    walker_no_cluster_floor: float = Field(default=0.1)

    rrf_k: int = Field(default=60)
    # Per-channel RRF weights. Empty dict = classical unweighted RRF.
    # Opinionated defaults removed after 2026-04-26 post-mortem.
    rrf_channel_weights: dict[str, float] = Field(default_factory=dict)


class MemgraphConfig(BaseModel):
    model_config = {"extra": "ignore"}

    host: str = "localhost"
    port: int = 7687
    user: str = ""
    password: SecretStr = SecretStr("")
    pool_size: int = 50


class QdrantConfig(BaseModel):
    model_config = {"extra": "ignore"}

    host: str = "localhost"
    port: int = 6333
    grpc_port: int = 6334
    api_key: SecretStr | None = None


class RedisConfig(BaseModel):
    model_config = {"extra": "ignore"}

    host: str = "localhost"
    port: int = 6379
    password: SecretStr | None = None
    db: int = 0


class PostgresConfig(BaseModel):
    model_config = {"extra": "ignore"}

    dsn: SecretStr = SecretStr(
        "postgresql://context_service:context_service@localhost:5432/context_service"
    )


class InfraConfig(BaseModel):
    model_config = {"extra": "ignore"}

    memgraph: MemgraphConfig = Field(default_factory=MemgraphConfig)
    qdrant: QdrantConfig = Field(default_factory=QdrantConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)
    postgres: PostgresConfig = Field(default_factory=PostgresConfig)


class WalkerTuning(BaseModel):
    model_config = {"extra": "ignore"}

    alpha: float = 0.4
    beta: float = 0.3
    gamma: float = 0.15
    delta: float = 0.15
    base_cost: float = 1.0
    tier_hot: float = 1.0
    tier_warm: float = 0.5
    tier_cold: float = 0.25
    tier_null: float = 0.1
    no_cluster_floor: float = 0.1


class TiebreakConfig(BaseModel):
    model_config = {"extra": "ignore"}

    enabled: bool = False
    similarity_threshold: float = 0.85
    score_boost: float = 0.02


class EntityRetrievalConfig(BaseModel):
    model_config = {"extra": "ignore"}

    enabled: bool = False
    max_entities: int = 10
    # Optional pre-fusion cap. None = no cap. Lever preserved; opinionated
    # defaults reverted after 2026-04-26 post-mortem.
    entity_pre_fusion_cap: int | None = None


class ClusterRetrievalConfig(BaseModel):
    model_config = {"extra": "ignore"}

    enabled: bool = False
    level: int | None = 1
    top_k: int = 5


class SupersessionConfig(BaseModel):
    model_config = {"extra": "ignore"}

    enabled: bool = False
    confidence_threshold: float = 0.75
    cross_cluster_enabled: bool = False
    cross_cluster_max_group_size: int = 20


class RetrievalConfig(BaseModel):
    model_config = {"extra": "ignore"}

    walker: WalkerTuning = Field(default_factory=WalkerTuning)
    rrf_k: int = 60
    # Per-channel RRF weights. Empty dict = unweighted RRF.
    rrf_channel_weights: dict[str, float] = Field(default_factory=dict)
    hybrid_enabled: bool = False
    fresh_floor: float = 0.25
    sigma_default_days: dict[str, float] = Field(
        default_factory=lambda: {
            "ephemeral": 7.0,
            "standard": 90.0,
            "durable": 540.0,
            "permanent": 1825.0,
        }
    )
    temporal_decay_enabled: bool = False
    staleness_weight: float = 0.15
    tiebreak: TiebreakConfig = Field(default_factory=TiebreakConfig)
    entity: EntityRetrievalConfig = Field(default_factory=EntityRetrievalConfig)
    cluster: ClusterRetrievalConfig = Field(default_factory=ClusterRetrievalConfig)
    supersession: SupersessionConfig = Field(default_factory=SupersessionConfig)


class ServerConfig(BaseModel):
    model_config = {"extra": "ignore"}

    host: str = "0.0.0.0"
    port: int = 8000
    reload: bool = False
    workers: int = 4
    request_timeout: int = 30


class JinaConfig(BaseModel):
    model_config = {"extra": "ignore"}

    api_key: SecretStr | None = None
    model: str = ""
    dimensions: int = 0
    api_url: str = ""


class VertexConfig(BaseModel):
    model_config = {"extra": "ignore"}

    project: str | None = None
    region: str = "us-central1"
    location: str = "us-central1"
    credentials_path: str = "/app/secrets/gcp-sa.json"
    model: str = ""
    dimensions: int = 0


class SpladeConfig(BaseModel):
    model_config = {"extra": "ignore"}

    model: str = "prithivida/Splade_PP_en_v1"


class EmbeddingConfig(BaseModel):
    model_config = {"extra": "ignore"}

    provider: str = "jina"
    jina: JinaConfig = Field(default_factory=JinaConfig)
    vertex: VertexConfig = Field(default_factory=VertexConfig)
    splade: SpladeConfig = Field(default_factory=SpladeConfig)


class ProviderConfig(BaseModel):
    model_config = {"extra": "ignore"}

    api_url: str = ""


class LLMConfig(BaseModel):
    model_config = {"extra": "ignore"}

    provider: str = ""
    model: str = ""
    api_url: str | None = None
    api_key: SecretStr | None = None
    providers: dict[str, ProviderConfig] = Field(
        default_factory=lambda: {
            "anthropic": ProviderConfig(api_url="https://api.anthropic.com/v1/messages"),
            "openai": ProviderConfig(api_url="https://api.openai.com/v1/chat/completions"),
            "gemini": ProviderConfig(
                api_url="https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
            ),
        }
    )


class WorkosConfig(BaseModel):
    model_config = {"extra": "ignore"}

    api_key: SecretStr | None = None
    client_id: str | None = None
    redirect_uri: str | None = None


class AuthConfig(BaseModel):
    model_config = {"extra": "ignore"}

    workos: WorkosConfig = Field(default_factory=WorkosConfig)


class PromptsConfig(BaseModel):
    model_config = {"extra": "ignore"}

    preset: str = "gemini"
    mcp_preset: str | None = None


class FeaturesConfig(BaseModel):
    model_config = {"extra": "ignore"}

    mcp_enabled: bool = True
    otel_enabled: bool = False
    walker_entity_graph_mode: bool = True
    docs_enabled: bool = False


class CacheConfig(BaseModel):
    model_config = {"extra": "ignore"}

    enabled: bool = True
    node_ttl: int = 3600
    embedding_ttl: int = 604800
    lookup_ttl: int = 300


class ClusteringConfig(BaseModel):
    model_config = {"extra": "ignore"}

    auto_trigger_enabled: bool = False
    post_ingest_threshold: int = 50


class ExtractionConfig(BaseModel):
    model_config = {"extra": "ignore"}

    mode: str = "eager"
    batch_concurrency: int = 8


class RateLimitConfig(BaseModel):
    model_config = {"extra": "ignore"}

    requests_per_minute: int = 1000


class SecurityConfig(BaseModel):
    model_config = {"extra": "ignore"}

    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    rate_limit: RateLimitConfig = Field(default_factory=RateLimitConfig)
    max_request_body_mb: int = 10


class BearConfig(BaseModel):
    model_config = {"extra": "ignore"}

    api_key: SecretStr | None = None
    api_url: str = "https://api.thetokencompany.com/v1/compress"
    timeout_ms: int = 200
    enabled: bool = False


class StripeConfig(BaseModel):
    model_config = {"extra": "ignore"}

    secret_key: SecretStr | None = None
    webhook_secret: SecretStr | None = None
    webhook_secret_rollover: SecretStr | None = None
    price_id_team: str = ""
    meter_event_name: str = "context_service_retrieval"
    mock: bool = False
    default_tier: str = "team"


class ExternalConfig(BaseModel):
    model_config = {"extra": "ignore"}

    bear: BearConfig = Field(default_factory=BearConfig)


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        env_ignore_empty=True,
        extra="ignore",
        frozen=True,
    )

    # Nested sub-configs
    infra: InfraConfig = Field(default_factory=InfraConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    prompts: PromptsConfig = Field(default_factory=PromptsConfig)
    features: FeaturesConfig = Field(default_factory=FeaturesConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    clustering: ClusteringConfig = Field(default_factory=ClusteringConfig)
    extraction: ExtractionConfig = Field(default_factory=ExtractionConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    external: ExternalConfig = Field(default_factory=ExternalConfig)
    stripe: StripeConfig = Field(default_factory=StripeConfig)
    custodian: CustodianSettings = Field(default_factory=CustodianSettings)
    retrieval_tuning: RetrievalTuning = Field(default_factory=RetrievalTuning)

    # =========================================================================
    # Application Meta
    # =========================================================================

    app_name: str = Field(default="ContextService")
    version: str = Field(default="0.1.0")
    debug: bool = Field(default=False)
    environment: str = Field(default="development")
    auth_dev_mode: bool = Field(
        default=False,
        description=(
            "Enable auth dev mode. Accepts ck_dev_test key without validation. "
            "Set AUTH_DEV_MODE=true."
        ),
    )

    @property
    def is_development(self) -> bool:
        return self.environment == "development"

    @property
    def is_staging(self) -> bool:
        return self.environment == "staging"

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    # =========================================================================
    # Server Settings (flat shims)
    # =========================================================================

    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000)
    reload: bool = Field(default=False)

    # =========================================================================
    # Memgraph Settings
    # =========================================================================

    memgraph_host: str = Field(default="localhost")
    memgraph_port: int = Field(default=7687)
    memgraph_user: str = Field(default="")
    memgraph_password: SecretStr = Field(default=SecretStr(""))

    @property
    def memgraph_uri(self) -> str:
        return f"bolt://{self.memgraph_host}:{self.memgraph_port}"

    # =========================================================================
    # Qdrant Settings
    # =========================================================================

    qdrant_host: str = Field(default="localhost")
    qdrant_port: int = Field(default=6333)
    qdrant_grpc_port: int = Field(default=6334)
    qdrant_api_key: SecretStr | None = Field(default=None)

    @property
    def qdrant_url(self) -> str:
        return f"http://{self.qdrant_host}:{self.qdrant_port}"

    # =========================================================================
    # Jina Embedding Settings
    # =========================================================================

    jina_api_key: SecretStr | None = Field(default=None)
    jina_model: str = Field(default="")
    jina_dimensions: int = Field(default=0)
    jina_api_url: str = Field(default="")

    # =========================================================================
    # Embedding Provider
    # =========================================================================

    embedding_provider: str = Field(default="jina")

    hybrid_search_enabled: bool = Field(default=False)

    entity_retrieval_enabled: bool = Field(default=False)
    entity_retrieval_max_entities: int = Field(default=10)
    entity_retrieval_pre_fusion_cap: int | None = Field(default=None)

    walker_entity_graph_mode: bool = Field(
        default=True,
        description=(
            "When true, GraphWalker traverses the entity-graph projection in addition "
            "to direct binary :EDGE relationships. Required for multi-hop Graph-RAG "
            "on data produced by LLM extraction."
        ),
    )

    cluster_retrieval_enabled: bool = Field(default=False)
    cluster_retrieval_level: int | None = Field(default=1)
    cluster_retrieval_top_k: int = Field(default=5)
    commitment_retrieval_enabled: bool = Field(default=False)

    # =========================================================================
    # VertexAI Embedding Settings
    # =========================================================================

    vertex_project: str | None = Field(default=None)
    vertex_region: str = Field(default="us-central1")
    vertex_location: str = Field(default="us-central1")
    vertex_credentials_path: str = Field(default="/app/secrets/gcp-sa.json")
    vertex_model: str = Field(default="")
    vertex_dimensions: int = Field(default=0)

    # =========================================================================
    # LLM Settings
    # =========================================================================

    llm_provider: str = Field(default="")
    llm_api_key: SecretStr | None = Field(default=None)
    llm_model: str = Field(default="")
    llm_api_url: str | None = Field(default=None)
    default_llm_model: str = Field(default="gemini-2.0-flash")

    # Per-provider API keys (used by llm/ providers)
    anthropic_api_key: SecretStr | None = Field(default=None)
    openai_api_key: SecretStr | None = Field(default=None)
    gemini_api_key: SecretStr | None = Field(default=None)

    # =========================================================================
    # WorkOS Auth Settings
    # =========================================================================

    workos_api_key: SecretStr | None = Field(default=None)
    workos_client_id: str | None = Field(default=None)
    workos_redirect_uri: str | None = Field(default=None)

    # =========================================================================
    # Stripe Billing Shims
    # =========================================================================

    @property
    def stripe_secret_key(self) -> SecretStr | None:
        return self.stripe.secret_key

    @property
    def stripe_webhook_secret(self) -> SecretStr | None:
        return self.stripe.webhook_secret

    @property
    def stripe_webhook_secret_rollover(self) -> SecretStr | None:
        return self.stripe.webhook_secret_rollover

    @property
    def stripe_price_id_team(self) -> str:
        return self.stripe.price_id_team

    @property
    def stripe_meter_event_name(self) -> str:
        return self.stripe.meter_event_name

    @property
    def billing_mock(self) -> bool:
        return self.stripe.mock

    @property
    def billing_default_tier(self) -> str:
        return self.stripe.default_tier

    # =========================================================================
    # Prompt Preset Settings
    # =========================================================================

    prompt_preset: str = Field(default="gemini")
    mcp_prompt_preset: str | None = Field(default=None)

    # =========================================================================
    # MCP Settings
    # =========================================================================

    mcp_enabled: bool = Field(default=True)

    # =========================================================================
    # Observability Settings
    # =========================================================================

    otel_enabled: bool = Field(default=False)

    # =========================================================================
    # Cache Settings
    # =========================================================================

    cache_enabled: bool = Field(default=True)
    node_cache_ttl: int = Field(default=3600)
    embedding_cache_ttl: int = Field(default=604800)
    lookup_cache_ttl: int = Field(default=300)

    # =========================================================================
    # Temporal Decay Settings
    # =========================================================================

    temporal_decay_enabled: bool = Field(default=False)
    staleness_weight: float = Field(default=0.15, ge=0.0, le=1.0)
    tiebreak_enabled: bool = Field(default=False)
    tiebreak_similarity_threshold: float = Field(default=0.85, ge=0.0, le=1.0)
    tiebreak_score_boost: float = Field(default=0.02, ge=0.0, le=0.5)
    supersession_enabled: bool = Field(default=False)
    supersession_confidence_threshold: float = Field(default=0.75, ge=0.0, le=1.0)
    supersession_cross_cluster_enabled: bool = Field(default=False)
    supersession_cross_cluster_max_group_size: int = Field(default=20, gt=1)

    # =========================================================================
    # Clustering Auto-Trigger Settings
    # =========================================================================

    clustering_auto_trigger_enabled: bool = Field(default=False)
    clustering_post_ingest_threshold: int = Field(default=50, gt=0)
    extraction_batch_concurrency: int = Field(default=8, ge=1, le=32)

    # =========================================================================
    # BEAR Compression Settings
    # =========================================================================

    bear_api_key: SecretStr | None = Field(default=None)
    bear_api_url: str = Field(default="https://api.thetokencompany.com/v1/compress")
    bear_timeout_ms: int = Field(default=200)
    bear_enabled: bool = Field(default=False)

    # =========================================================================
    # Production Settings
    # =========================================================================

    workers: int = Field(default=4)
    request_timeout: int = Field(default=30)

    # =========================================================================
    # Redis Settings
    # =========================================================================

    redis_host: str = Field(default="localhost")
    redis_port: int = Field(default=6379)
    redis_password: SecretStr | None = Field(default=None)
    redis_db: int = Field(default=0)

    @property
    def redis_url(self) -> str:
        if self.redis_password:
            password = self.redis_password.get_secret_value()
            return f"redis://:{password}@{self.redis_host}:{self.redis_port}/{self.redis_db}"
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"

    # =========================================================================
    # Postgres Settings
    # =========================================================================

    postgres_dsn: SecretStr = Field(
        default=SecretStr(
            "postgresql://context_service:context_service@localhost:5432/context_service"
        )
    )

    # =========================================================================
    # YAML loading
    # =========================================================================

    @classmethod
    def settings_customise_sources(
        cls,
        _settings_cls: type[BaseSettings],
        init_settings: Any,
        env_settings: Any,
        dotenv_settings: Any,
        file_secret_settings: Any,
    ) -> tuple[Any, ...]:
        """Env vars outrank YAML (passed via init kwargs)."""
        return env_settings, init_settings, dotenv_settings, file_secret_settings

    @classmethod
    def from_yaml(cls, path: Path) -> Settings:
        """Build a fresh Settings from a YAML file."""
        data: dict[str, Any] = yaml.safe_load(path.read_text()) or {}
        return cls(**data)


# ContextVar holds the active Settings snapshot. Setting it is atomic at the
# interpreter level, so concurrent requests that call get_settings() mid-reload
# always see a fully-constructed, immutable instance — never a partially-updated one.
_settings_var: contextvars.ContextVar[Settings | None] = contextvars.ContextVar(
    "settings", default=None
)


def get_settings() -> Settings:
    """Return the active Settings snapshot, creating one on first call."""
    instance = _settings_var.get()
    if instance is None:
        instance = Settings()
        _settings_var.set(instance)
    return instance


def reload_settings(path: Path | None = None) -> Settings:
    """Replace the active Settings snapshot atomically.

    Callers within the same request that already hold a reference to the old
    snapshot are unaffected; subsequent calls to get_settings() return the new
    instance. Pass *path* to overlay YAML values on top of env vars.
    """
    fresh = Settings.from_yaml(path) if path is not None else Settings()
    _settings_var.set(fresh)
    return fresh


settings = get_settings()
