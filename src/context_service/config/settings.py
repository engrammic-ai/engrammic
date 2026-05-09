"""Application settings — single canonical source.

All settings live here. core/settings.py re-exports from here for
backwards compatibility with library code that predates this consolidation.

Settings precedence:
1. Environment variables (always override)
2. config/settings.yaml (runtime settings, hot-reloadable via reload_settings)
3. Default values in code
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv(override=False)


class CustodianSettings(BaseModel):
    """Custodian phase settings: budgets, flags, and model identifiers."""

    model_config = ConfigDict(frozen=True, extra="ignore")

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


class CustodianIdentityConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    enabled: bool = True
    model: str = "google-vertex:gemini-2.5-flash"
    timeout_seconds: int = 30
    batch_size: int = 5
    batch_window_seconds: float = 2.0


class SynthesizerIdentityConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    enabled: bool = True
    model: str = "google-vertex:gemini-2.5-pro"
    timeout_seconds: int = 60
    threshold_pending_nodes: int = 50
    schedule_cron: str = "0 * * * *"


class DecayClassConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    half_life_days: int
    hard_delete_days: int


class GroundskeeperIdentityConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    enabled: bool = True
    schedule_cron: str = "0 3 * * *"
    decay_classes: dict[str, DecayClassConfig] = Field(default_factory=dict)


class ValidatorIdentityConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    enabled: bool = True
    model: str = "google-vertex:gemini-2.5-pro"
    timeout_seconds: int = 5
    fail_open: bool = True


class IdentitiesConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    custodian: CustodianIdentityConfig = Field(default_factory=CustodianIdentityConfig)
    synthesizer: SynthesizerIdentityConfig = Field(default_factory=SynthesizerIdentityConfig)
    groundskeeper: GroundskeeperIdentityConfig = Field(default_factory=GroundskeeperIdentityConfig)
    validator: ValidatorIdentityConfig = Field(default_factory=ValidatorIdentityConfig)


class RetrievalTuning(BaseModel):
    """Retrieval-ranking tuning knobs."""

    model_config = ConfigDict(frozen=True, extra="ignore")

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
    model_config = ConfigDict(frozen=True, extra="ignore")

    host: str = "localhost"
    port: int = 7687
    user: str = ""
    password: SecretStr = SecretStr("")
    pool_size: int = 50


class QdrantConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    host: str = "localhost"
    port: int = 6333
    grpc_port: int = 6334
    api_key: SecretStr | None = None


class RedisConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    host: str = "localhost"
    port: int = 6379
    password: SecretStr | None = None
    db: int = 0


class PostgresConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    host: str = "localhost"
    port: int = 5432
    user: str = "context"
    password: SecretStr = SecretStr("context")
    database: str = "context_service"

    @property
    def dsn(self) -> str:
        """Build PostgreSQL DSN from components."""
        pwd = self.password.get_secret_value()
        return f"postgresql://{self.user}:{pwd}@{self.host}:{self.port}/{self.database}"


class InfraConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    memgraph: MemgraphConfig = Field(default_factory=MemgraphConfig)
    qdrant: QdrantConfig = Field(default_factory=QdrantConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)
    postgres: PostgresConfig = Field(default_factory=PostgresConfig)


class WalkerTuning(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

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
    model_config = ConfigDict(frozen=True, extra="ignore")

    enabled: bool = False
    similarity_threshold: float = 0.85
    score_boost: float = 0.02


class EntityRetrievalConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    enabled: bool = False
    max_entities: int = 10
    # Optional pre-fusion cap. None = no cap. Lever preserved; opinionated
    # defaults reverted after 2026-04-26 post-mortem.
    entity_pre_fusion_cap: int | None = None


class ClusterRetrievalConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    enabled: bool = False
    level: int | None = 1
    top_k: int = 5


class SupersessionConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    enabled: bool = False
    confidence_threshold: float = 0.75
    cross_cluster_enabled: bool = False
    cross_cluster_max_group_size: int = 20


class RetrievalConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    walker: WalkerTuning = Field(default_factory=WalkerTuning)
    rrf_k: int = 60
    # Per-channel RRF weights. Empty dict = unweighted RRF.
    rrf_channel_weights: dict[str, float] = Field(default_factory=dict)
    hybrid_enabled: bool = False
    fresh_floor: float = 0.25
    staleness_weight: float = 0.15
    tiebreak: TiebreakConfig = Field(default_factory=TiebreakConfig)
    entity: EntityRetrievalConfig = Field(default_factory=EntityRetrievalConfig)
    cluster: ClusterRetrievalConfig = Field(default_factory=ClusterRetrievalConfig)
    supersession: SupersessionConfig = Field(default_factory=SupersessionConfig)


class ServerConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    host: str = "127.0.0.1"
    port: int = 8000
    reload: bool = False
    workers: int = 4
    request_timeout: int = 30


class JinaConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    api_key: SecretStr | None = None
    model: str = ""
    dimensions: int = 0
    api_url: str = ""


class VertexConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    project: str | None = None
    region: str = "us-central1"
    location: str = "us-central1"
    credentials_path: str = "/app/secrets/gcp-sa.json"
    model: str = ""
    dimensions: int = 0


class SpladeConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    model: str = "prithivida/Splade_PP_en_v1"


class EmbeddingConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    provider: str = "jina"
    jina: JinaConfig = Field(default_factory=JinaConfig)
    vertex: VertexConfig = Field(default_factory=VertexConfig)
    splade: SpladeConfig = Field(default_factory=SpladeConfig)


class ProviderConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    api_url: str = ""


class LLMConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

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
    model_config = ConfigDict(frozen=True, extra="ignore")

    api_key: SecretStr | None = None
    client_id: str | None = None
    redirect_uri: str | None = None


class AuthConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    workos: WorkosConfig = Field(default_factory=WorkosConfig)


class PromptsConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    preset: str = "gemini"
    mcp_preset: str | None = None


class AutoReflectConfig(BaseModel):
    """Feature flags for automatic MetaObservation generation."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    enabled: bool = Field(default=False, description="Master gate for auto-reflection")
    on_supersession: bool = Field(
        default=True, description="Generate observation on fact supersession"
    )
    on_revision: bool = Field(default=True, description="Generate observation on belief revision")
    triggers_enabled: bool = Field(
        default=False,
        description="Gate for v1.3d auto-reflection triggers (confidence shift, contradiction, uncertainty)",
    )
    confidence_shift_threshold: float = Field(
        default=0.2,
        ge=0.0,
        le=1.0,
        description="Minimum confidence delta to trigger a confidence-shift auto-reflection",
    )
    uncertainty_threshold: float = Field(
        default=0.4,
        ge=0.0,
        le=1.0,
        description="Max average result confidence below which reflection_suggested is set",
    )
    max_reflections_per_hour: int = Field(
        default=10,
        ge=1,
        description="Rate-limit cap: maximum auto-reflections per silo per hour",
    )


class FeaturesConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    mcp_enabled: bool = True
    otel_enabled: bool = False
    walker_entity_graph_mode: bool = True
    docs_enabled: bool = False


class TelemetryConfig(BaseModel):
    """Self-hosted telemetry configuration."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    enabled: bool = Field(
        default=True,
        description="Tier 1: anonymous aggregate telemetry (default on)",
    )
    silos: list[str] = Field(
        default_factory=list,
        description="Tier 2: silo IDs to include in telemetry. Empty = tier 1 only. ['*'] = all silos.",
    )
    beacon_url: str = Field(
        default="https://tel.engrammic.com/v1/beacon",
        description="Endpoint for telemetry heartbeats",
    )
    beacon_interval_hours: int = Field(
        default=24,
        ge=1,
        le=168,
        description="Hours between beacon heartbeats",
    )

    @property
    def all_silos(self) -> bool:
        return self.silos == ["*"]

    @property
    def tier2_enabled(self) -> bool:
        return len(self.silos) > 0


class CacheConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    enabled: bool = True
    node_ttl: int = 3600
    embedding_ttl: int = 604800
    lookup_ttl: int = 300


class ClusteringConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    auto_trigger_enabled: bool = False
    post_ingest_threshold: int = 50


class ExtractionConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    mode: str = "eager"
    batch_concurrency: int = 8


class RateLimitConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    requests_per_minute: int = 1000


class SecurityConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    rate_limit: RateLimitConfig = Field(default_factory=RateLimitConfig)
    max_request_body_mb: int = 10
    admin_api_key: SecretStr | None = Field(
        default=None,
        description="Bearer token required for /admin/* endpoints. None disables the check (dev only).",
    )


class BearConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    api_key: SecretStr | None = None
    api_url: str = "https://api.thetokencompany.com/v1/compress"
    timeout_ms: int = 200
    enabled: bool = False


class StripeConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    secret_key: SecretStr | None = None
    webhook_secret: SecretStr | None = None
    webhook_secret_rollover: SecretStr | None = None
    price_id_team: str = ""
    meter_event_name: str = "context_service_retrieval"
    mock: bool = False
    default_tier: str = "team"


class ExternalConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    bear: BearConfig = Field(default_factory=BearConfig)


class PatternConfig(BaseModel):
    """Configuration for pattern detection (v1.3a/b)."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    detection_enabled: bool = Field(
        default=False,
        description="Gate for co_occurrence and causal_chain pattern detection.",
    )
    llm_enabled: bool = Field(
        default=False,
        description="Gate for LLM-based pattern detection (requires detection_enabled).",
    )


