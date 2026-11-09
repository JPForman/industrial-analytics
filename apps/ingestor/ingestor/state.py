"""Sparkplug B consumer state machine. Pure: no I/O, so every rule is unit-testable.

Tracks, per edge node: the current session (bdSeq), the last seq seen, and per device the
alias -> tag_id map learned from DBIRTH. Decides when data is trustworthy and when a
rebirth must be requested.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime

from sparkplug import Metric

ASSET_TYPE = "Properties/AssetType"
UNIT_PREFIX = "Properties/Unit/"


@dataclass(frozen=True)
class BirthMetric:
    name: str
    alias: int
    unit: str


@dataclass(frozen=True)
class DeviceBirth:
    asset_type: str | None
    metrics: list[BirthMetric]


@dataclass(frozen=True)
class Row:
    tag_id: int
    ts: datetime
    value: float


@dataclass
class DataResult:
    rows: list[Row] = field(default_factory=list)
    needs_rebirth: bool = False
    reason: str | None = None


@dataclass
class NodeState:
    bd_seq: int | None = None
    last_seq: int | None = None
    online: bool = False
    devices: dict[str, dict[int, int]] = field(default_factory=dict)  # device -> alias -> tag_id


def parse_dbirth(metrics: list[Metric]) -> DeviceBirth:
    """Split a DBIRTH into real metrics and our `Properties/...` metadata convention."""
    units = {
        m.name.removeprefix(UNIT_PREFIX): str(m.value)
        for m in metrics
        if m.name and m.name.startswith(UNIT_PREFIX)
    }
    asset_type = next((str(m.value) for m in metrics if m.name == ASSET_TYPE), None)
    real = [
        BirthMetric(m.name, m.alias, units.get(m.name, ""))
        for m in metrics
        if m.name and not m.name.startswith("Properties/") and m.alias is not None
    ]
    return DeviceBirth(asset_type, real)


def _to_float(value: float | int | bool | str | None) -> float | None:
    if value is None or isinstance(value, str):
        return None  # readings are numeric; strings/nulls are not stored as readings
    return float(value)  # bool -> 1.0 / 0.0


class SparkplugState:
    def __init__(self) -> None:
        self.nodes: dict[str, NodeState] = {}

    def _check_seq(self, node: NodeState, seq: int | None) -> bool:
        """True if `seq` is exactly the next expected value (mod 256). Always records it."""
        expected = None if node.last_seq is None else (node.last_seq + 1) % 256
        node.last_seq = seq
        return seq is not None and expected is not None and seq == expected

    def on_nbirth(self, edge: str, metrics: list[Metric], seq: int | None) -> None:
        bd_seq = next(
            (int(m.value) for m in metrics if m.name == "bdSeq" and m.value is not None), None
        )
        # A node birth starts a fresh session: forget device alias maps (they will re-birth).
        self.nodes[edge] = NodeState(bd_seq=bd_seq, last_seq=seq, online=True)

    def on_ndeath(self, edge: str, metrics: list[Metric]) -> bool:
        """Returns True if the death applied. A death whose bdSeq doesn't match the current
        session is from an old connection (arrived late) and must be ignored."""
        node = self.nodes.get(edge)
        bd_seq = next(
            (int(m.value) for m in metrics if m.name == "bdSeq" and m.value is not None), None
        )
        if node is None or bd_seq != node.bd_seq:
            return False
        node.online = False
        node.devices.clear()
        return True

    def on_dbirth_seq(self, edge: str, seq: int | None) -> DataResult:
        node = self.nodes.get(edge)
        if node is None:
            return DataResult(needs_rebirth=True, reason=f"DBIRTH from unknown node {edge}")
        if not self._check_seq(node, seq):
            return DataResult(needs_rebirth=True, reason=f"seq gap on {edge} at DBIRTH")
        return DataResult()

    def register_device(self, edge: str, device: str, alias_to_tag: dict[int, int]) -> None:
        self.nodes.setdefault(edge, NodeState()).devices[device] = alias_to_tag

    def on_ddeath(self, edge: str, device: str) -> None:
        node = self.nodes.get(edge)
        if node:
            node.devices.pop(device, None)

    def on_ddata(
        self,
        edge: str,
        device: str,
        seq: int | None,
        metrics: list[Metric],
        payload_ts_ms: int | None,
    ) -> DataResult:
        node = self.nodes.get(edge)
        if node is None or not node.online:
            return DataResult(needs_rebirth=True, reason=f"DDATA from unknown/offline node {edge}")
        result = DataResult()
        if not self._check_seq(node, seq):
            # Something was lost. Keep the values we can map (they are still valid), but ask
            # for a rebirth so our view of the node is guaranteed complete again.
            result.needs_rebirth, result.reason = True, f"seq gap on {edge} (got {seq})"
        aliases = node.devices.get(device)
        if aliases is None:
            return DataResult(needs_rebirth=True, reason=f"DDATA before DBIRTH for {edge}/{device}")
        for m in metrics:
            value = _to_float(m.value)
            tag_id = aliases.get(m.alias) if m.alias is not None else None
            if tag_id is None:
                result.needs_rebirth, result.reason = True, f"unknown alias {m.alias} on {device}"
                continue
            if value is None:
                continue
            ts_ms = m.timestamp_ms or payload_ts_ms
            ts = datetime.fromtimestamp(ts_ms / 1000, UTC) if ts_ms else datetime.now(UTC)
            result.rows.append(Row(tag_id, ts, value))
        return result
