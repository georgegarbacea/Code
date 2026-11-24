"""Transitions between two rendered frames."""
from __future__ import annotations

import numpy as np

from ..core.geometry import Geometry

TRANSITIONS = (
    ("crossfade", "Crossfade"),
    ("wipe_out", "Din șemineu spre exterior"),
    ("wipe_up", "De jos în sus"),
    ("dissolve", "Dizolvare"),
    ("fade_black", "Prin negru"),
    ("flash", "Flash alb (drop)"),
)


def _ease(p: float) -> float:
    p = min(1.0, max(0.0, p))
    return p * p * (3 - 2 * p)


class Transition:
    def __init__(self, kind: str, duration: float, g: Geometry, seed: int = 0):
        self.kind = kind if kind in dict(TRANSITIONS) else "crossfade"
        self.duration = max(0.05, float(duration))
        self.g = g
        self.t = 0.0
        self.rand = np.random.default_rng(seed).random((g.cols, g.rows)).astype(np.float32)

    @property
    def done(self) -> bool:
        return self.t >= self.duration

    def step(self, dt: float) -> None:
        self.t += dt

    def mix(self, a: np.ndarray, b: np.ndarray) -> np.ndarray:
        p = _ease(self.t / self.duration)
        g = self.g
        k = self.kind
        if k == "crossfade":
            return a + (b - a) * p
        soft = 0.15
        if k == "wipe_out":
            m = np.clip((p * (1 + soft) - g.D) / soft, 0, 1)[..., None]
            return a * (1 - m) + b * m
        if k == "wipe_up":
            m = np.clip((p * (1 + soft) - g.Y) / soft, 0, 1)[..., None]
            return a * (1 - m) + b * m
        if k == "dissolve":
            m = np.clip((p * 1.2 - self.rand) / 0.2, 0, 1)[..., None]
            return a * (1 - m) + b * m
        if k == "fade_black":
            if p < 0.5:
                return a * (1 - p * 2)
            return b * ((p - 0.5) * 2)
        if k == "flash":
            # short warm-white bloom that hides the cut (one flash, not a strobe)
            bloom = np.exp(-((p - 0.25) ** 2) / 0.01) * 0.8
            base = a if p < 0.25 else b
            return base + bloom * np.array([1.0, 0.95, 0.85], np.float32)
        return b
