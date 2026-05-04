"""Tests for cycle detection in supersession."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from context_service.custodian.supersession import detect_structured_supersession


@dataclass
class MockSPONode:
    id: str
    subject: str
    predicate: str
    object: str
    confidence: float
    created_at: datetime


class TestCycleDetection:
    def test_circular_pair_no_edge(self) -> None:
        """A references B, B references A - should not create edges that form cycle."""
        now = datetime.now(UTC)
        node_a = MockSPONode(
            id="a",
            subject="entity1",
            predicate="relates_to",
            object="entity2",
            confidence=0.9,
            created_at=now,
        )
        node_b = MockSPONode(
            id="b",
            subject="entity2",
            predicate="relates_to",
            object="entity1",
            confidence=0.9,
            created_at=now,
        )

        pairs = detect_structured_supersession([node_a, node_b])

        # Should not have both directions - that would be a cycle
        superseding_ids = {p.superseding_id for p in pairs}
        superseded_ids = {p.superseded_id for p in pairs}

        # If A supersedes B, B cannot supersede A
        assert not (superseding_ids & superseded_ids), "Cycle detected in supersession pairs"

    def test_chain_no_cycle(self) -> None:
        """A -> B -> C chain should work, but C -> A should not be added."""
        now = datetime.now(UTC)
        nodes = [
            MockSPONode(
                id="a",
                subject="topic",
                predicate="has_value",
                object="old",
                confidence=0.7,
                created_at=now,
            ),
            MockSPONode(
                id="b",
                subject="topic",
                predicate="has_value",
                object="newer",
                confidence=0.8,
                created_at=now,
            ),
            MockSPONode(
                id="c",
                subject="topic",
                predicate="has_value",
                object="newest",
                confidence=0.9,
                created_at=now,
            ),
        ]

        pairs = detect_structured_supersession(nodes)

        # Build graph and check for cycles
        graph: dict[str, set[str]] = {}
        for p in pairs:
            graph.setdefault(p.superseding_id, set()).add(p.superseded_id)

        # DFS cycle check
        def has_cycle(node: str, visited: set[str], path: set[str]) -> bool:
            visited.add(node)
            path.add(node)
            for neighbor in graph.get(node, set()):
                if neighbor in path:
                    return True
                if neighbor not in visited and has_cycle(neighbor, visited, path):
                    return True
            path.remove(node)
            return False

        visited: set[str] = set()
        for node in graph:
            if node not in visited:
                assert not has_cycle(node, visited, set()), f"Cycle found starting from {node}"


@dataclass
class MockLLMPair:
    superseding_id: str
    superseded_id: str
    confidence: float
    reason: str


class TestLLMPathCycleDetection:
    def test_llm_pairs_filtered_for_cycles(self) -> None:
        """LLM pairs that would create cycles should be filtered out."""
        from context_service.custodian.supersession import filter_cyclic_pairs

        pairs = [
            MockLLMPair("a", "b", 0.9, "semantic"),
            MockLLMPair("b", "c", 0.9, "semantic"),
            MockLLMPair("c", "a", 0.9, "semantic"),  # This creates a cycle
        ]

        filtered = filter_cyclic_pairs(pairs)

        # Should have at most 2 pairs (the cycle-creating one removed)
        assert len(filtered) <= 2

        # Verify no cycles in result
        graph: dict[str, set[str]] = {}
        for p in filtered:
            graph.setdefault(p.superseding_id, set()).add(p.superseded_id)

        def has_cycle(node: str, visited: set[str], path: set[str]) -> bool:
            visited.add(node)
            path.add(node)
            for neighbor in graph.get(node, set()):
                if neighbor in path:
                    return True
                if neighbor not in visited and has_cycle(neighbor, visited, path):
                    return True
            path.remove(node)
            return False

        visited: set[str] = set()
        for node in graph:
            if node not in visited:
                assert not has_cycle(node, visited, set())
