"""Application settings — single canonical source.

All settings live here. core/settings.py re-exports from here for
backwards compatibility with library code that predates this consolidation.

Settings precedence:
1. Environment variables (always override)
2. config/settings.yaml (runtime settings, hot-reloadable via reload_settings)
3. Default values in code
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from context_service.config.models import ModelsConfig

load_dotenv(override=False)


def _fetch_secret(secret_id: str, project: str = "engrammic") -> str | None:
    """Fetch secret from GCP Secret Manager. Returns None if unavailable."""
    try:
        from google.cloud import secretmanager

        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{project}/secrets/{secret_id}/versions/latest"
        response = client.access_secret_version(request={"name": name})
        return str(response.payload.data.decode("UTF-8"))
    except Exception:
        return None


class CustodianSettings(BaseModel):
    """Custodian phase settings: budgets, flags, and model identifiers."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    enabled: bool = Field(default=False, description="Master gate for the Custodian subsystem")

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

    flash_model: str = Field(default="google-vertex:gemini-3.1-flash-lite")
    pro_model: str = Field(default="google-vertex:gemini-3.1-pro")

    min_edge_confidence: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Minimum confidence for proposed edges; below this they are structurally rejected",
    )


class CustodianIdentityConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    enabled: bool = True
    model: str = "google-vertex:gemini-3.1-flash-lite"
    timeout_seconds: int = 30
    batch_size: int = 5
    batch_window_seconds: float = 2.0
    min_confidence_for_supersession: float = 0.7


class SynthesizerIdentityConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    enabled: bool = True
    model: str = "google-vertex:gemini-3.1-pro"
    timeout_seconds: int = 60
    threshold_pending_nodes: int = 50
    schedule_cron: str = "0 * * * *"
    proposal_confidence_threshold: float = 0.6
    max_facts_per_synthesis: int = 10
    min_facts_for_synthesis: int = 3
    belief_merge_similarity_threshold: float = Field(
        default=0.85,
        ge=0.0,
        le=1.0,
        description="Minimum cosine similarity between belief embeddings to consider merge",
    )
    belief_merge_max_pairs: int = Field(
        default=50,
        description="Maximum belief pairs to process per merge run",
    )


class EvidenceEnforcementConfig(BaseModel):
    """Settings for Knowledge layer evidence enforcement (D1)."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    enabled: bool = Field(default=True, description="Enable evidence validation")
    enforce: bool = Field(default=False, description="If false, log-only mode (no rejection)")


class TrustGateConfig(BaseModel):
    """Settings for the recall trust gate (A1).

    Withholds memory the system cannot stand behind from recall results.
    Superseded nodes are already dropped upstream by query(); this gate adds
    unresolved-contradiction and below-floor-confidence withholding.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    enabled: bool = Field(default=True, description="Enable the recall trust gate")
    confidence_floor: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Withhold results with confidence below this floor. "
        "Default 0.0 (off) to avoid hiding low-confidence-but-useful knowledge; "
        "calibrate per deployment.",
    )
    withhold_unresolved_conflicts: bool = Field(
        default=True,
        description="Withhold results whose conflict_status is 'unresolved'",
    )


