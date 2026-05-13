"""Engrammic infrastructure entrypoint."""

import pulumi

from components import (
    IAMStack,
    NetworkStack,
    StorageStack,
    SecretsStack,
    StatefulHost,
    ContextServiceRun,
)

# IAM first - service accounts needed by other resources
iam = IAMStack("engrammic-iam")

# Network - VPC, subnets, NAT
network = NetworkStack("engrammic-network")

# Storage - backup buckets
storage = StorageStack("engrammic-storage")

# Secrets - Secret Manager resources
secrets = SecretsStack("engrammic-secrets")

# Stateful host - GCE instance for Memgraph, Qdrant, Redis, Postgres, Dagster
stateful_host = StatefulHost(
    "engrammic-stateful",
    network=network.vpc,
    subnet=network.private_subnet,
    service_account_email=iam.stateful_host.email,
)

# Cloud Run deployment - commented out until container image is built
# Placeholder image: "gcr.io/cloudrun/hello"
#
# context_service = ContextServiceRun(
#     "engrammic-context-service",
#     vpc_id=network.vpc.id,
#     connector_subnet_id=network.private_subnet.name,
#     service_account_email=iam.context_service_run.email,
#     image="gcr.io/cloudrun/hello",
#     env_vars={
#         "ENVIRONMENT": pulumi.Config().require("environment"),
#         "MEMGRAPH_HOST": stateful_host.instance.network_interfaces[0].network_ip,
#         "QDRANT_HOST": stateful_host.instance.network_interfaces[0].network_ip,
#         "REDIS_HOST": stateful_host.instance.network_interfaces[0].network_ip,
#         "POSTGRES_HOST": stateful_host.instance.network_interfaces[0].network_ip,
#     },
#     secrets={
#         "POSTGRES_PASSWORD": secrets.secrets["postgres-password"].id,
#         "MEMGRAPH_PASSWORD": secrets.secrets["memgraph-password"].id,
#         "WORKOS_API_KEY": secrets.secrets["workos-api-key"].id,
#         "ANTHROPIC_API_KEY": secrets.secrets["anthropic-api-key"].id,
#     },
# )

# Exports
pulumi.export("vpc_id", network.vpc.id)
pulumi.export("stateful_host_ip", stateful_host.instance.network_interfaces[0].network_ip)
pulumi.export("backup_bucket_name", storage.backup_bucket.name)
pulumi.export("service_account_emails", {
    "compute": iam.stateful_host.email,
    "cloudrun": iam.context_service_run.email,
})
