import pytest

from sparkplug import DataType, MessageType, Metric, Topic, decode, encode


def test_topic_round_trip() -> None:
    t = Topic("Buffalo", MessageType.DDATA, "edge1", "laser1")
    assert str(t) == "spBv1.0/Buffalo/DDATA/edge1/laser1"
    assert Topic.parse(str(t)) == t
    node = Topic.parse("spBv1.0/Buffalo/NBIRTH/edge1")
    assert node.device_id is None and node.message_type is MessageType.NBIRTH


@pytest.mark.parametrize("bad", ["foo/bar", "spBv1.0/g/NOPE/e", "spBv2/g/NDATA/e"])
def test_topic_rejects_garbage(bad: str) -> None:
    with pytest.raises(ValueError):
        Topic.parse(bad)


def test_payload_round_trip_all_value_types() -> None:
    metrics = [
        Metric("power_w", 1, DataType.Double, 1234.5),
        Metric("count", 2, DataType.Int64, 2**40),
        Metric("on", 3, DataType.Boolean, True),
        Metric("mode", 4, DataType.String, "auto"),
        Metric("temp", 5, DataType.Float, None),  # null value
    ]
    payload, decoded = decode(encode(metrics, seq=300, timestamp_ms=1_700_000_000_000))
    assert payload.seq == 300 % 256  # seq wraps at 256
    assert payload.timestamp == 1_700_000_000_000
    assert [m.value for m in decoded] == [1234.5, 2**40, True, "auto", None]
    assert [m.alias for m in decoded] == [1, 2, 3, 4, 5]


def test_data_messages_can_omit_names() -> None:
    _, (m,) = decode(encode([Metric(None, 7, DataType.Double, 1.0)], seq=1))
    assert m.name is None and m.alias == 7
