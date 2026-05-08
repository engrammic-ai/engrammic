"""Edge-case tests for context_service.utils.json (orjson-backed helpers)."""

import uuid
from datetime import UTC, datetime, timedelta, timezone

import pytest

from context_service.utils.json import JSONDecodeError, dumps, loads

# ---------------------------------------------------------------------------
# datetime serialization
# ---------------------------------------------------------------------------


class TestDatetimeSerialization:
    def test_utc_aware_datetime(self) -> None:
        dt = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)
        result = loads(dumps({"ts": dt}))
        assert result["ts"] == "2024-06-01T12:00:00+00:00"

    def test_offset_aware_datetime(self) -> None:
        tz = timezone(timedelta(hours=5, minutes=30))
        dt = datetime(2024, 6, 1, 12, 0, 0, tzinfo=tz)
        result = loads(dumps({"ts": dt}))
        assert "+05:30" in result["ts"]

    def test_naive_datetime_serialized(self) -> None:
        # orjson serializes naive datetimes without tz offset
        dt = datetime(2024, 1, 15, 8, 30, 0)
        result = dumps({"ts": dt})
        assert "2024-01-15" in result

    def test_datetime_in_list(self) -> None:
        dts = [datetime(2024, i, 1, tzinfo=UTC) for i in range(1, 4)]
        result = loads(dumps(dts))
        assert len(result) == 3
        assert all("2024" in s for s in result)

    def test_datetime_microseconds_preserved(self) -> None:
        dt = datetime(2024, 1, 1, 0, 0, 0, 123456, tzinfo=UTC)
        result = loads(dumps({"ts": dt}))
        assert "123456" in result["ts"]


# ---------------------------------------------------------------------------
# UUID serialization
# ---------------------------------------------------------------------------


class TestUUIDSerialization:
    def test_uuid4_roundtrip_as_string(self) -> None:
        uid = uuid.uuid4()
        result = loads(dumps({"id": uid}))
        assert result["id"] == str(uid)

    def test_uuid_in_nested_dict(self) -> None:
        uid = uuid.UUID("12345678-1234-5678-1234-567812345678")
        data = {"outer": {"inner": uid}}
        result = loads(dumps(data))
        assert result["outer"]["inner"] == str(uid)

    def test_uuid_in_list(self) -> None:
        uids = [uuid.uuid4() for _ in range(5)]
        result = loads(dumps(uids))
        assert result == [str(u) for u in uids]


# ---------------------------------------------------------------------------
# Nested structures with mixed types
# ---------------------------------------------------------------------------


class TestNestedMixedTypes:
    def test_dict_with_int_float_str_bool(self) -> None:
        data = {"i": 1, "f": 3.14, "s": "hello", "b": True, "n": None}
        assert loads(dumps(data)) == data

    def test_list_of_dicts(self) -> None:
        data = [{"k": i} for i in range(10)]
        assert loads(dumps(data)) == data

    def test_dict_of_lists(self) -> None:
        data = {"a": [1, 2, 3], "b": ["x", "y"]}
        assert loads(dumps(data)) == data

    def test_mixed_list_types(self) -> None:
        data = [1, "two", 3.0, True, None, {"k": "v"}, [1, 2]]
        assert loads(dumps(data)) == data

    def test_nested_mixed_with_datetime_and_uuid(self) -> None:
        uid = uuid.uuid4()
        dt = datetime(2025, 1, 1, tzinfo=UTC)
        data = {"meta": {"uid": uid, "created": dt, "tags": ["a", "b"]}}
        result = loads(dumps(data))
        assert result["meta"]["uid"] == str(uid)
        assert "2025-01-01" in result["meta"]["created"]
        assert result["meta"]["tags"] == ["a", "b"]


# ---------------------------------------------------------------------------
# None / null handling
# ---------------------------------------------------------------------------


class TestNullHandling:
    def test_none_value(self) -> None:
        assert loads(dumps(None)) is None

    def test_dict_with_none_values(self) -> None:
        data = {"a": None, "b": 1, "c": None}
        assert loads(dumps(data)) == data

    def test_list_with_none(self) -> None:
        data = [None, None, 1, None]
        assert loads(dumps(data)) == data

    def test_nested_none(self) -> None:
        data = {"x": {"y": None}}
        assert loads(dumps(data)) == data


