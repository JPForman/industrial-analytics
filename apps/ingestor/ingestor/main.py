"""Ingestor process: MQTT in, TimescaleDB out, alarms, live republish, graceful shutdown."""

import asyncio
import json
import logging
import os
import signal
import time

import aiomqtt
from sparkplug import DataType, MessageType, Metric, Topic, decode, encode
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ingestor.alarms import load_open_events, load_rules
from ingestor.registry import upsert_device
from ingestor.state import SparkplugState, parse_dbirth
from ingestor.writer import ReadingWriter

log = logging.getLogger("ingestor")

LIVE_PREFIX = "ia/v1/live"  # normalized JSON for the API's WebSocket feed
ALARM_TOPIC = "ia/v1/alarms"
REBIRTH_COOLDOWN_S = 5.0


class Ingestor:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], client: aiomqtt.Client) -> None:
        self.sessions = sessions
        self.client = client
        self.state = SparkplugState()
        self.writer = ReadingWriter(sessions, publish_alarm=self.publish_alarm)
        self._last_rebirth: dict[str, float] = {}

    async def publish_alarm(self, event: dict[str, object]) -> None:
        await self.client.publish(ALARM_TOPIC, json.dumps(event), qos=1)

    async def request_rebirth(self, group: str, edge: str, reason: str | None) -> None:
        now = time.monotonic()
        if now - self._last_rebirth.get(edge, 0) < REBIRTH_COOLDOWN_S:
            return  # rate limit: one request per node per cooldown, not one per message
        self._last_rebirth[edge] = now
        log.info("requesting rebirth from %s: %s", edge, reason)
        payload = encode([Metric("Node Control/Rebirth", None, DataType.Boolean, True)], seq=None)
        await self.client.publish(str(Topic(group, MessageType.NCMD, edge)), payload, qos=1)

    async def handle(self, topic_str: str, data: bytes) -> None:
        try:
            topic = Topic.parse(topic_str)
            payload, metrics = decode(data)
        except Exception:  # bad topic or corrupt protobuf: one bad message must not kill ingest
            log.warning("ignoring undecodable message on %s", topic_str)
            return
        seq = payload.seq if payload.HasField("seq") else None
        edge, device, kind = topic.edge_node_id, topic.device_id, topic.message_type

        if kind is MessageType.NBIRTH:
            self.state.on_nbirth(edge, metrics, seq)
            log.info("NBIRTH %s", edge)
        elif kind is MessageType.NDEATH:
            applied = self.state.on_ndeath(edge, metrics)
            log.info("NDEATH %s (%s)", edge, "offline" if applied else "stale, ignored")
        elif kind is MessageType.DBIRTH and device:
            check = self.state.on_dbirth_seq(edge, seq)
            if check.needs_rebirth:
                await self.request_rebirth(topic.group_id, edge, check.reason)
                return
            async with self.sessions() as session:
                aliases = await upsert_device(session, edge, device, parse_dbirth(metrics))
            self.state.register_device(edge, device, aliases)
            log.info("DBIRTH %s/%s: %d tags", edge, device, len(aliases))
        elif kind is MessageType.DDEATH and device:
            self.state.on_ddeath(edge, device)
        elif kind is MessageType.DDATA and device:
            result = self.state.on_ddata(edge, device, seq, metrics, payload.timestamp or None)
            if result.needs_rebirth:
                await self.request_rebirth(topic.group_id, edge, result.reason)
            self.writer.add(result.rows)
            for row in result.rows:  # live path doesn't wait for the DB write
                msg = {"tag_id": row.tag_id, "ts": row.ts.isoformat(), "value": row.value}
                await self.client.publish(f"{LIVE_PREFIX}/{row.tag_id}", json.dumps(msg), qos=0)

    async def consume(self) -> None:
        async for message in self.client.messages:
            if isinstance(message.payload, bytes):
                await self.handle(message.topic.value, message.payload)

    async def refresh_rules_forever(self, every_s: float) -> None:
        while True:
            try:
                async with self.sessions() as session:
                    self.writer.rules = await load_rules(session)
            except Exception:
                log.exception("rule refresh failed; keeping previous rules")
            await asyncio.sleep(every_s)

    async def flush_forever(self, every_s: float) -> None:
        backoff = every_s
        while True:
            await asyncio.sleep(backoff)
            try:
                while (written := await self.writer.flush()) > 0:
                    log.debug("flushed %d rows", written)
                backoff = every_s
            except Exception:
                backoff = min(backoff * 2, 30)
                log.exception(
                    "flush failed; %d rows buffered, retry in %.0fs", len(self.writer), backoff
                )


async def main() -> None:
    db_url = os.environ.get(
        "DATABASE_URL", "postgresql+asyncpg://industrial:industrial@localhost:5432/industrial"
    )
    host = os.environ.get("MQTT_HOST", "localhost")
    port = int(os.environ.get("MQTT_PORT", "1883"))
    flush_s = float(os.environ.get("FLUSH_INTERVAL_S", "1.0"))
    rules_s = float(os.environ.get("RULE_REFRESH_S", "30"))
    engine = create_async_engine(db_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    backoff = 1.0
    while not stop.is_set():
        try:
            async with aiomqtt.Client(host, port, identifier="ingestor") as client:
                ing = Ingestor(sessions, client)
                async with sessions() as session:
                    ing.writer.open_events = await load_open_events(session)
                await client.subscribe("spBv1.0/#", qos=1)
                log.info("connected to %s:%d, subscribed spBv1.0/#", host, port)
                backoff = 1.0
                tasks = [
                    asyncio.create_task(ing.flush_forever(flush_s)),
                    asyncio.create_task(ing.refresh_rules_forever(rules_s)),
                ]

                consumer = asyncio.create_task(ing.consume())
                stopper = asyncio.create_task(stop.wait())
                done, _ = await asyncio.wait(
                    {consumer, stopper}, return_when=asyncio.FIRST_COMPLETED
                )
                for t in [*tasks, consumer, stopper]:
                    t.cancel()
                # Graceful shutdown: drain the buffer before exiting so nothing is lost.
                while await ing.writer.flush() > 0:
                    pass
                log.info("flushed buffer; %s", "stopping" if stop.is_set() else "reconnecting")
                if consumer in done:
                    consumer.result()  # re-raise MQTT errors to trigger reconnect
        except aiomqtt.MqttError as exc:
            log.warning("MQTT error (%s); reconnecting in %.0fs", exc, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)
    await engine.dispose()


def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(main())


if __name__ == "__main__":
    run()
