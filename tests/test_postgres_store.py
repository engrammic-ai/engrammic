"""Tests for PostgresStore repository layer."""

from __future__ import annotations

from context_service.engine.postgres_store import PostgresStore


def test_postgres_store_has_required_methods() -> None:
    """PostgresStore exposes required methods."""
    store = PostgresStore()
    assert hasattr(store, "upsert_chain_steps")
    assert hasattr(store, "get_chain_steps")
    assert hasattr(store, "delete_chain_steps")
    assert hasattr(store, "add_orphaned_chain")
