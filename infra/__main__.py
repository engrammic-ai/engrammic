"""Engrammic infrastructure entrypoint."""

from urllib.parse import quote

import pulumi

config = pulumi.Config()
benchmark_config = pulumi.Config("benchmark")

# Check if this is the benchmark stack (benchmark:environment=benchmark)
env = benchmark_config.get("environment") or config.get("environment") or "dev"

# Benchmark stack has its own simplified infrastructure
if env == "benchmark":
    from components.benchmark import BenchmarkEnvironment

    benchmark = BenchmarkEnvironment("benchmark")

    pulumi.export("gpu_ip", benchmark.gpu.internal_ip)
    pulumi.export("devbox_ip", benchmark.devbox.internal_ip)
    pulumi.export("tei_embeddings_url", pulumi.Output.concat("http://", benchmark.gpu.internal_ip, ":8080"))
    pulumi.export("tei_reranker_url", pulumi.Output.concat("http://", benchmark.gpu.internal_ip, ":8081"))
    pulumi.export("vllm_url", pulumi.Output.concat("http://", benchmark.gpu.internal_ip, ":8000"))
    pulumi.export("engrammic_url", pulumi.Output.concat("http://", benchmark.devbox.internal_ip, ":8000"))
    pulumi.export("dagster_url", pulumi.Output.concat("http://", benchmark.devbox.internal_ip, ":3002"))

else:
    # Standard infrastructure (beta, prod, dev)
    from components import (
        BeaconServiceRun,
        CloudSQLPostgres,
        ContextServiceRun,
        IAMStack,
        InternalDNS,
        MetabaseRun,
        MigrationJob,
        NetworkStack,
        SecretsStack,
        StatefulHost,
        StorageStack,
        TEIHost,
    )
    from pulumi_gcp import secretmanager

    use_cloudsql = config.get_bool("use_cloudsql") or False

    # Feature flags per environment (static flags only - dynamic ones added below)
    feature_flags = {
        "beta": {
            "ENABLE_EXPERIMENTAL_RECALL": "true",
            "ENABLE_DEBUG_ENDPOINTS": "true",
            "SECURITY__RATE_LIMIT__ENABLED": "true",
            "MODEL_TIER": "beta",
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

    # License signing key (shared across environments)
    license_private_key = secretmanager.get_secret_output(secret_id="license-private-key")

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

    # Internal DNS - stable hostnames for StatefulHost services
    internal_dns = InternalDNS(
        "engrammic-dns",
        vpc_id=network.vpc.id,
        stateful_host_ip=stateful_host.instance.network_interfaces[0].network_ip,
    )
    stateful_hostname = internal_dns.hostname

    # TEI GPU host for local embeddings (beta only - T4 GPUs in europe-west1)
    tei_host = None
    tei_url = None
    reranker_url = None
    use_tei = config.get_bool("use_tei") or False
    if use_tei:
        tei_host = TEIHost(
            "engrammic-tei",
            network=network.vpc,
            subnet=network.tei_subnet,
            service_account_email=iam.stateful_host.email,
            model_id="BAAI/bge-m3",
        )
        tei_url = tei_host.instance.network_interfaces[0].network_ip.apply(
            lambda ip: f"http://{ip}:8080"
        )
        reranker_url = tei_host.instance.network_interfaces[0].network_ip.apply(
            lambda ip: f"http://{ip}:8081"
        )

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
            "MEMGRAPH_HOST": stateful_hostname,
            "MEMGRAPH_URI": f"bolt://{stateful_hostname}:7687",
            "QDRANT_HOST": stateful_hostname,
            "QDRANT_URL": f"http://{stateful_hostname}:6333",
            "REDIS_HOST": stateful_hostname,
            "REDIS_URL": f"redis://{stateful_hostname}:6379",
            "POSTGRES_HOST": postgres_host,
            "POSTGRES_USER": "context",
            "POSTGRES_DATABASE": "engrammic",
            "VERTEX_PROJECT_ID": "engrammic",
            "VERTEX_LOCATION": "europe-north1",
            "EMBEDDING_PROVIDER": "tei" if use_tei else "vertex",
            "LLM_PROVIDER": "vertex_gemini",
            "DEFAULT_LLM_MODEL": "gemini-3.1-flash-lite",
            "AUTH_ENABLED": "false" if env == "dev" else "true",
            "CUSTODIAN__ENABLED": "true",
            "LOG_LEVEL": "INFO",
            "OAUTH__ISSUER": "https://api.engrammic.ai"
            if env == "prod"
            else f"https://{env}.engrammic.ai",
            # Telemetry beacon (URL set via config, secret from Pulumi secrets)
            "TELEMETRY__BEACON_SECRET": config.get_secret("beacon_secret") or "",
            "TELEMETRY__BEACON_URL": "https://tel.engrammic.ai/v1/beacon"
            if env in ("beta", "prod")
            else "",
            # Feature flags
            **feature_flags.get(env, {}),
            # TEI URL (dynamic, only when use_tei=true)
            **({"TEI_URL": tei_url, "RERANKER_URL": reranker_url} if tei_url else {}),
        },
        secrets={
            "POSTGRES_PASSWORD": secrets.secrets["postgres-password"].id,
            "MEMGRAPH_PASSWORD": secrets.secrets["memgraph-password"].id,
            "WORKOS_API_KEY": secrets.secrets["workos-api-key"].id,
            "WORKOS_CLIENT_ID": secrets.secrets["workos-client-id"].id,
            "WORKOS_COOKIE_PASSWORD": secrets.secrets["workos-cookie-password"].id,
            "LICENSE_PRIVATE_KEY": license_private_key.id,
            "GEMINI_API_KEY": secrets.secrets["gemini-api-key"].id,
        },
    )

    # Migration job and Beacon service (if Cloud SQL enabled - beta/prod only)
    migration_job = None
    beacon_service = None
    metabase_service = None
    if use_cloudsql:
        # SQLAlchemy format for migration job (uses asyncpg driver)
        database_url_sqlalchemy = pulumi.Output.all(
            postgres_host,
            config.require_secret("postgres_password"),
        ).apply(
            lambda args: (
                f"postgresql+asyncpg://context:{quote(args[1], safe='')}@{args[0]}:5432/engrammic"
            )
        )

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

        # Metabase for internal dashboards
        metabase_database_url = pulumi.Output.all(
            postgres_host,
            config.require_secret("postgres_password"),
        ).apply(lambda args: f"postgres://context:{quote(args[1], safe='')}@{args[0]}:5432/metabase")

        metabase_service = MetabaseRun(
            "engrammic-metabase",
            vpc_id=network.vpc.id,
            subnet_id=network.private_subnet.name,
            service_account_email=iam.context_service_run.email,
            database_url=metabase_database_url,
        )

    # Exports
    pulumi.export("vpc_id", network.vpc.id)
    pulumi.export("stateful_host_ip", stateful_host.instance.network_interfaces[0].network_ip)
    pulumi.export("stateful_hostname", stateful_hostname)
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

    if tei_host:
        pulumi.export("tei_host_ip", tei_host.instance.network_interfaces[0].network_ip)
        pulumi.export("tei_url", tei_url)

    if metabase_service:
        pulumi.export("metabase_url", metabase_service.service.uri)
