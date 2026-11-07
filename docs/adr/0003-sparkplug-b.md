# 0003: Sparkplug B over MQTT for machine telemetry

- Status: accepted
- Date: 2026-11-07

## Context
Machines from different vendors must publish telemetry to the platform. Plain MQTT
defines transport only: every vendor picks its own topic names and payload format, so each
integration needs custom parsing, and there is no standard way to know when a device is offline.

## Decision
Use Sparkplug B (Eclipse Sparkplug, v1.0 topic namespace, protobuf payloads) on a Mosquitto broker.
- Topics: `spBv1.0/{group}/{NBIRTH|DBIRTH|DDATA|NDEATH|DDEATH|NCMD}/{edge_node}[/{device}]`.
- BIRTH messages declare metric names, datatypes and aliases; DATA messages send values by alias.
- NDEATH is the MQTT Last Will, carrying `bdSeq` so consumers can ignore deaths from stale sessions.
- `seq` (0-255) lets consumers detect lost messages and request a rebirth via NCMD.
- We vendor a subset of the official `sparkplug_b.proto` with identical field numbers, so payloads
  stay readable by standard tools (e.g. Ignition, Tahu).

## Alternatives
- Plain MQTT + JSON: easiest to read and debug, but no schema, no state/online semantics,
  larger payloads, and every device needs bespoke parsing.
- OPC UA: rich information model and strong in PLC/controls, but client/server polling or a heavier
  pub/sub stack; better as a source the edge node reads from and republishes as Sparkplug.
- HTTP POST from devices: simple, but no broker decoupling, no last-will, poor for constrained links.

## Consequences
- Consumers (the ingestor) must keep per-device alias maps and handle birth/death/rebirth state.
- Payloads are binary, so debugging needs a decoder (see the sniffer approach in the simulator tests).
- The platform can auto-register assets and tags from DBIRTH, with no hand-maintained config.
