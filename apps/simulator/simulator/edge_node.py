"""Sparkplug B edge-node state and message builders (pure: no I/O, easy to test)."""

from dataclasses import dataclass, field

from sparkplug import DataType, MessageType, Metric, Topic, encode, now_ms

from simulator.machines import Machine

REBIRTH = "Node Control/Rebirth"
ASSET_TYPE = "Properties/AssetType"
UNIT_PREFIX = "Properties/Unit/"  # convention: per-metric engineering unit, sent in DBIRTH


@dataclass
class EdgeNode:
    group_id: str
    edge_node_id: str
    machines: list[Machine]
    bd_seq: int = 0  # increments per MQTT session; ties NBIRTH to its NDEATH
    _seq: int = field(default=0, repr=False)

    def topic(self, msg: MessageType, device_id: str | None = None) -> str:
        return str(Topic(self.group_id, msg, self.edge_node_id, device_id))

    def next_seq(self) -> int:
        seq = self._seq
        self._seq = (self._seq + 1) % 256
        return seq

    @staticmethod
    def alias(device_index: int, metric_index: int) -> int:
        # Unique per edge node. DATA messages carry only this number, not the name.
        return (device_index + 1) * 100 + metric_index

    def ndeath(self) -> tuple[str, bytes]:
        """Registered as the MQTT Last Will: the broker publishes it if we vanish."""
        return self.topic(MessageType.NDEATH), encode(
            [Metric("bdSeq", None, DataType.Int64, self.bd_seq)], seq=None
        )

    def nbirth(self) -> tuple[str, bytes]:
        self._seq = 0  # NBIRTH always starts the sequence at 0
        metrics = [
            Metric("bdSeq", None, DataType.Int64, self.bd_seq),
            Metric(REBIRTH, None, DataType.Boolean, False),
        ]
        return self.topic(MessageType.NBIRTH), encode(metrics, seq=self.next_seq())

    def dbirths(self) -> list[tuple[str, bytes]]:
        out = []
        for d, machine in enumerate(self.machines):
            metrics = [Metric(ASSET_TYPE, None, DataType.String, machine.asset_type)]
            for i, spec in enumerate(machine.metrics):
                metrics.append(Metric(spec.name, self.alias(d, i), spec.datatype, None))
                metrics.append(Metric(UNIT_PREFIX + spec.name, None, DataType.String, spec.unit))
            topic = self.topic(MessageType.DBIRTH, machine.device_id)
            out.append((topic, encode(metrics, seq=self.next_seq())))
        return out

    def ddata(self, values_per_machine: list[list[float | int]]) -> list[tuple[str, bytes]]:
        ts = now_ms()
        out = []
        for d, (machine, values) in enumerate(zip(self.machines, values_per_machine, strict=True)):
            metrics = [
                Metric(None, self.alias(d, i), spec.datatype, value, ts)
                for i, (spec, value) in enumerate(zip(machine.metrics, values, strict=True))
            ]
            topic = self.topic(MessageType.DDATA, machine.device_id)
            out.append((topic, encode(metrics, seq=self.next_seq(), timestamp_ms=ts)))
        return out
