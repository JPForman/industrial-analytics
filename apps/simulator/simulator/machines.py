"""Machine models: each produces realistic-looking metric values per tick."""

import math
import random
from collections.abc import Callable
from dataclasses import dataclass, field

from sparkplug import DataType

Generator = Callable[[int, random.Random], float | int]


@dataclass(frozen=True)
class MetricSpec:
    name: str
    unit: str
    datatype: int
    generate: Generator  # (tick, rng) -> value


@dataclass
class Machine:
    device_id: str
    asset_type: str  # matches the API's AssetType values
    metrics: list[MetricSpec]
    tick: int = field(default=0)

    def sample(self, rng: random.Random) -> list[float | int]:
        values = [m.generate(self.tick, rng) for m in self.metrics]
        self.tick += 1
        return values


def spiky(base: float, noise: float, spike_to: float, spike_prob: float) -> Generator:
    """Gaussian noise around `base`, with a rare spike: the thing alarms exist to catch."""

    def gen(_tick: int, rng: random.Random) -> float:
        if rng.random() < spike_prob:
            return round(spike_to + rng.gauss(0, noise), 2)
        return round(base + rng.gauss(0, noise), 2)

    return gen


def press_stroke(period: int, peak: float) -> Generator:
    """Tonnage near zero, rising to `peak` once per `period` ticks (a stamping stroke)."""

    def gen(tick: int, rng: random.Random) -> float:
        phase = (tick % period) / period
        force = peak * max(0.0, math.sin(phase * 2 * math.pi)) ** 4
        return round(max(0.0, force + rng.gauss(0, peak * 0.01)), 2)  # a press can't pull

    return gen


def counter(every: int) -> Generator:
    def gen(tick: int, _rng: random.Random) -> int:
        return tick // every

    return gen


def default_machines(spike_prob: float) -> list[Machine]:
    return [
        Machine(
            "laser1",
            "laser",
            [
                MetricSpec("power_w", "W", DataType.Double, spiky(1000, 15, 1600, spike_prob)),
                MetricSpec("head_temp_c", "degC", DataType.Double, spiky(35, 0.4, 48, spike_prob)),
            ],
        ),
        Machine(
            "press1",
            "stamping_press",
            [
                MetricSpec("tonnage_t", "t", DataType.Double, press_stroke(period=4, peak=180)),
                MetricSpec("strokes", "count", DataType.Int64, counter(every=4)),
            ],
        ),
        Machine(
            "printer1",
            "printer_3d",
            [
                MetricSpec(
                    "nozzle_temp_c", "degC", DataType.Double, spiky(210, 0.8, 235, spike_prob)
                ),
                MetricSpec("bed_temp_c", "degC", DataType.Double, spiky(60, 0.3, 60, 0)),
                MetricSpec("layer", "count", DataType.Int64, counter(every=10)),
            ],
        ),
    ]
