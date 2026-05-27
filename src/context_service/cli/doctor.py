"""engrammic doctor - verify installation and connectivity."""

from __future__ import annotations

import asyncio
import sys


async def check_redis() -> tuple[bool, str]:
    """Check Redis connectivity."""
    try:
        from context_service.config.settings import get_settings
        from context_service.stores.redis import RedisClient, create_redis_pool

        settings = get_settings()
        redis = await create_redis_pool(settings)
        client = RedisClient(redis)
        ok = await client.health_check()
        await client.close()
        if ok:
            return True, "Redis connected"
        return False, "Redis ping returned false"
    except Exception as e:
        return False, f"Redis error: {e}"


async def check_graph() -> tuple[bool, str]:
    """Check Memgraph connectivity."""
    try:
        from context_service.config.settings import get_settings
        from context_service.stores.memgraph import MemgraphClient, create_memgraph_driver

        settings = get_settings()
        driver = await create_memgraph_driver(settings)
        client = MemgraphClient(driver)
        ok = await client.health_check()
        await client.close()
        if ok:
            return True, "Memgraph connected"
        return False, "Memgraph health check returned false"
    except Exception as e:
        return False, f"Memgraph error: {e}"


async def check_qdrant() -> tuple[bool, str]:
    """Check Qdrant connectivity."""
    try:
        from context_service.config.settings import get_settings
        from context_service.stores.qdrant import QdrantClient

        settings = get_settings()
        client = QdrantClient.from_settings(settings)
        ok = await client.health_check()
        await client.close()
        if ok:
            return True, "Qdrant connected"
        return False, "Qdrant health check returned false"
    except Exception as e:
        return False, f"Qdrant error: {e}"


async def run_doctor() -> int:
    """Run all health checks."""
    checks: list[tuple[str, object]] = [
        ("Redis", check_redis()),
        ("Memgraph", check_graph()),
        ("Qdrant", check_qdrant()),
    ]

    all_passed = True
    print("Engrammic Doctor")
    print("=" * 40)

    for name, coro in checks:
        try:
            passed, message = await coro  # type: ignore[misc]
        except Exception as e:
            passed, message = False, f"Check failed: {e}"
        status = "OK" if passed else "FAIL"
        print(f"[{status}] {name}: {message}")
        if not passed:
            all_passed = False

    print("=" * 40)
    if all_passed:
        print("All checks passed!")
        return 0
    print("Some checks failed. See above for details.")
    return 1


def main() -> None:
    """CLI entrypoint."""
    sys.exit(asyncio.run(run_doctor()))


if __name__ == "__main__":
    main()
