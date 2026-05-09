import asyncio
import pytest
from context_service.custodian.identities.triggers.async_batch import AsyncBatchTrigger


@pytest.mark.asyncio
async def test_batch_fires_on_size():
    fired = []

    async def on_fire(silo_id: str, node_ids: list[str]) -> None:
        fired.append((silo_id, node_ids))

    trigger = AsyncBatchTrigger(batch_size=3, window_seconds=10.0, on_fire=on_fire)

    await trigger.enqueue("silo1", "node1", "store")
    await trigger.enqueue("silo1", "node2", "store")
    assert len(fired) == 0

    await trigger.enqueue("silo1", "node3", "store")
    assert len(fired) == 1
    assert fired[0] == ("silo1", ["node1", "node2", "node3"])


@pytest.mark.asyncio
async def test_batch_fires_on_timeout():
    fired = []

    async def on_fire(silo_id: str, node_ids: list[str]) -> None:
        fired.append((silo_id, node_ids))

    trigger = AsyncBatchTrigger(batch_size=10, window_seconds=0.1, on_fire=on_fire)

    await trigger.enqueue("silo1", "node1", "store")
    assert len(fired) == 0

    await asyncio.sleep(0.15)
    assert len(fired) == 1
    assert fired[0] == ("silo1", ["node1"])
