import random

from sparkplug import MessageType, Topic, decode

from simulator.edge_node import ASSET_TYPE, REBIRTH, UNIT_PREFIX, EdgeNode
from simulator.machines import default_machines


def make_node() -> EdgeNode:
    return EdgeNode("BuffaloWorks", "edge1", default_machines(spike_prob=0.0))


def test_birth_sequence_and_seq_numbers() -> None:
    node = make_node()
    topic, payload = node.nbirth()
    assert Topic.parse(topic).message_type is MessageType.NBIRTH
    nb, metrics = decode(payload)
    assert nb.seq == 0
    assert {m.name for m in metrics} == {"bdSeq", REBIRTH}
    births = node.dbirths()
    assert [decode(p)[0].seq for _, p in births] == [1, 2, 3]  # seq continues across messages


def test_dbirth_announces_aliases_units_and_type() -> None:
    node = make_node()
    node.nbirth()
    topic, payload = node.dbirths()[0]
    assert Topic.parse(topic).device_id == "laser1"
    _, metrics = decode(payload)
    by_name = {m.name: m for m in metrics}
    assert by_name[ASSET_TYPE].value == "laser"
    assert by_name["power_w"].alias == 100
    assert by_name[UNIT_PREFIX + "power_w"].value == "W"


def test_ddata_uses_aliases_only() -> None:
    node = make_node()
    rng = random.Random(1)
    values = [m.sample(rng) for m in node.machines]
    _, payload = node.ddata(values)[0]
    _, metrics = decode(payload)
    assert all(m.name is None for m in metrics)
    assert [m.alias for m in metrics] == [100, 101]
    assert abs(float(metrics[0].value or 0) - 1000) < 100  # laser power near 1000 W


def test_seq_wraps_at_256() -> None:
    node = make_node()
    node.nbirth()
    seqs = [node.next_seq() for _ in range(300)]
    assert max(seqs) == 255 and seqs[255] == 0


def test_ndeath_carries_bdseq_and_no_seq() -> None:
    node = make_node()
    node.bd_seq = 7
    _, payload = node.ndeath()
    p, (m,) = decode(payload)
    assert not p.HasField("seq") and m.name == "bdSeq" and m.value == 7


def test_press_produces_strokes() -> None:
    press = make_node().machines[1]
    rng = random.Random(0)
    tonnage = [press.sample(rng)[0] for _ in range(8)]
    assert max(tonnage) > 150 and min(tonnage) < 10  # cyclic force, not flat noise
    assert all(t >= 0 for t in tonnage)  # never negative, even with noise
