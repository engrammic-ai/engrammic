import dagger
from dagger import dag, function, object_type


@object_type
class ContextService:
    @function
    async def lint(self, source: dagger.Directory) -> str:
        """Run ruff linter on src and tests."""
        return await (
            dag.container()
            .from_("ghcr.io/astral-sh/uv:python3.12-alpine")
            .with_directory("/app", source)
            .with_workdir("/app")
            .with_exec(["uv", "sync", "--frozen"])
            .with_exec(["uv", "run", "ruff", "check", "src", "tests"])
            .stdout()
        )

    @function
    async def typecheck(self, source: dagger.Directory) -> str:
        """Run mypy type checker on src."""
        return await (
            dag.container()
            .from_("ghcr.io/astral-sh/uv:python3.12-alpine")
            .with_directory("/app", source)
            .with_workdir("/app")
            .with_exec(["uv", "sync", "--frozen"])
            .with_exec(["uv", "run", "mypy", "src"])
            .stdout()
        )

    @function
    async def test(self, source: dagger.Directory) -> str:
        """Run unit tests (excludes integration tests)."""
        return await (
            dag.container()
            .from_("ghcr.io/astral-sh/uv:python3.12-alpine")
            .with_directory("/app", source)
            .with_workdir("/app")
            .with_exec(["uv", "sync", "--frozen", "--all-extras"])
            .with_exec(["uv", "run", "pytest", "-m", "not integration", "-v"])
            .stdout()
        )

    @function
    async def test_integration(self, source: dagger.Directory) -> str:
        """Run integration tests with service containers."""
        memgraph = (
            dag.container()
            .from_("memgraph/memgraph:2.14")
            .with_exposed_port(7687)
            .as_service()
        )
        qdrant = (
            dag.container()
            .from_("qdrant/qdrant:v1.7.4")
            .with_exposed_port(6333)
            .as_service()
        )
        redis = (
            dag.container()
            .from_("redis:7-alpine")
            .with_exposed_port(6379)
            .as_service()
        )

        return await (
            dag.container()
            .from_("ghcr.io/astral-sh/uv:python3.12-alpine")
            .with_directory("/app", source)
            .with_workdir("/app")
            .with_service_binding("memgraph", memgraph)
            .with_service_binding("qdrant", qdrant)
            .with_service_binding("redis", redis)
            .with_env_variable("MEMGRAPH_HOST", "memgraph")
            .with_env_variable("QDRANT_HOST", "qdrant")
            .with_env_variable("REDIS_HOST", "redis")
            .with_exec(["uv", "sync", "--frozen", "--all-extras"])
            .with_exec(["uv", "run", "pytest", "-m", "integration", "-v"])
            .stdout()
        )

    @function
    async def check(self, source: dagger.Directory) -> str:
        """Run lint + typecheck in parallel."""
        lint_result = await self.lint(source)
        typecheck_result = await self.typecheck(source)
        return f"=== LINT ===\n{lint_result}\n=== TYPECHECK ===\n{typecheck_result}"

    @function
    async def all(self, source: dagger.Directory) -> str:
        """Run full test pipeline: lint, typecheck, test, test-integration."""
        check_result = await self.check(source)
        test_result = await self.test(source)
        integration_result = await self.test_integration(source)
        return (
            f"{check_result}\n"
            f"=== UNIT TESTS ===\n{test_result}\n"
            f"=== INTEGRATION TESTS ===\n{integration_result}"
        )