class EpistemicFusionConfig(BaseModel):
    """Settings for post-rerank epistemic score fusion.

    Reranker scores previously overwrote confidence/conflict signal in
    recall ranking; fusion multiplies the final relevance score by an
    epistemic adjustment so evidence state is load-bearing at read time.
    Withholding (trust gate) is separate and unaffected.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    enabled: bool = Field(default=True, description="Enable epistemic score fusion")
    confidence_weight: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description=(
            "Weight of node confidence in the fused score for knowledge/wisdom "
            "layers: factor = (1 - w) + w * confidence"
        ),
    )
    conflict_penalty: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Score multiplier applied to unresolved-contradiction nodes",
    )


class BM25ChannelConfig(BaseModel):
    """BM25 keyword search channel configuration."""

    model_config = ConfigDict(frozen=True)

    enabled: bool = True
    top_k: int = 100


class TemporalChannelConfig(BaseModel):
    """Temporal date-aware retrieval channel configuration.

    Only Memory layer uses time-based recency decay. Knowledge/Wisdom persist
    until superseded (evidence-gated). Intelligence is session-scoped.
    """

    model_config = ConfigDict(frozen=True)

    enabled: bool = True
    memory_half_life_days: float = 7.0

    def half_life_for_layer(self, layer: str) -> float | None:
        """Return the half-life in days for a given cognitive layer.

        Returns None for non-Memory layers (no time-based decay).
        """
        if layer.lower() == "memory":
            return self.memory_half_life_days
        return None


class GraphChannelConfig(BaseModel):
    """PPR graph traversal channel configuration."""

    model_config = ConfigDict(frozen=True)

    enabled: bool = True
    damping: float = 0.85
    max_iterations: int = 50
    edge_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "SYNTHESIZED_FROM": 1.5,
            "SUPERSEDES": 1.5,
            "LINK": 1.0,
        }
    )


class CrossEncoderConfig(BaseModel):
    """Local cross-encoder reranker configuration."""

    model_config = ConfigDict(frozen=True)

    enabled: bool = True
    model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    top_k: int = 50


class RerankingSettings(BaseModel):
    """Settings for semantic reranking and query expansion."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    enabled: bool = Field(default=True, description="Enable cross-encoder reranking")
    expand_hard_queries: bool = Field(
        default=False,
        description="Enable LLM query expansion for hard queries (disabled by default due to genai SDK stability)",
    )
    expansion_cache_ttl_days: int = Field(
        default=7, description="TTL for cached query expansions in Redis"
    )
    reranker_timeout_seconds: float = Field(
        default=10.0, description="Timeout for reranker API calls"
    )
    expander_timeout_seconds: float = Field(
        default=5.0, description="Timeout for query expansion LLM calls"
    )
    skip_rerank_threshold: float = Field(
        default=0.85,
        ge=0.0,
        le=1.0,
        description="Skip reranking if top cosine score exceeds this threshold",
    )

    # Semantic rerank cache settings
    cache_enabled: bool = Field(
        default=True, description="Enable semantic caching of rerank results"
    )
    cache_similarity_threshold: float = Field(
        default=0.95,
        ge=0.8,
        le=1.0,
        description="Cosine similarity threshold for L2 cache hits",
    )
    cache_l1_ttl_seconds: int = Field(default=300, description="TTL for L1 (exact match) cache")
    cache_l1_maxsize: int = Field(default=1000, description="Max entries in L1 cache per process")

    # Score-adaptive truncation (SmartSearch-style)
    adaptive_threshold_enabled: bool = Field(
        default=True,
        description="Use score-adaptive truncation (tau = alpha * max_score)",
    )
    adaptive_alpha: float = Field(
        default=0.5,
        ge=0.3,
        le=0.9,
        description="Alpha for adaptive threshold (0.5-0.7 recommended)",
    )


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
    model: str = "google-vertex:gemini-3.1-pro"
    timeout_seconds: int = 5
    fail_open: bool = True


class IdentitiesConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    custodian: CustodianIdentityConfig = Field(default_factory=CustodianIdentityConfig)
    synthesizer: SynthesizerIdentityConfig = Field(default_factory=SynthesizerIdentityConfig)
    groundskeeper: GroundskeeperIdentityConfig = Field(default_factory=GroundskeeperIdentityConfig)
    validator: ValidatorIdentityConfig = Field(default_factory=ValidatorIdentityConfig)


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
    scalar_quantization_enabled: bool = False
    quantization_always_ram: bool = True
    recreate_on_dimension_mismatch: bool = False


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
    database: str = "engrammic"

    @model_validator(mode="before")
    @classmethod
    def _from_env(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Read from POSTGRES_* env vars for docker-compose compatibility."""
        import os

        env_map = {
            "POSTGRES_HOST": "host",
            "POSTGRES_PORT": "port",
            "POSTGRES_USER": "user",
            "POSTGRES_PASSWORD": "password",
            "POSTGRES_DATABASE": "database",
        }
        for env_key, field in env_map.items():
            if env_key in os.environ and field not in data:
                data[field] = os.environ[env_key]
        return data

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


class FusionConfig(BaseModel):
    """Cross-channel RRF fusion settings."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    rrf_k: int = Field(
        default=60,
        description="RRF smoothing constant (standard literature value)",
    )
    default_graph_depth: int = Field(
        default=2,
        description="Default BFS depth for graph channel",
    )


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
    hybrid_enabled: bool = True
    fresh_floor: float = 0.25
    staleness_weight: float = 0.15
    tiebreak: TiebreakConfig = Field(default_factory=TiebreakConfig)
    entity: EntityRetrievalConfig = Field(default_factory=EntityRetrievalConfig)
    cluster: ClusterRetrievalConfig = Field(default_factory=ClusterRetrievalConfig)
    supersession: SupersessionConfig = Field(default_factory=SupersessionConfig)
    fusion: FusionConfig = Field(default_factory=FusionConfig)
    temporal_channel: TemporalChannelConfig = Field(default_factory=TemporalChannelConfig)


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
    credentials_path: str = ""
    model: str = ""
    dimensions: int = 0


class SpladeConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    model: str = "prithivida/Splade_PP_en_v1"  # verified 2026-05-19


class ModelRateLimitConfig(BaseModel):
    """Rate limiting and retry configuration for AI model calls."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    max_retries: int = Field(
        default=3,
        description="Maximum number of retries on rate limit or transient errors.",
    )
    retry_base_delay_seconds: float = Field(
        default=1.0,
        description="Base delay for exponential backoff between retries.",
    )
    retry_max_delay_seconds: float = Field(
        default=60.0,
        description="Maximum delay between retries.",
    )
    max_concurrent_requests: int = Field(
        default=10,
        description="Maximum concurrent API requests (semaphore limit).",
    )
    timeout_seconds: float = Field(
        default=60.0,
        description="Timeout for individual API calls.",
    )
    requests_per_minute: int = Field(
        default=250,
        description="Max requests per minute (Vertex AI default: 250/region).",
    )


class EmbeddingConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    provider: str = "jina"
    jina: JinaConfig = Field(default_factory=JinaConfig)
    vertex: VertexConfig = Field(default_factory=VertexConfig)
    splade: SpladeConfig = Field(default_factory=SpladeConfig)
    rate_limit: ModelRateLimitConfig = Field(default_factory=ModelRateLimitConfig)


class ProviderConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    api_url: str = ""


class LLMConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    provider: str = ""
    model: str = ""
    api_url: str | None = None
    api_key: SecretStr | None = None
    default_timeout_seconds: float = Field(
        default=60.0,
        description="Default timeout for LLM API calls when caller passes None.",
    )
    rate_limit: ModelRateLimitConfig = Field(default_factory=ModelRateLimitConfig)
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


class OAuthConfig(BaseModel):
    """OAuth 2.0 configuration for MCP client authentication.

    Redirect URI validation follows RFC 8252 (OAuth for Native Apps):
    - Loopback (127.0.0.1, localhost) with any port: allowed for CLI/desktop
    - Custom URL schemes (cursor://, claude://, etc.): allowed for native apps
    - HTTPS: allowed for web clients
    - HTTP to non-loopback: rejected

    PKCE (S256) is required for all clients, providing code injection protection.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    issuer: str = "https://api.engrammic.ai"
    access_token_ttl_seconds: int = 2592000  # 30 days - harness refresh is unreliable
    refresh_token_ttl_days: int = 90
    authorization_code_ttl_seconds: int = 600  # 10 minutes


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
    enable_test_endpoints: bool = False  # Admin endpoints for testing (disabled in prod)


class ConsolidationConfig(BaseModel):
    """Configuration for conflict consolidation resolution."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    use_llm_resolver: bool = Field(
        default=False,
        description="Use LLM resolver instead of deterministic scorer for conflict resolution",
    )


def _generate_install_id() -> str:
    """Generate a stable install ID based on machine identity."""
    import hashlib
    import platform
    import uuid

    try:
        node = uuid.getnode()
        hostname = platform.node()
        raw = f"{node}:{hostname}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]
    except Exception:
        return str(uuid.uuid4())[:16]


class TelemetryConfig(BaseModel):
    """Self-hosted telemetry configuration."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    enabled: bool = Field(
        default=True,
        description="Tier 1: anonymous aggregate telemetry (default on)",
    )
    install_id: str = Field(
        default_factory=_generate_install_id,
        description="Unique identifier for this installation (auto-generated if not set)",
    )
    silos: list[str] = Field(
        default_factory=list,
        description="Tier 2: silo IDs to include in telemetry. Empty = tier 1 only. ['*'] = all silos.",
    )
    beacon_url: str = Field(
        default="https://tel.engrammic.ai/v1/beacon",
        description="Endpoint for telemetry heartbeats",
    )
    beacon_secret: str = Field(
        default="",
        description="Secret for authenticating to beacon service (X-Beacon-Secret header)",
    )
    beacon_interval_hours: int = Field(
        default=1,
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


class ResultCacheConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    enabled: bool = Field(default=True, description="Enable in-process tiered result cache")
    memory_ttl: int = Field(default=300, description="Memory layer TTL in seconds (5 min)")
    knowledge_ttl: int = Field(default=3600, description="Knowledge layer TTL in seconds (1 hour)")
    wisdom_ttl: int = Field(default=1800, description="Wisdom layer TTL in seconds (30 min)")
    maxsize: int = Field(default=10000, description="Max entries per layer cache")


class SimilarityCacheConfig(BaseModel):
    """Configuration for Phase 4 similarity embedding cache."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    enabled: bool = Field(
        default=False,
        description="Enable similarity-based embedding reuse on exact-match miss.",
    )
    threshold: float = Field(
        default=0.95,
        ge=0.0,
        le=1.0,
        description="Minimum cosine similarity to reuse a cached embedding.",
    )
    max_entries: int = Field(
        default=500,
        ge=10,
        le=5000,
        description="Maximum number of recent query embeddings kept in the similarity index.",
    )
    index_ttl: int = Field(
        default=86400,
        ge=60,
        description="TTL in seconds applied to the similarity index key on each write.",
    )


class ClusteringConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    auto_trigger_enabled: bool = False
    post_ingest_threshold: int = 50


class ConsensusConfig(BaseModel):
    """Configuration for TX6 CONSENSUS and TX7 TRACE handlers."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    min_chains: int = Field(
        default=3,
        ge=1,
        description="Minimum number of chains (K) required for consensus promotion.",
    )
    min_agents: int = Field(
        default=2,
        ge=1,
        description="Minimum number of distinct agents (J) required for consensus.",
    )
    conclusion_threshold: float = Field(
        default=0.85,
        ge=0.0,
        le=1.0,
        description="ANN cosine similarity threshold for matching conclusions (Layer 1).",
    )
    reasoning_threshold: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="DTW similarity threshold for compatible reasoning paths (Layer 2).",
    )
    trace_on_commit: bool = Field(
        default=True,
        description="When true, TX7 TRACE emits CHECK_CONSENSUS for each traced chain.",
    )


class ExtractionConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    mode: str = "eager"
    batch_concurrency: int = 8

    # TX1 EXTRACT settings
    enabled: bool = True
    threshold: int = 200  # Minimum content length to trigger extraction
    max_claims: int = 10  # Cap on claims extracted per memory
    model: str = "gemini-1.5-flash"  # LLM model for extraction
    timeout_ms: int = 25000  # Extraction timeout
    reextract_before_version: str | None = None  # Re-extract nodes with version < this


class EndpointLimits(BaseModel):
    """Rate limits for a single endpoint category."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    requests_per_minute: int = 60
    requests_per_hour: int = 600


class TierLimits(BaseModel):
    """Rate limits for all endpoint categories within a tier."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    mcp_write: EndpointLimits = Field(default_factory=EndpointLimits)
    mcp_read: EndpointLimits = Field(default_factory=EndpointLimits)
    admin: EndpointLimits = Field(default_factory=EndpointLimits)
    rest: EndpointLimits = Field(default_factory=EndpointLimits)


def _default_tiers() -> dict[str, TierLimits]:
    """Default tier configurations matching pricing model."""
    return {
        "free": TierLimits(
            mcp_write=EndpointLimits(requests_per_minute=20, requests_per_hour=200),
            mcp_read=EndpointLimits(requests_per_minute=60, requests_per_hour=600),
            admin=EndpointLimits(requests_per_minute=10, requests_per_hour=60),
            rest=EndpointLimits(requests_per_minute=30, requests_per_hour=300),
        ),
        "starter": TierLimits(
            mcp_write=EndpointLimits(requests_per_minute=60, requests_per_hour=600),
            mcp_read=EndpointLimits(requests_per_minute=200, requests_per_hour=2000),
            admin=EndpointLimits(requests_per_minute=30, requests_per_hour=300),
            rest=EndpointLimits(requests_per_minute=100, requests_per_hour=1000),
        ),
        "pro": TierLimits(
            mcp_write=EndpointLimits(requests_per_minute=200, requests_per_hour=2000),
            mcp_read=EndpointLimits(requests_per_minute=600, requests_per_hour=6000),
            admin=EndpointLimits(requests_per_minute=60, requests_per_hour=600),
            rest=EndpointLimits(requests_per_minute=300, requests_per_hour=3000),
        ),
        "enterprise": TierLimits(
            mcp_write=EndpointLimits(requests_per_minute=1000, requests_per_hour=10000),
            mcp_read=EndpointLimits(requests_per_minute=3000, requests_per_hour=30000),
            admin=EndpointLimits(requests_per_minute=200, requests_per_hour=2000),
            rest=EndpointLimits(requests_per_minute=1000, requests_per_hour=10000),
        ),
    }


