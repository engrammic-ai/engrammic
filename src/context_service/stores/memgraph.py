"""Memgraph database client using the neo4j Python driver.

The neo4j driver works with Memgraph via the Bolt protocol.
"""

import contextlib
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from neo4j import AsyncDriver, AsyncGraphDatabase, AsyncSession, AsyncTransaction
from neo4j.exceptions import ClientError, ServiceUnavailable
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from context_service.config.logging import get_logger
from context_service.config.settings import Settings, get_settings

logger = get_logger(__name__)

_READ_RETRY_MAX_ATTEMPTS = 3
_WRITE_RETRY_MAX_ATTEMPTS = 3

_TRANSIENT_CLIENT_ERROR_CODES = frozenset(
    [
        "Memgraph.TransientError.DeadlockDetected",
        "Neo.TransientError.Transaction.DeadlockDetected",
        "Neo.TransientError.General.DatabaseUnavailable",
        "Neo.TransientError.Cluster.NotALeader",
        "Neo.TransientError.Cluster.LeaderChanged",
    ]
)


def _is_transient_client_error(exc: BaseException) -> bool:
    """Return True for ClientError codes that are safe to retry."""
    if not isinstance(exc, ClientError):
        return False
    code: str = getattr(exc, "code", "") or ""
    return code in _TRANSIENT_CLIENT_ERROR_CODES


def _coerce_params(params: dict[str, Any] | None) -> dict[str, Any]:
    """Stringify uuid.UUID values so the neo4j driver accepts them."""
    if not params:
        return {}
    out: dict[str, Any] = {}
    for k, v in params.items():
        if isinstance(v, uuid.UUID):
            out[k] = str(v)
        elif isinstance(v, list):
            out[k] = [str(x) if isinstance(x, uuid.UUID) else x for x in v]
        else:
            out[k] = v
    return out


class MemgraphOperationError(Exception):
    """Raised when a Memgraph operation fails."""


async def create_memgraph_driver(settings: Settings | None = None) -> AsyncDriver:
    """Create an async Memgraph driver with connection pooling.

    Args:
        settings: Application settings. Uses default settings if not provided.

    Returns:
        AsyncDriver instance connected to Memgraph.
    """
    if settings is None:
        settings = get_settings()

    auth = None
    if settings.memgraph_user:
        auth = (settings.memgraph_user, settings.memgraph_password)

    return AsyncGraphDatabase.driver(
        settings.memgraph_uri,
        auth=auth,
        max_connection_pool_size=50,
        connection_acquisition_timeout=30.0,
    )