class CausalConfig(BaseModel):
    """Configuration for causal edge extraction, inference, and query exposure."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    extraction_enabled: bool = Field(
        default=False,
        description="Gate for causal claim extraction during document processing.",
    )
    inference_enabled: bool = Field(
        default=False,
        description="Gate for the causal_transitivity Dagster asset.",
    )
    query_enabled: bool = Field(
        default=False,
        description="Gate for returning CAUSES/CORROBORATES/PREVENTS edges in MCP responses.",
    )
    max_transitivity_depth: int = Field(
        default=3,
        ge=2,
        le=4,
        description="Maximum hop count for transitivity inference.",
    )
    min_inferred_confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Minimum confidence for materialized inferred edges.",
    )
    confidence_formula: str = Field(
        default="multiplicative",
        description="Formula: 'multiplicative', 'minimum', or 'geometric_mean'.",
    )
    transitivity_batch_size: int = Field(
        default=500,
        ge=1,
        description="Anchor nodes per batch in transitivity asset.",
    )
    max_invalidation_depth: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Maximum cascade depth when tombstoning derived inferred edges on supersession.",
    )


class WeakLinksSettings(BaseModel):
    """Weak links (speculative RELATED_TO edges) configuration."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    enabled: bool = Field(default=True, description="Enable weak link creation")

    # Ingest-time creation
    similarity_threshold: float = Field(default=0.75, ge=0.0, le=1.0)
    max_links_per_node: int = Field(default=5, ge=1)
    top_k_candidates: int = Field(default=10, ge=1)
    initial_weight_multiplier: float = Field(default=0.5, ge=0.0, le=1.0)

    # Promotion thresholds
    promotion_min_weight: float = Field(default=0.6, ge=0.0, le=1.0)
    promotion_min_edge_heat: float = Field(default=0.3, ge=0.0)
    promotion_require_fact_endpoints: bool = Field(default=True)

    # Pruning thresholds
    pruning_max_age_days: int = Field(default=30, ge=1)
    pruning_min_edge_heat: float = Field(default=0.1, ge=0.0)

    # Embedding model tracking
    embedding_model_version: str = Field(default="jina-v3")


