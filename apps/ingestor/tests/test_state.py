from sparkplug import DataType, Metric

from ingestor.state import SparkplugState, parse_dbirth

EDGE, DEV = "edge1", "laser1"


def birthed_state(bd_seq: int = 0) -> SparkplugState:
    s = SparkplugState()
    s.on_nbirth(EDGE, [Metric("bdSeq", None, DataType.Int64, bd_seq)], seq=0)
    assert not s.on_dbirth_seq(EDGE, 1).needs_rebirth
    s.register_device(EDGE, DEV, {100: 7, 101: 8})
    return s


def data(alias: int, value: float) -> Metric:
    return Metric(None, alias, DataType.Double, value, 1_700_000_000_000)


def test_parse_dbirth_separates_metadata_from_metrics() -> None:
    birth = parse_dbirth(
        [
            Metric("Properties/AssetType", None, DataType.String, "laser"),
            Metric("power_w", 100, DataType.Double, None),
            Metric("Properties/Unit/power_w", None, DataType.String, "W"),
        ]
    )
    assert birth.asset_type == "laser"
    assert [(m.name, m.alias, m.unit) for m in birth.metrics] == [("power_w", 100, "W")]


def test_ddata_maps_aliases_to_tags() -> None:
    s = birthed_state()
    result = s.on_ddata(EDGE, DEV, 2, [data(100, 1000.0), data(101, 35.0)], None)
    assert not result.needs_rebirth
    assert [(r.tag_id, r.value) for r in result.rows] == [(7, 1000.0), (8, 35.0)]
    assert result.rows[0].ts.year == 2023  # metric timestamp used, not arrival time


def test_seq_gap_keeps_data_but_requests_rebirth() -> None:
    s = birthed_state()
    result = s.on_ddata(EDGE, DEV, 5, [data(100, 1.0)], None)  # expected 2, got 5
    assert result.needs_rebirth and "seq gap" in (result.reason or "")
    assert len(result.rows) == 1  # values we can map are still valid


def test_seq_wraps_255_to_0() -> None:
    s = birthed_state()
    s.nodes[EDGE].last_seq = 255
    assert not s.on_ddata(EDGE, DEV, 0, [data(100, 1.0)], None).needs_rebirth


def test_data_from_unknown_node_or_device_requests_rebirth() -> None:
    s = SparkplugState()
    assert s.on_ddata("ghost", DEV, 0, [data(100, 1.0)], None).needs_rebirth
    s = birthed_state()
    result = s.on_ddata(EDGE, "unknown-device", 2, [data(100, 1.0)], None)
    assert result.needs_rebirth and result.rows == []


def test_unknown_alias_requests_rebirth() -> None:
    s = birthed_state()
    result = s.on_ddata(EDGE, DEV, 2, [data(999, 1.0), data(100, 2.0)], None)
    assert result.needs_rebirth and [r.value for r in result.rows] == [2.0]


def test_stale_ndeath_is_ignored_current_one_applies() -> None:
    s = birthed_state(bd_seq=3)
    stale = [Metric("bdSeq", None, DataType.Int64, 2)]  # from the previous session
    assert s.on_ndeath(EDGE, stale) is False and s.nodes[EDGE].online
    current = [Metric("bdSeq", None, DataType.Int64, 3)]
    assert s.on_ndeath(EDGE, current) is True and not s.nodes[EDGE].online
    assert s.on_ddata(EDGE, DEV, 2, [data(100, 1.0)], None).needs_rebirth  # offline now


def test_strings_and_nulls_are_not_stored_bools_are() -> None:
    s = birthed_state()
    metrics = [
        Metric(None, 100, DataType.String, "auto", None),
        Metric(None, 101, DataType.Boolean, True, None),
    ]
    rows = s.on_ddata(EDGE, DEV, 2, metrics, 1_700_000_000_000).rows
    assert [(r.tag_id, r.value) for r in rows] == [(8, 1.0)]
