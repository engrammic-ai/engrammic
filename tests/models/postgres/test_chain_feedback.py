"""Tests for ChainDelivery and ChainFeedback Postgres models."""

from uuid import uuid4

from sqlalchemy import inspect

from context_service.models.postgres.chain_feedback import ChainDelivery, ChainFeedback


def test_chain_delivery_columns():
    """ChainDelivery has required columns."""
    mapper = inspect(ChainDelivery)
    columns = {c.key for c in mapper.columns}
    assert columns == {
        "id",
        "session_id",
        "chain_id",
        "query",
        "similarity_score",
        "delivered_at",
    }


def test_chain_delivery_instantiation():
    """ChainDelivery can be instantiated with required fields."""
    session_id = uuid4()
    chain_id = uuid4()
    delivery = ChainDelivery(
        session_id=session_id,
        chain_id=chain_id,
        query="What steps were taken to resolve the auth issue?",
    )
    assert delivery.session_id == session_id
    assert delivery.chain_id == chain_id
    assert delivery.query == "What steps were taken to resolve the auth issue?"
    assert delivery.similarity_score is None


def test_chain_delivery_with_similarity_score():
    """ChainDelivery accepts an optional similarity_score."""
    delivery = ChainDelivery(
        session_id=uuid4(),
        chain_id=uuid4(),
        query="debugging steps",
        similarity_score=0.87,
    )
    assert delivery.similarity_score == 0.87


def test_chain_delivery_primary_key_default():
    """ChainDelivery id column has a callable default (uuid4)."""
    table = ChainDelivery.__table__
    id_col = table.c["id"]
    assert id_col.default is not None
    assert callable(id_col.default.arg)


def test_chain_delivery_indexes():
    """ChainDelivery has expected indexes on session_id and delivered_at."""
    table = ChainDelivery.__table__
    index_names = {idx.name for idx in table.indexes}
    assert "ix_chain_delivery_session_id" in index_names
    assert "ix_chain_delivery_delivered_at" in index_names


def test_chain_delivery_server_default_delivered_at():
    """ChainDelivery delivered_at has a server_default."""
    table = ChainDelivery.__table__
    assert table.c["delivered_at"].server_default is not None


def test_chain_feedback_columns():
    """ChainFeedback has required columns."""
    mapper = inspect(ChainFeedback)
    columns = {c.key for c in mapper.columns}
    assert columns == {
        "id",
        "chain_id",
        "signal",
        "created_at",
    }


def test_chain_feedback_instantiation():
    """ChainFeedback can be instantiated with required fields."""
    chain_id = uuid4()
    feedback = ChainFeedback(chain_id=chain_id, signal="useful")
    assert feedback.chain_id == chain_id
    assert feedback.signal == "useful"


def test_chain_feedback_primary_key_default():
    """ChainFeedback id column has a callable default (uuid4)."""
    table = ChainFeedback.__table__
    id_col = table.c["id"]
    assert id_col.default is not None
    assert callable(id_col.default.arg)


def test_chain_feedback_index():
    """ChainFeedback has expected index on chain_id."""
    table = ChainFeedback.__table__
    index_names = {idx.name for idx in table.indexes}
    assert "ix_chain_feedback_chain_id" in index_names


def test_chain_feedback_server_default_created_at():
    """ChainFeedback created_at has a server_default."""
    table = ChainFeedback.__table__
    assert table.c["created_at"].server_default is not None


def test_chain_feedback_signal_max_length():
    """ChainFeedback signal column has length constraint of 20."""
    table = ChainFeedback.__table__
    assert table.c["signal"].type.length == 20
