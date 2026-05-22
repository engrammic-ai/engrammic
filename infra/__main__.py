"""Engrammic infrastructure entrypoint."""

from urllib.parse import quote

import pulumi
from components import (
    BeaconServiceRun,
    CloudSQLPostgres,
    ContextServiceRun,
    IAMStack,
    MigrationJob,
    NetworkStack,
    SecretsStack,
    StatefulHost,
    StorageStack,
)

config = pulumi.Config()
use_cloudsql = config.get_bool("use_cloudsql") or False

env = config.require("environment")

# Feature flags per environment
feature_flags = {
    "beta": {
        "ENABLE_EXPERIMENTAL_RECALL": "true",
        "ENABLE_DEBUG_ENDPOINTS": "true",
        "SECURITY__RATE_LIMIT__ENABLED": "true",
    },
    "prod": {
        "ENABLE_EXPERIMENTAL_RECALL": "false",
        "ENABLE_DEBUG_ENDPOINTS": "false",
        "SECURITY__RATE_LIMIT__ENABLED": "true",
    },
    "dev": {
        "ENABLE_EXPERIMENTAL_RECALL": "true",
        "ENABLE_DEBUG_ENDPOINTS": "true",
        "SECURITY__RATE_LIMIT__ENABLED": "false",
    },
}

# IAM first - service accounts needed by other resources
iam = IAMStack("engrammic-iam")

# Network - VPC, subnets, NAT
network = NetworkStack("engrammic-network")

# Storage - backup buckets (IAM binding needs stateful host SA)
storage = StorageStack("engrammic-storage", stateful_host_email=iam.stateful_host.email)

# Secrets - Secret Manager resources
secrets = SecretsStack("engrammic-secrets")

# Cloud SQL (if enabled) - define postgres_host early for StatefulHost
cloudsql = None
if use_cloudsql:
    cloudsql = CloudSQLPostgres(
        "engrammic-cloudsql",
        network_id=network.vpc.id,
        private_connection=network.private_connection,
    )
    postgres_host = cloudsql.instance.private_ip_address
else:
    postgres_host = None  # Will be set after StatefulHost

# Stateful host - GCE instance for Memgraph, Qdrant, Redis (+ Postgres if not using Cloud SQL)
stateful_host = StatefulHost(
    "engrammic-stateful",
    network=network.vpc,
    subnet=network.private_subnet,
    service_account_email=iam.stateful_host.email,
    postgres_host=postgres_host,
)

# Set postgres_host from StatefulHost if not using Cloud SQL
if not use_cloudsql:
    postgres_host = stateful_host.instance.network_interfaces[0].network_ip

# Cloud Run API deployment
context_service = ContextServiceRun(
    "engrammic-context-service",
    vpc_id=network.vpc.id,
    connector_subnet_id=network.private_subnet.name,
    service_account_email=iam.context_service_run.email,
    image="europe-north1-docker.pkg.dev/engrammic/engrammic/engrammic-api:latest",
    env_vars={
        "ENVIRONMENT": env,
        "HOST": "0.0.0.0",
        "MEMGRAPH_HOST": stateful_host.instance.network_interfaces[0].network_ip,
        "MEMGRAPH_URI": stateful_host.instance.network_interfaces[0].network_ip.apply(
            lambda ip: f"bolt://{ip}:7687"
        ),
        "QDRANT_HOST": stateful_host.instance.network_interfaces[0].network_ip,
        "QDRANT_URL": stateful_host.instance.network_interfaces[0].network_ip.apply(
            lambda ip: f"http://{ip}:6333"
        ),
        "REDIS_HOST": stateful_host.instance.network_interfaces[0].network_ip,
        "REDIS_URL": stateful_host.instance.network_interfaces[0].network_ip.apply(
            lambda ip: f"redis://{ip}:6379"
        ),
        "POSTGRES_HOST": postgres_host,
        "POSTGRES_USER": "context",
        "POSTGRES_DATABASE": "engrammic",
        "VERTEX_PROJECT_ID": "engrammic",
        "VERTEX_LOCATION": "europe-north1",
        "EMBEDDING_PROVIDER": "vertex",
        "LLM_PROVIDER": "vertex_gemini",
        "DEFAULT_LLM_MODEL": "gemini-2.5-flash",
        "AUTH_ENABLED": "true",
        "CUSTODIAN__ENABLED": "true",
        "LOG_LEVEL": "INFO",
        "OAUTH__ISSUER": "https://api.engrammic.ai" if env == "prod" else f"https://{env}.engrammic.ai",
        # Observability
        "OTEL_ENABLED": "true",
        # Feature flags
        **feature_flags.get(env, {}),
    },
    secrets={
        "POSTGRES_PASSWORD": secrets.secrets["postgres-password"].id,
        "MEMGRAPH_PASSWORD": secrets.secrets["memgraph-password"].id,
        "WORKOS_API_KEY": secrets.secrets["workos-api-key"].id,
        "WORKOS_CLIENT_ID": secrets.secrets["workos-client-id"].id,
        "WORKOS_COOKIE_PASSWORD": secrets.secrets["workos-cookie-password"].id,
    },
)

# Migration job and Beacon service (if Cloud SQL enabled - beta/prod only)
migration_job = None
beacon_service = None
if use_cloudsql:
    # SQLAlchemy format for migration job (uses asyncpg driver)
    database_url_sqlalchemy = pulumi.Output.all(
        postgres_host,
        config.require_secret("postgres_password"),
    ).apply(lambda args: f"postgresql+asyncpg://context:{quote(args[1], safe='')}@{args[0]}:5432/engrammic")

    # Plain asyncpg format for beacon (uses asyncpg directly)
    database_url_asyncpg = pulumi.Output.all(
        postgres_host,
        config.require_secret("postgres_password"),
    ).apply(lambda args: f"postgresql://context:{quote(args[1], safe='')}@{args[0]}:5432/engrammic")

    migration_job = MigrationJob(
        "engrammic-migrate",
        vpc_id=network.vpc.id,
        subnet_id=network.private_subnet.name,
        service_account_email=iam.context_service_run.email,
        image="europe-north1-docker.pkg.dev/engrammic/engrammic/engrammic-api:latest",
        database_url=database_url_sqlalchemy,
    )

    beacon_service = BeaconServiceRun(
        "engrammic-beacon",
        vpc_id=network.vpc.id,
        subnet_id=network.private_subnet.name,
        service_account_email=iam.context_service_run.email,
        image="europe-north1-docker.pkg.dev/engrammic/engrammic/engrammic-beacon:latest",
        database_url=database_url_asyncpg,
    )

# Exports
pulumi.export("vpc_id", network.vpc.id)
pulumi.export("stateful_host_ip", stateful_host.instance.network_interfaces[0].network_ip)
pulumi.export("backup_bucket_name", storage.backup_bucket.name)
pulumi.export(
    "service_account_emails",
    {
        "compute": iam.stateful_host.email,
        "cloudrun": iam.context_service_run.email,
    },
)
pulumi.export("api_url", context_service.service.uri)

if cloudsql:
    pulumi.export("cloudsql_connection_name", cloudsql.instance.connection_name)
    pulumi.export("cloudsql_private_ip", cloudsql.instance.private_ip_address)

if migration_job:
    pulumi.export("migration_job_name", migration_job.job.name)

if beacon_service:
    pulumi.export("beacon_url", beacon_service.service.uri)
