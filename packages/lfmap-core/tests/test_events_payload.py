import json

import pytest

from lfmap_core import ToolError
from lfmap_core.events_payload import MAX_PAYLOAD_BYTES, decode_payload, encode_payload


def test_limit():
    assert MAX_PAYLOAD_BYTES == 65536


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({}, "{}"),
        ({"b": 1, "a": 2}, '{"a":2,"b":1}'),
        ({"path": "C:/Tài liệu/a.pdf"}, '{"path":"C:/Tài liệu/a.pdf"}'),
        (
            {"n": None, "t": True, "f": 1.5, "l": [1, "x", {"z": 0, "y": []}]},
            '{"f":1.5,"l":[1,"x",{"y":[],"z":0}],"n":null,"t":true}',
        ),
        ({"tuple": (1, 2)}, '{"tuple":[1,2]}'),
    ],
)
def test_encode(payload, expected):
    assert encode_payload(payload) == expected


def test_encode_returns_str():
    assert type(encode_payload({"a": 1})) is str


@pytest.mark.parametrize("payload", [None, [], [1], "x", 1, b"{}", ({"a": 1},)])
def test_encode_rejects_non_objects(payload):
    with pytest.raises(ToolError) as caught:
        encode_payload(payload)
    assert caught.value.code == "invalid_input"
    assert caught.value.details == {"reason": "not_object"}


@pytest.mark.parametrize(
    "payload",
    [
        {"a": float("nan")},
        {"a": float("inf")},
        {"a": {1, 2}},
        {"a": b"bytes"},
        {"a": object()},
        {1: "int key"},
        {"a": {2: "nested int key"}},
        {"a": [{None: 1}]},
        {"a": {True: 1}},
        {(1, 2): "tuple key"},
    ],
)
def test_encode_rejects_non_json(payload):
    with pytest.raises(ToolError) as caught:
        encode_payload(payload)
    assert caught.value.code == "invalid_input"
    assert caught.value.details == {"reason": "not_json"}


def test_encode_rejects_cycles():
    payload: dict = {}
    payload["self"] = payload
    with pytest.raises(ToolError) as caught:
        encode_payload(payload)
    assert caught.value.details == {"reason": "not_json"}


def _sized(size: int, char: str = "x") -> dict:
    """A payload whose encoded form is exactly `size` bytes ({"k":"..."} costs 8 bytes around the value)."""
    width = len(char.encode("utf-8"))
    assert (size - 8) % width == 0
    return {"k": char * ((size - 8) // width)}


def test_encode_accepts_exactly_the_limit():
    text = encode_payload(_sized(MAX_PAYLOAD_BYTES))
    assert len(text.encode("utf-8")) == MAX_PAYLOAD_BYTES


def test_encode_rejects_one_byte_over():
    with pytest.raises(ToolError) as caught:
        encode_payload(_sized(MAX_PAYLOAD_BYTES + 1))
    assert caught.value.code == "invalid_input"
    assert caught.value.details == {"reason": "too_large", "bytes": MAX_PAYLOAD_BYTES + 1, "limit": MAX_PAYLOAD_BYTES}


def test_limit_counts_utf8_bytes_not_characters():
    payload = _sized(MAX_PAYLOAD_BYTES + 1, "\u1ec7")
    assert len(json.dumps(payload, ensure_ascii=False, separators=(",", ":"))) < MAX_PAYLOAD_BYTES
    with pytest.raises(ToolError) as caught:
        encode_payload(payload)
    assert caught.value.details["reason"] == "too_large"
    assert caught.value.details["bytes"] == MAX_PAYLOAD_BYTES + 1


def test_encode_does_not_change_the_input():
    payload = {"b": [3, 2, 1], "a": {"y": 1, "x": 2}}
    encode_payload(payload)
    assert payload == {"b": [3, 2, 1], "a": {"y": 1, "x": 2}}
    assert list(payload) == ["b", "a"]


@pytest.mark.parametrize(
    "payload", [{}, {"a": 1}, {"path": "D:/Hồ sơ/ảnh.png", "items": [1, 2.5, None, False], "nested": {"k": "v"}}]
)
def test_round_trip(payload):
    assert decode_payload(encode_payload(payload)) == payload


def test_decode_returns_dict():
    assert decode_payload('{"a":[1,2]}') == {"a": [1, 2]}


@pytest.mark.parametrize("text", ["[]", '"x"', "1", "null", "true"])
def test_decode_rejects_non_objects(text):
    with pytest.raises(ToolError) as caught:
        decode_payload(text)
    assert caught.value.code == "invalid_input"
    assert caught.value.details == {"reason": "not_object"}


@pytest.mark.parametrize("text", ["", "{", "{'a': 1}", '{"a": NaN}', '{"a": Infinity}', '{"a": -Infinity}', "{} x"])
def test_decode_rejects_bad_json(text):
    with pytest.raises(ToolError) as caught:
        decode_payload(text)
    assert caught.value.code == "invalid_input"
    assert caught.value.details == {"reason": "not_json"}


@pytest.mark.parametrize("value", [None, b"{}", 1, {}])
def test_decode_rejects_non_strings(value):
    with pytest.raises(ToolError) as caught:
        decode_payload(value)
    assert caught.value.code == "invalid_input"
    assert caught.value.details == {"reason": "not_json"}
