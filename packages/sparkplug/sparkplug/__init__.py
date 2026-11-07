"""Minimal Sparkplug B (v1.0 topic namespace, 3.0 payload) helpers.

Topic:   spBv1.0/{group_id}/{message_type}/{edge_node_id}[/{device_id}]
Payload: protobuf `Payload` (see sparkplug_b.proto) carrying typed metrics.

Lifecycle: NBIRTH/DBIRTH announce metrics with names, aliases and datatypes; NDATA/DDATA
then send values by alias only; NDEATH (the MQTT Last Will) / DDEATH mark offline.
"""

from dataclasses import dataclass
from enum import StrEnum
from time import time

from sparkplug.sparkplug_b_pb2 import DataType, Payload

NAMESPACE = "spBv1.0"

__all__ = [
    "NAMESPACE",
    "DataType",
    "MessageType",
    "Metric",
    "Payload",
    "Topic",
    "decode",
    "encode",
    "now_ms",
]


class MessageType(StrEnum):
    NBIRTH = "NBIRTH"
    NDEATH = "NDEATH"
    NDATA = "NDATA"
    NCMD = "NCMD"
    DBIRTH = "DBIRTH"
    DDEATH = "DDEATH"
    DDATA = "DDATA"
    DCMD = "DCMD"
    STATE = "STATE"


@dataclass(frozen=True)
class Topic:
    group_id: str
    message_type: MessageType
    edge_node_id: str
    device_id: str | None = None

    def __str__(self) -> str:
        parts = [NAMESPACE, self.group_id, self.message_type, self.edge_node_id]
        if self.device_id:
            parts.append(self.device_id)
        return "/".join(parts)

    @classmethod
    def parse(cls, topic: str) -> Topic:
        parts = topic.split("/")
        if len(parts) not in (4, 5) or parts[0] != NAMESPACE:
            raise ValueError(f"Not a Sparkplug B topic: {topic!r}")
        return cls(parts[1], MessageType(parts[2]), parts[3], parts[4] if len(parts) == 5 else None)


@dataclass(frozen=True)
class Metric:
    """A decoded metric. In DATA messages `name` is usually None and `alias` identifies it."""

    name: str | None
    alias: int | None
    datatype: int
    value: float | int | bool | str | None
    timestamp_ms: int | None = None


# Which protobuf oneof field holds each datatype's value.
_FIELD = {
    DataType.Int8: "int_value",
    DataType.Int16: "int_value",
    DataType.Int32: "int_value",
    DataType.UInt8: "int_value",
    DataType.UInt16: "int_value",
    DataType.UInt32: "int_value",
    DataType.Int64: "long_value",
    DataType.UInt64: "long_value",
    DataType.DateTime: "long_value",
    DataType.Float: "float_value",
    DataType.Double: "double_value",
    DataType.Boolean: "boolean_value",
    DataType.String: "string_value",
    DataType.Text: "string_value",
}


def now_ms() -> int:
    return int(time() * 1000)


def encode(metrics: list[Metric], seq: int | None, timestamp_ms: int | None = None) -> bytes:
    payload = Payload(timestamp=timestamp_ms or now_ms())
    if seq is not None:
        payload.seq = seq % 256
    for m in metrics:
        pm = payload.metrics.add(datatype=m.datatype)
        if m.name is not None:
            pm.name = m.name
        if m.alias is not None:
            pm.alias = m.alias
        if m.timestamp_ms is not None:
            pm.timestamp = m.timestamp_ms
        if m.value is None:
            pm.is_null = True
        else:
            setattr(pm, _FIELD[m.datatype], m.value)  # type: ignore[index]
    data: bytes = payload.SerializeToString()
    return data


def decode(data: bytes) -> tuple[Payload, list[Metric]]:
    payload = Payload()
    payload.ParseFromString(data)
    metrics = []
    for pm in payload.metrics:
        field = pm.WhichOneof("value")
        metrics.append(
            Metric(
                name=pm.name if pm.HasField("name") else None,
                alias=pm.alias if pm.HasField("alias") else None,
                datatype=pm.datatype,
                value=None if pm.is_null or field is None else getattr(pm, field),
                timestamp_ms=pm.timestamp if pm.HasField("timestamp") else None,
            )
        )
    return payload, metrics