class RateLimitConfig(BaseModel):
    """Tiered rate limiting configuration."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    enabled: bool = False
    tiers: dict[str, TierLimits] = Field(default_factory=_default_tiers)
    default_tier: str = "free"
    tier_cache_ttl_seconds: int = 300

    def get_limits(self, tier: str) -> TierLimits:
        """Get limits for a tier, falling back to default if unknown."""
        return self.tiers.get(tier, self.tiers[self.default_tier])


class SecurityConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    rate_limit: RateLimitConfig = Field(default_factory=RateLimitConfig)
    max_request_body_mb: int = 10
    admin_api_key: SecretStr | None = Field(
        default=None,
        description="Bearer token required for /admin/* endpoints. None disables the check (dev only).",
    )


class StripeConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    secret_key: SecretStr | None = None
    webhook_secret: SecretStr | None = None
    webhook_secret_rollover: SecretStr | None = None
    price_id_team: str = ""
    meter_event_name: str = "context_service_retrieval"
    mock: bool = False
    default_tier: str = "team"


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


class ReasoningChainMatchingConfig(BaseModel):
    """Reasoning chain applicability matching configuration."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    query_threshold_cold: float = Field(default=0.95, ge=0.0, le=1.0)
    query_threshold_warm: float = Field(default=0.88, ge=0.0, le=1.0)
    step_threshold: float = Field(default=0.85, ge=0.0, le=1.0)
    top_k_candidates: int = Field(default=5, ge=1)
    dtw_latency_warn_ms: int = Field(default=50, ge=1)
    dtw_latency_abort_ms: int = Field(default=100, ge=1)