class MemgraphClient:
    """High-level Memgraph client with query methods."""

    def __init__(self, driver: AsyncDriver) -> None:
        """Initialize the client with a driver.

        Args:
            driver: Neo4j async driver instance.
        """
        self._driver = driver

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Get a database session.

        Yields:
            AsyncSession for executing queries.
        """
        session = self._driver.session()
        try:
            yield session
        finally:
            await session.close()

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncTransaction]:
        """Yield an explicit bolt transaction for multi-statement atomic writes.

        The transaction is committed on clean exit and rolled back if the body raises.
        Retries are not performed at this layer — the caller decides retry policy.
        """
        async with self.session() as session:
            tx = await session.begin_transaction()
            try:
                yield tx
            except Exception:
                with contextlib.suppress(Exception):
                    await tx.rollback()
                raise
            else:
                await tx.commit()

    async def health_check(self) -> bool:
        """Check if Memgraph is reachable.

        Returns:
            True if healthy, False otherwise.
        """
        try:
            async with self.session() as session:
                result = await session.run("RETURN 1 AS n")
                await result.consume()
                return True
        except ServiceUnavailable:
            logger.warning("memgraph_health_check_failed", reason="service_unavailable")
            return False
        except Exception as e:
            logger.warning("memgraph_health_check_failed", error=str(e))
            return False

    async def execute_query(
        self,
        query: str,
        parameters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Execute a Cypher query and return results.

        Args:
            query: Cypher query string.
            parameters: Query parameters.

        Returns:
            List of result records as dictionaries.

        Raises:
            MemgraphOperationError: If the query fails.
        """

        async def _run_once() -> list[dict[str, Any]]:
            async with self.session() as session:
                result = await session.run(query, _coerce_params(parameters))
                data: list[dict[str, Any]] = await result.data()
                return data

        try:
            async for attempt in AsyncRetrying(
                retry=retry_if_exception_type(ServiceUnavailable),
                stop=stop_after_attempt(_READ_RETRY_MAX_ATTEMPTS),
                wait=wait_exponential(multiplier=0.1, max=2.0),
                reraise=True,
            ):
                with attempt:
                    attempt_number = attempt.retry_state.attempt_number
                    if attempt_number > 1:
                        logger.warning(
                            "memgraph_read_retry",
                            attempt=attempt_number,
                            max_attempts=_READ_RETRY_MAX_ATTEMPTS,
                        )
                    return await _run_once()
            return []
        except ServiceUnavailable as e:
            logger.error("memgraph_service_unavailable", error=str(e))
            raise MemgraphOperationError(f"Database unavailable: {e}") from e
        except RetryError as e:
            logger.error("memgraph_retry_exhausted", error=str(e))
            raise MemgraphOperationError(f"Database unavailable: {e}") from e
        except ClientError as e:
            logger.error("memgraph_query_error", error=str(e))
            raise MemgraphOperationError(f"Query failed: {e}") from e
        except Exception as e:
            logger.error("memgraph_unexpected_error", error=str(e))
            raise MemgraphOperationError(f"Database operation failed: {e}") from e

    async def execute_write(
        self,
        query: str,
        parameters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Execute a write query within a transaction.

        Args:
            query: Cypher query string.
            parameters: Query parameters.

        Returns:
            List of result records as dictionaries.

        Raises:
            MemgraphOperationError: If the write fails.
        """

        async def _write_tx(tx: Any, q: str, p: dict[str, Any]) -> list[dict[str, Any]]:
            result = await tx.run(q, p)
            data: list[dict[str, Any]] = await result.data()
            return data

        async def _run_once() -> list[dict[str, Any]]:
            async with self.session() as session:
                result: list[dict[str, Any]] = await session.execute_write(
                    _write_tx, query, _coerce_params(parameters)
                )
                return result

        retry_policy = retry_if_exception_type(ServiceUnavailable) | retry_if_exception(
            _is_transient_client_error
        )

        try:
            async for attempt in AsyncRetrying(
                retry=retry_policy,
                stop=stop_after_attempt(_WRITE_RETRY_MAX_ATTEMPTS),
                wait=wait_exponential(multiplier=0.1, max=2.0),
                reraise=True,
            ):
                with attempt:
                    attempt_number = attempt.retry_state.attempt_number
                    if attempt_number > 1:
                        logger.warning(
                            "memgraph_write_retry",
                            attempt=attempt_number,
                            max_attempts=_WRITE_RETRY_MAX_ATTEMPTS,
                        )
                    return await _run_once()
            return []
        except ServiceUnavailable as e:
            logger.error("memgraph_service_unavailable", error=str(e))
            raise MemgraphOperationError(f"Database unavailable: {e}") from e
        except RetryError as e:
            logger.error("memgraph_write_retry_exhausted", error=str(e))
            raise MemgraphOperationError(f"Database unavailable: {e}") from e
        except ClientError as e:
            logger.error("memgraph_write_error", error=str(e))
            raise MemgraphOperationError(f"Write failed: {e}") from e
        except Exception as e:
            logger.error("memgraph_unexpected_write_error", error=str(e))
            raise MemgraphOperationError(f"Database write failed: {e}") from e

    async def close(self) -> None:
        """Close the driver and release resources."""
        try:
            await self._driver.close()
        except Exception as e:
            logger.warning("memgraph_close_error", error=str(e))
