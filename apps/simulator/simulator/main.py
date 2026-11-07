"""Run the simulated edge node: connect, birth, publish DDATA every interval, honour rebirth."""

import asyncio
import logging
import os
import random

import aiomqtt
from sparkplug import MessageType, decode

from simulator.edge_node import REBIRTH, EdgeNode
from simulator.machines import default_machines

log = logging.getLogger("simulator")


async def publish_births(client: aiomqtt.Client, node: EdgeNode) -> None:
    topic, payload = node.nbirth()
    await client.publish(topic, payload, qos=0)
    for topic, payload in node.dbirths():
        await client.publish(topic, payload, qos=0)
    log.info("published NBIRTH + %d DBIRTH (bdSeq=%d)", len(node.machines), node.bd_seq)


async def listen_for_commands(client: aiomqtt.Client, node: EdgeNode) -> None:
    await client.subscribe(node.topic(MessageType.NCMD), qos=1)
    async for message in client.messages:
        _, metrics = decode(message.payload if isinstance(message.payload, bytes) else b"")
        if any(m.name == REBIRTH and m.value is True for m in metrics):
            log.info("rebirth requested")
            await publish_births(client, node)


async def publish_data(
    client: aiomqtt.Client, node: EdgeNode, interval: float, rng: random.Random
) -> None:
    while True:
        values = [m.sample(rng) for m in node.machines]
        for topic, payload in node.ddata(values):
            await client.publish(topic, payload, qos=0)  # Sparkplug: DATA is QoS 0
        await asyncio.sleep(interval)


async def main() -> None:
    host = os.environ.get("MQTT_HOST", "localhost")
    port = int(os.environ.get("MQTT_PORT", "1883"))
    interval = float(os.environ.get("INTERVAL_S", "1.0"))
    rng = random.Random(os.environ.get("SEED"))
    node = EdgeNode(
        group_id=os.environ.get("GROUP_ID", "BuffaloWorks"),
        edge_node_id=os.environ.get("EDGE_NODE_ID", "edge1"),
        machines=default_machines(spike_prob=float(os.environ.get("SPIKE_PROB", "0.01"))),
    )
    backoff = 1.0
    while True:
        will_topic, will_payload = node.ndeath()
        try:
            async with aiomqtt.Client(
                host,
                port,
                identifier=f"sim-{node.edge_node_id}",
                will=aiomqtt.Will(will_topic, will_payload, qos=1, retain=False),
            ) as client:
                log.info("connected to %s:%d", host, port)
                backoff = 1.0
                await publish_births(client, node)
                async with asyncio.TaskGroup() as tg:
                    tg.create_task(listen_for_commands(client, node))
                    tg.create_task(publish_data(client, node, interval, rng))
        except* aiomqtt.MqttError as eg:
            log.warning("MQTT connection lost (%s); retrying in %.0fs", eg.exceptions[0], backoff)
            node.bd_seq += 1  # new session -> new bdSeq
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)  # exponential backoff, capped


def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(main())


if __name__ == "__main__":
    run()
