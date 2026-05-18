"""Engrammic infrastructure entrypoint."""

import pulumi
from components import (
    BeaconServiceRun,
    CloudSQLPostgres,
    ContextServiceRun,
    IAMStack,
    NetworkStack,
    SecretsStack,
    StatefulHost,
    StorageStack,
)

config = pulumi.Config()
use_cloudsql = config.get_bool("use_cloudsql") or False

# IAM first - service accounts needed by other resources
iam = IAMStack("engrammic-iam")

# Network - VPC, subnets, NAT
network = NetworkStack("engrammic-network")

# Storage - backup buckets (IAM binding needs stateful host SA)
storage = StorageStack("engrammic-storage", stateful_host_email=iam.stateful_host.email)

# Secrets - Secret Manager resources
secrets = SecretsStack("engrammic-secrets")

# Stateful host - GCE instance for Memgraph, Qdrant, Redis (+ Postgres if not using Cloud SQL)
stateful_host = StatefulHost(
    "engrammic-stateful",
    network=network.vpc,
    subnet=network.private_subnet,
    service_account_email=iam.stateful_host.email,
)

# Cloud SQL (if enabled)
cloudsql = None
postgres_host = stateful_host.instance.network_interfaces[0].network_ip
if use_cloudsql:
    cloudsql = CloudSQLPostgres(
        "engrammic-cloudsql",
        network_id=network.vpc.id,
    )
    postgres_host = cloudsql.instance.private_ip_address

# Cloud Run API deployment
context_service = ContextServiceRun(
    "engrammic-context-service",
    vpc_id=network.vpc.id,
    connector_subnet_id=network.vpc_connector.name,
    service_account_email=iam.context_service_run.email,
    image="europe-north1-docker.pkg.dev/engrammic/engrammic/engrammic-api:latest",
    env_vars={
        "ENVIRONMENT": config.require("environment"),
        "MEMGRAPH_HOST": stateful_host.instance.network_interfaces[0].network_ip,
        "QDRANT_HOST": stateful_host.instance.network_interfaces[0].network_ip,
        "REDIS_HOST": stateful_host.instance.network_interfaces[0].network_ip,
        "POSTGRES_HOST": postgres_host,
        "POSTGRES_USER": "context",
        "POSTGRES_DATABASE": "engrammic",
        "VERTEX_PROJECT_ID": "engrammic",
        "VERTEX_LOCATION": "europe-north1",
    },
    secrets={
        "POSTGRES_PASSWORD": secrets.secrets["postgres-password"].id,
        "MEMGRAPH_PASSWORD": secrets.secrets["memgraph-password"].id,
        "WORKOS_API_KEY": secrets.secrets["workos-api-key"].id,
        "ANTHROPIC_API_KEY": secrets.secrets["anthropic-api-key"].id,
        "OPENAI_API_KEY": secrets.secrets["openai-api-key"].id,
        "GOOGLE_API_KEY": secrets.secrets["google-api-key"].id,
    },
)

# Beacon service (if Cloud SQL enabled - beta/prod only)
beacon_service = None
if use_cloudsql:
    database_url = pulumi.Output.all(
        postgres_host,
        config.require_secret("postgres_password"),
    ).apply(lambda args: f"postgresql://context:{args[1]}@{args[0]}:5432/engrammic")

    beacon_service = BeaconServiceRun(
        "engrammic-beacon",
        vpc_connector_id=context_service.connector.id,
        service_account_email=iam.context_service_run.email,
        image="europe-north1-docker.pkg.dev/engrammic/engrammic/engrammic-beacon:latest",
        database_url=database_url,
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

if beacon_service:
    pulumi.export("beacon_url", beacon_service.service.uri)
