"""Mixin protocol for raw Cypher execution against Memgraph.

Raw Cypher is an implementation detail of the Memgraph backend, not part of
the abstract HyperGraphStore interface. Code that genuinely needs escape-hatch
access to raw Cypher should accept RawCypherMixin (or a union of
HyperGraphStore | RawCypherMixin) rather than HyperGraphStore alone.

New code should prefer the domain-level HyperGraphStore methods wherever possible.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager


class RawCypherMixin(Protocol):
    """Protocol for objects that expose raw Cypher execution.

    Implemented by MemgraphStore (via delegation to MemgraphClient).
    Only accept this type when raw Cypher is genuinely unavoidable.
    """

    async def execute_query(
        self,
        cypher: str,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Run a read-only Cypher query and return results as a list of dicts."""
        ...

    async def execute_write(
        self,
        cypher: str,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Run a write Cypher query within a transaction and return results as a list of dicts."""
        ...

    def session(self) -> AbstractAsyncContextManager[Any]:
        """Return an async context manager yielding a database session for transaction scope."""
        ...

    def transaction(self) -> AbstractAsyncContextManager[Any]:
        """Return an async context manager yielding an explicit transaction.

        The transaction is committed on clean exit and rolled back if the body raises.
        Prefer this over session() + begin_transaction() for atomic writes.
        """
        ...