def _load_identities_config() -> IdentitiesConfig:
    config_path = Path(__file__).parent / "identities.yaml"
    if config_path.exists():
        with open(config_path) as f:
            data = yaml.safe_load(f)
            return IdentitiesConfig(**data.get("identities", {}))
    return IdentitiesConfig()


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
    auto_reflect: AutoReflectConfig = Field(default_factory=AutoReflectConfig)
    causal: CausalConfig = Field(default_factory=CausalConfig)
    pattern: PatternConfig = Field(default_factory=PatternConfig)
    weak_links: WeakLinksSettings = Field(default_factory=WeakLinksSettings)
    telemetry: TelemetryConfig = Field(default_factory=TelemetryConfig)
    identities: IdentitiesConfig = Field(default_factory=_load_identities_config)

    # =========================================================================
    # Application Meta
    # =========================================================================

    app_name: str = Field(default="ContextService")
    version: str = Field(default="1.3.0")
    debug: bool = Field(default=False)
    environment: str = Field(default="development")

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

    host: str = Field(default="127.0.0.1")
    port: int = Field(default=8000)
    reload: bool = Field(default=False)

    # =========================================================================
    # Auth Flags
    # =========================================================================

    auth_enabled: bool = Field(default=False)
    dev_org_id: str = Field(default="dev-org")
    dev_user_id: str = Field(default="dev-user")
    dev_agent_id: str = Field(default="dev-agent")

    # =========================================================================
    # Memgraph Settings
    # =========================================================================

    memgraph_host: str = Field(default="localhost")
    memgraph_port: int = Field(default=7687)
    memgraph_user: str = Field(default="")
    memgraph_password: SecretStr = Field(default=SecretStr(""))
    memgraph_pool_size: int = Field(default=50)
    memgraph_pool_timeout: float = Field(default=30.0)

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
    # LiteLLM Embedding Settings
    # =========================================================================

    litellm_embedding_model: str = Field(default="openai/text-embedding-3-small")
    embedding_dimensions: int = Field(default=768)

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
    vertex_project_id: str = Field(default="")
    vertex_region: str = Field(default="us-central1")
    vertex_location: str = Field(default="us-central1")
    vertex_credentials_path: str = Field(default="/app/secrets/gcp-sa.json")
    vertex_model: str = Field(default="")
    vertex_dimensions: int = Field(default=0)

    # =========================================================================
    # Google Application Credentials (flat shim for ADC / local dev)
    # =========================================================================

    google_application_credentials: str = Field(default="")

    # =========================================================================
    # LLM Settings
    # =========================================================================

    llm_provider: str = Field(default="")
    default_llm_model: str = Field(default="gemini-2.0-flash")

    # Per-provider API keys (used by llm/ providers)
    anthropic_api_key: SecretStr | None = Field(default=None)
    anthropic_api_version: str = Field(default="2023-06-01")
    openai_api_key: SecretStr | None = Field(default=None)
    gemini_api_key: SecretStr | None = Field(default=None)

    # Self-hosted LLM (Ollama, vLLM)
    ollama_base_url: str = Field(default="http://localhost:11434")

    # =========================================================================
    # WorkOS Auth Settings
    # =========================================================================

    workos_api_key: SecretStr | None = Field(default=None)
    workos_client_id: str | None = Field(default=None)
    workos_redirect_uri: str | None = Field(default=None)
    # Sealed-session secret used by WorkOS SDK v6 to seal/unseal session
    # cookies (32-byte URL-safe base64). Required for authenticate_with_session_cookie.
    workos_cookie_password: SecretStr | None = Field(default=None)

    @model_validator(mode="after")
    def _validate_auth(self) -> Settings:
        if self.environment == "production" and not self.auth_enabled:
            raise ValueError("AUTH_ENABLED must be true when ENVIRONMENT=production")
        if self.auth_enabled and (self.workos_api_key is None or self.workos_client_id is None):
            raise ValueError(
                "WORKOS_API_KEY and WORKOS_CLIENT_ID are required when AUTH_ENABLED=true"
            )
        if self.auth_enabled and self.workos_cookie_password is None:
            raise ValueError("WORKOS_COOKIE_PASSWORD is required when AUTH_ENABLED=true")
        return self

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
    log_level: str = Field(default="INFO")
    llm_max_concurrency: int = Field(default=20)

    # =========================================================================
    # Cache Settings
    # =========================================================================

    cache_enabled: bool = Field(default=True)
    node_cache_ttl: int = Field(default=3600)
    embedding_cache_ttl: int = Field(default=604800)
    lookup_cache_ttl: int = Field(default=300)

    # =========================================================================
    # Temporal Decay Settings (unified decay via heat asset)
    # =========================================================================

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
    # TODO: BEAR compression subsystem - implement in future
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
    redis_max_connections: int = Field(default=50)

    @property
    def redis_url(self) -> str:
        if self.redis_password:
            password = self.redis_password.get_secret_value()
            return f"redis://:{password}@{self.redis_host}:{self.redis_port}/{self.redis_db}"
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"

    # =========================================================================
    # Postgres Settings
    # =========================================================================

    postgres_host: str = Field(default="localhost")
    postgres_port: int = Field(default=5432)
    postgres_user: str = Field(default="context")
    postgres_password: SecretStr = Field(default=SecretStr("context"))
    postgres_database: str = Field(default="context_service")

    @property
    def postgres_dsn(self) -> str:
        pwd = self.postgres_password.get_secret_value()
        return f"postgresql://{self.postgres_user}:{pwd}@{self.postgres_host}:{self.postgres_port}/{self.postgres_database}"

    # =========================================================================
    # Retention Policy Defaults
    # =========================================================================

    retention_ephemeral_max_age_hours: int = Field(default=24, ge=1)
    retention_standard_max_age_days: int = Field(default=7, ge=1)
    retention_standard_heat_threshold: float = Field(default=0.3, ge=0.0, le=1.0)
    retention_durable_max_age_days: int = Field(default=30, ge=1)
    retention_durable_heat_threshold: float = Field(default=0.2, ge=0.0, le=1.0)
    retention_meta_observation_max_count: int = Field(default=100, ge=10)
    retention_grace_period_days: int = Field(default=7, ge=1)

    # =========================================================================
    # Summarization Settings
    # =========================================================================

    summarization_provider: str = Field(default="anthropic")
    summarization_model: str = Field(default="claude-haiku-4-5-20250929")
    summarization_max_tokens: int = Field(default=500)

    # =========================================================================
    # Engine Tuning
    # =========================================================================

    belief_density_threshold: int = Field(
        default=3,
        ge=1,
        description="Minimum number of facts required to synthesise a Wisdom-layer belief",
    )
    revision_cosine_threshold: float = Field(
        default=0.15,
        ge=0.0,
        le=1.0,
        description="Cosine distance above which a belief centroid is considered stale",
    )
    compaction_step_threshold: int = Field(
        default=5,
        ge=1,
        description="Chains with <= this many steps are inlined; longer chains use LLM summarization",
    )
    session_compaction_enabled: bool = Field(
        default=False,
        description="Gate for v1.3c session compaction (context_close_reasoning MCP tool)",
    )
    session_timeout_minutes: int = Field(
        default=30,
        ge=1,
        description="Minutes of inactivity after which an open ReasoningSession is auto-closed.",
    )
    pattern_min_frequency: int = Field(
        default=2,
        ge=1,
        description="Minimum observation frequency for a pattern to be retained",
    )

    # =========================================================================
    # Proposal Worker Thresholds
    # =========================================================================

    validator_auto_synthesis_threshold: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Confidence above which T3 auto-creates Belief from cluster.",
    )
    validator_proposal_threshold: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Confidence above which (but below auto_synthesis) creates ProposedBelief.",
    )

    # =========================================================================
    # Signals — heat / freshness / priority
    # =========================================================================

    freshness_weight: float = Field(default=0.3)
    freshness_sigma_days: int = Field(default=30)
    access_stream_maxlen: int = Field(default=100_000)

    # Signals enhancement (v1d) — all default OFF for safe rollout
    expansion_generation_enabled: bool = Field(
        default=True,
        description="When true, ExpansionGenerator runs during store() and the expansion is concatenated to the SPLADE input.",
    )

    heat_ranking_enabled: bool = Field(default=False)
    unified_decay_enabled: bool = Field(default=False)
    write_events_enabled: bool = Field(default=False)

    # Heat ranking tuning
    heat_weight: float = Field(default=0.1)
    heat_half_life_days: int = Field(default=7)
    heat_read_weight: float = Field(default=1.0)
    heat_write_weight: float = Field(default=0.5)
    heat_dedup_window_seconds: int = Field(default=300)

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


_settings_cache: Settings | None = None


def get_settings() -> Settings:
    """Return the cached Settings singleton."""
    global _settings_cache
    if _settings_cache is None:
        _settings_cache = Settings()
    return _settings_cache


def reload_settings(path: Path | None = None) -> Settings:
    """Replace the cached Settings singleton.

    Pass *path* to load values from a YAML file on top of env vars.
    """
    global _settings_cache
    _settings_cache = Settings.from_yaml(path) if path is not None else Settings()
    return _settings_cache


settings = get_settings()
