"""Subscribe to the ingestor's normalized JSON topics and feed the broadcaster.

The API never decodes Sparkplug: the ingestor already resolved aliases to tag ids and republishes
`ia/v1/live/{tag_id}` (`{tag_id, ts, value}`) and `ia/v1/alarms`. One bridge per API process,
however many browsers are connected.
"""

import asyncio
import json
import logging

import aiomqtt

from app.live import Broadcaster, Event

log = logging.getLogger("api.mqtt_bridge")

LIVE_TOPIC = "ia/v1/live/#"
ALARM_TOPIC = "ia/v1/alarms"
MAX_BACKOFF_S = 30.0


def to_event(topic: str, payload: bytes) -> Event | None:
    """Translate one MQTT message into a client event, or None if it is malformed."""
    try:
        body = json.loads(payload)
    except ValueError:
        return None
    if not isinstance(body, dict):
        return None
    if topic == ALARM_TOPIC:
        return {"type": "alarm", **body}
    if topic.startswith("ia/v1/live/") and {"tag_id", "ts", "value"} <= body.keys():
        return {
            "type": "reading",
            "tag_id": body["tag_id"],
            "ts": body["ts"],
            "value": body["value"],
        }
    return None


async def run_bridge(broadcaster: Broadcaster, host: str, port: int) -> None:
    """Run until cancelled, reconnecting with exponential backoff if the broker goes away."""
    backoff = 1.0
    while True:
        try:
            async with aiomqtt.Client(host, port) as client:
                await client.subscribe(LIVE_TOPIC, qos=0)
                await client.subscribe(ALARM_TOPIC, qos=1)
                log.info("live bridge connected to %s:%d", host, port)
                backoff = 1.0
                async for message in client.messages:
                    if not isinstance(message.payload, bytes):
                        continue
                    event = to_event(message.topic.value, message.payload)
                    if event is None:
                        log.warning("ignoring malformed message on %s", message.topic.value)
                        continue
                    broadcaster.publish(event)
        except aiomqtt.MqttError as exc:
            log.warning("live bridge disconnected (%s); retrying in %.0fs", exc, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF_S)