class ChainFeedbackConfig(BaseModel):
    """Chain feedback evaluation configuration."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    evaluation_delay_minutes: int = Field(default=5, ge=1)
    min_subsequent_steps: int = Field(default=3, ge=1)
    max_wait_minutes: int = Field(default=30, ge=1)
    usefulness_threshold: float = Field(default=0.7, ge=0.0, le=1.0)


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
    from context_service.config.paths import resolve_config_file

    config_path = resolve_config_file("identities.yaml", Path(__file__).parent / "identities.yaml")
    if not config_path.exists():
        return IdentitiesConfig()
    try:
        with open(config_path) as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise ValueError(f"Failed to parse identities config: {config_path}") from exc
    if not isinstance(data, dict):
        return IdentitiesConfig()
    return IdentitiesConfig(**data.get("identities", {}))


def _load_models_config() -> ModelsConfig:
    from context_service.config.models import load_models_config

    return load_models_config()


class UsageRetentionConfig(BaseModel):
    """Configuration for ToolUsage row retention."""

    retention_enabled: bool = Field(
        default=False,
        description="Enable deletion of old ToolUsage rows. Disabled by default.",
    )
    retention_days: int = Field(
        default=90,
        ge=1,
        description="Rows older than this many days are deleted when retention is enabled.",
    )


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
    oauth: OAuthConfig = Field(default_factory=OAuthConfig)
    prompts: PromptsConfig = Field(default_factory=PromptsConfig)
    features: FeaturesConfig = Field(default_factory=FeaturesConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    result_cache: ResultCacheConfig = Field(default_factory=ResultCacheConfig)
    similarity_cache: SimilarityCacheConfig = Field(default_factory=SimilarityCacheConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    clustering: ClusteringConfig = Field(default_factory=ClusteringConfig)
    extraction: ExtractionConfig = Field(default_factory=ExtractionConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    stripe: StripeConfig = Field(default_factory=StripeConfig)
    custodian: CustodianSettings = Field(default_factory=CustodianSettings)
    auto_reflect: AutoReflectConfig = Field(default_factory=AutoReflectConfig)
    consolidation: ConsolidationConfig = Field(default_factory=ConsolidationConfig)
    causal: CausalConfig = Field(default_factory=CausalConfig)
    pattern: PatternConfig = Field(default_factory=PatternConfig)
    weak_links: WeakLinksSettings = Field(default_factory=WeakLinksSettings)
    consensus: ConsensusConfig = Field(default_factory=ConsensusConfig)
    telemetry: TelemetryConfig = Field(default_factory=TelemetryConfig)
    identities: IdentitiesConfig = Field(default_factory=_load_identities_config)
    models: ModelsConfig = Field(default_factory=_load_models_config)
    reasoning_chain_matching: ReasoningChainMatchingConfig = Field(
        default_factory=ReasoningChainMatchingConfig
    )
    chain_feedback: ChainFeedbackConfig = Field(default_factory=ChainFeedbackConfig)
    reranking: RerankingSettings = Field(default_factory=RerankingSettings)
    evidence_enforcement: EvidenceEnforcementConfig = Field(
        default_factory=EvidenceEnforcementConfig
    )
    trust_gate: TrustGateConfig = Field(default_factory=TrustGateConfig)
    epistemic_fusion: EpistemicFusionConfig = Field(default_factory=EpistemicFusionConfig)
    bm25_channel: BM25ChannelConfig = Field(default_factory=BM25ChannelConfig)
    temporal_channel: TemporalChannelConfig = Field(default_factory=TemporalChannelConfig)
    graph_channel: GraphChannelConfig = Field(default_factory=GraphChannelConfig)
    cross_encoder: CrossEncoderConfig = Field(default_factory=CrossEncoderConfig)
    usage: UsageRetentionConfig = Field(default_factory=UsageRetentionConfig)

    # =========================================================================
    # Application Meta
    # =========================================================================

    app_name: str = Field(default="ContextService")
    version: str = Field(default="1.3.1")
    debug: bool = Field(default=False)
    environment: str = Field(default="development")

    @property
    def is_development(self) -> bool:
        return self.environment == "development"

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
    # License Settings (Self-Hosted)
    # =========================================================================

    license_key: str | None = Field(
        default=None,
        validation_alias="ENGRAMMIC_LICENSE_KEY",
        description="License key for self-hosted deployments",
    )

    # MCP settings
    default_icp_preset: str = Field(default="coding")

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
    qdrant_scalar_quantization_enabled: bool = Field(default=False)
    qdrant_quantization_always_ram: bool = Field(default=True)
    qdrant_recreate_on_dimension_mismatch: bool = Field(default=False)

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
    # Embedding Settings (dimensions moved to models.yaml, provider via tier)
    # =========================================================================

    embedding_dimensions: int = Field(default=2048)

    hybrid_search_enabled: bool = Field(default=True)

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
    vertex_credentials_path: str = Field(default="")
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
    default_llm_model: str = Field(default="gemini-3.1-flash-lite")

    # Per-provider API keys (used by llm/ providers)
    anthropic_api_key: SecretStr | None = Field(default=None)
    anthropic_api_version: str = Field(default="2023-06-01")
    openai_api_key: SecretStr | None = Field(default=None)
    gemini_api_key: SecretStr | None = Field(default=None)

    # Self-hosted LLM (Ollama, vLLM)
    # Any of OLLAMA_URL, OLLAMA_BASE_URL, OLLAMA_API_BASE work (unified)
    @property
    def ollama_url(self) -> str:
        """Canonical Ollama URL. Reads from multiple env var names for compatibility."""
        return (
            os.environ.get("OLLAMA_URL")
            or os.environ.get("OLLAMA_BASE_URL")
            or os.environ.get("OLLAMA_API_BASE")
            or "http://localhost:11434"
        )

    @property
    def ollama_base_url(self) -> str:
        """Alias for ollama_url (litellm LLM convention)."""
        return self.ollama_url

    @property
    def ollama_api_base(self) -> str:
        """Alias for ollama_url (litellm embeddings convention)."""
        return self.ollama_url

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
    def _fetch_secrets_from_gcp(self) -> Settings:
        """Populate missing secrets from GCP Secret Manager when auth is enabled."""
        if not self.auth_enabled:
            return self

        # Map of field -> (secret_id, is_secret_str)
        secret_mapping: dict[str, tuple[str, bool]] = {
            "workos_api_key": ("engrammic-beta-workos-api-key", True),
            "workos_client_id": ("engrammic-beta-workos-client-id", False),
            "workos_cookie_password": ("engrammic-beta-workos-cookie-password", True),
            "postgres_password": ("engrammic-beta-postgres-password", True),
        }

        for field_name, (secret_id, is_secret) in secret_mapping.items():
            current_value = getattr(self, field_name)
            # Skip if already set (non-None, and for SecretStr not empty)
            if current_value is not None:
                if is_secret:
                    if current_value.get_secret_value():
                        continue
                else:
                    continue

            fetched = _fetch_secret(secret_id)
            if fetched:
                if is_secret:
                    object.__setattr__(self, field_name, SecretStr(fetched))
                else:
                    object.__setattr__(self, field_name, fetched)

        return self

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
    tei_url: str | None = Field(default=None, description="TEI sidecar URL for local embeddings")
    reranker_url: str | None = Field(
        default=None, description="TEI reranker URL (overrides models.yaml url)"
    )
    tei_reranker_url: str | None = Field(
        default=None, description="Alias for reranker_url (backwards compat)"
    )

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
    postgres_database: str = Field(default="engrammic")

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
    retention_supersession_chain_max_length: int = Field(
        default=20,
        ge=3,
        description="Max nodes in a supersession chain before pruning.",
    )

    # Forget Policy Defaults
    forget_enabled: bool = Field(
        default=True,
        description="Whether forget is enabled by default.",
    )
    forget_cancel_window_hours: int = Field(
        default=1,
        ge=1,
        description="Hours within which a forget can be cancelled.",
    )
    forget_rate_limit_per_hour: int = Field(
        default=100,
        ge=1,
        description="Max forget operations per hour per silo.",
    )

    # =========================================================================
    # Summarization Settings
    # =========================================================================

    summarization_provider: str = Field(default="vertex")
    summarization_model: str = Field(default="gemini-3.1-flash-lite")
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
    proposal_cooldown_hours: int = Field(
        default=24,
        ge=1,
        description="Don't re-propose rejected beliefs within this window",
    )
    max_proposals_per_silo: int = Field(
        default=10,
        ge=1,
        description="Cap pending ProposedBeliefs per silo to avoid noise",
    )

    # =========================================================================
    # Contradiction Detection (inline flagging)
    # =========================================================================

    contradiction_candidate_threshold: float = Field(
        default=0.85,
        ge=0.0,
        le=1.0,
        description="Cosine similarity threshold for flagging contradiction candidates",
    )
    contradiction_candidate_ttl_hours: int = Field(
        default=1,
        ge=1,
        description="Hours before unflagged candidates expire (validator picks them up)",
    )
    contradiction_flagging_enabled: bool = Field(
        default=True,
        description="Enable inline contradiction candidate flagging during writes",
    )
    affinity_computation_enabled: bool = Field(
        default=True,
        description="Enable inline affinity edge computation after Knowledge node writes",
    )

    # =========================================================================
    # Wisdom/Intelligence Activation
    # =========================================================================

    recall_hints_enabled: bool = Field(
        default=False,
        description="Enable recall hints for wisdom/intelligence layer suggestions",
    )

    # =========================================================================
    # tick() engagement
    # =========================================================================

    storage_gap_threshold: int = Field(
        default=10,
        description="Number of turns without storage before showing storage_gap nudge",
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
    # Engagement Escalation Settings
    # =========================================================================

    engagement_escalation_threshold: int = Field(
        default=3,
        ge=1,
        le=100,
        description="Number of touches before a soft checkpoint escalates to hard. Wired into the touch counter and engagement modules. Values above 100 would effectively disable escalation.",
    )
    engagement_decay_window_ms: int = Field(
        default=1_800_000,
        ge=1,
        le=86_400_000,
        description="Decay window in milliseconds (30 min) for engagement touch counting. Wired into the touch counter and engagement modules. Max 24 hours (86400000 ms) to prevent unbounded Redis growth.",
    )
    engagement_hard_enabled: bool = Field(
        default=True,
        description="Kill switch for hard checkpoint mode. Set false to disable escalation.",
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
