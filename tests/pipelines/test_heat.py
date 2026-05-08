# tests/pipelines/test_heat.py
import math

from context_service.pipelines.assets.heat import (
    _APPLY_HEAT_CYPHER,
    _FETCH_EXISTING_HEAT_CYPHER,
    HEAT_HALF_LIFE_DAYS,
    HOT_THRESHOLD,
    WARM_THRESHOLD,
    XREAD_COUNT,
    _decay_factor,
    _tier,
    parse_event_type,
    parse_layer,
)


def test_heat_constants():
    assert HEAT_HALF_LIFE_DAYS == 7
    assert HOT_THRESHOLD == 0.66
    assert WARM_THRESHOLD == 0.33
    assert XREAD_COUNT == 10_000


def test_tier_hot():
    assert _tier(0.66) == "HOT"
    assert _tier(0.9) == "HOT"
    assert _tier(1.0) == "HOT"


def test_tier_warm():
    assert _tier(0.33) == "WARM"
    assert _tier(0.5) == "WARM"
    assert _tier(0.65) == "WARM"


def test_tier_cold():
    assert _tier(0.0) == "COLD"
    assert _tier(0.32) == "COLD"


def test_decay_factor_zero_age():
    assert _decay_factor(0.0) == 1.0


def test_decay_factor_one_half_life():
    half_life_s = HEAT_HALF_LIFE_DAYS * 86400.0
    result = _decay_factor(half_life_s)
    assert math.isclose(result, 0.5, rel_tol=1e-9)


def test_decay_factor_two_half_lives():
    half_life_s = HEAT_HALF_LIFE_DAYS * 86400.0
    result = _decay_factor(2 * half_life_s)
    assert math.isclose(result, 0.25, rel_tol=1e-9)


def test_parse_event_type_bytes():
    fields = {b"event_type": b"write"}
    assert parse_event_type(fields) == "write"


def test_parse_event_type_str():
    fields = {"event_type": "read"}
    assert parse_event_type(fields) == "read"


def test_parse_event_type_default():
    fields = {}
    assert parse_event_type(fields) == "read"


def test_parse_layer_bytes():
    fields = {b"layer": b"memory"}
    assert parse_layer(fields) == "memory"


def test_parse_layer_str():
    fields = {"layer": "knowledge"}
    assert parse_layer(fields) == "knowledge"


def test_parse_layer_missing():
    fields = {}
    assert parse_layer(fields) is None


def test_apply_heat_cypher_structure():
    assert "UNWIND $updates AS u" in _APPLY_HEAT_CYPHER
    assert "n.heat_score = u.heat_score" in _APPLY_HEAT_CYPHER
    assert "n.tier" in _APPLY_HEAT_CYPHER
    assert "silo_id" in _APPLY_HEAT_CYPHER


def test_fetch_existing_heat_cypher_structure():
    assert "UNWIND $node_ids AS nid" in _FETCH_EXISTING_HEAT_CYPHER
    assert "silo_id" in _FETCH_EXISTING_HEAT_CYPHER
    assert "heat_score" in _FETCH_EXISTING_HEAT_CYPHER