# ---------------------------------------------------------------------------
# Edge cases: empty / deeply nested / large payloads
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_dict(self) -> None:
        assert loads(dumps({})) == {}

    def test_empty_list(self) -> None:
        assert loads(dumps([])) == []

    def test_empty_string_value(self) -> None:
        assert loads(dumps({"k": ""})) == {"k": ""}

    def test_deeply_nested_dict(self) -> None:
        depth = 50
        obj: dict = {}
        node = obj
        for _ in range(depth - 1):
            node["child"] = {}
            node = node["child"]
        node["leaf"] = "deep"
        result = loads(dumps(obj))
        # traverse result to verify leaf
        r = result
        for _ in range(depth - 1):
            r = r["child"]
        assert r["leaf"] == "deep"

    def test_large_payload(self) -> None:
        data = {str(i): i for i in range(1000)}
        result = loads(dumps(data))
        assert len(result) == 1000
        assert result["999"] == 999

    def test_large_list(self) -> None:
        data = list(range(10_000))
        assert loads(dumps(data)) == data

    def test_unicode_strings(self) -> None:
        data = {"text": "hello 世界 \U0001f600"}
        assert loads(dumps(data)) == data

    def test_zero_and_negative_numbers(self) -> None:
        data = {"zero": 0, "neg": -42, "neg_float": -3.14}
        assert loads(dumps(data)) == data

    def test_boolean_values(self) -> None:
        data = {"t": True, "f": False}
        assert loads(dumps(data)) == data


# ---------------------------------------------------------------------------
# sort_keys option
# ---------------------------------------------------------------------------


class TestSortKeys:
    def test_sort_keys_produces_sorted_output(self) -> None:
        data = {"z": 1, "a": 2, "m": 3}
        result = dumps(data, sort_keys=True)
        # Verify ordering in the raw string
        pos_a = result.index('"a"')
        pos_m = result.index('"m"')
        pos_z = result.index('"z"')
        assert pos_a < pos_m < pos_z

    def test_sort_keys_false_roundtrip(self) -> None:
        data = {"z": 1, "a": 2}
        assert loads(dumps(data, sort_keys=False)) == data


# ---------------------------------------------------------------------------
# Round-trip fidelity
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_str_roundtrip(self) -> None:
        assert loads(dumps("hello")) == "hello"

    def test_int_roundtrip(self) -> None:
        assert loads(dumps(42)) == 42

    def test_float_roundtrip(self) -> None:
        assert loads(dumps(3.14)) == pytest.approx(3.14)

    def test_bool_roundtrip(self) -> None:
        assert loads(dumps(True)) is True
        assert loads(dumps(False)) is False

    def test_complex_roundtrip(self) -> None:
        data = {
            "name": "test",
            "values": [1, 2, 3],
            "nested": {"flag": True, "count": 0},
            "nullable": None,
        }
        assert loads(dumps(data)) == data

    def test_bytes_input_to_loads(self) -> None:
        raw = b'{"key": "value"}'
        assert loads(raw) == {"key": "value"}

    def test_dumps_returns_str(self) -> None:
        result = dumps({"k": "v"})
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Malformed input handling
# ---------------------------------------------------------------------------


class TestMalformedInput:
    def test_invalid_json_string_raises(self) -> None:
        with pytest.raises(JSONDecodeError):
            loads("{not valid json}")

    def test_empty_string_raises(self) -> None:
        with pytest.raises(JSONDecodeError):
            loads("")

    def test_truncated_json_raises(self) -> None:
        with pytest.raises(JSONDecodeError):
            loads('{"key": ')

    def test_trailing_comma_raises(self) -> None:
        with pytest.raises(JSONDecodeError):
            loads('{"key": 1,}')

    def test_bare_string_not_quoted_raises(self) -> None:
        with pytest.raises(JSONDecodeError):
            loads("hello")

    def test_json_decode_error_is_importable(self) -> None:
        # Ensure re-export works so callers don't need stdlib json
        from context_service.utils.json import JSONDecodeError as JDE
        assert JDE is JSONDecodeError
