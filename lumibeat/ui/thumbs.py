"""Effect thumbnails rendered incrementally (a few per timer tick) with synthetic audio."""
from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QObject, QTimer, Signal

from ..audio.analysis import AudioFeatures
from ..core.config import Config
from ..core.geometry import build_geometry
from ..effects import REGISTRY, Ctx, Palette
from .widgets import render_thumb


def synthetic_features(i: int, fps: float = 30.0) -> AudioFeatures:
    t = i / fps
    beat_len = 60 / 124
    ph = (t / beat_len) % 1.0
    env = math.exp(-ph * 5)
    x = np.linspace(0, 1, 32)
    bands = np.clip(0.75 * np.exp(-x * 2.2) * (0.6 + 0.4 * env) + 0.25 * np.abs(np.sin(x * 9 + t * 3)), 0, 1)
    wf = np.sin(np.linspace(0, 6 * np.pi, 64) + t * 5).astype(np.float32) * 0.6
    return AudioFeatures(t=t, level=0.55 + 0.35 * env, level_l=0.6, level_r=0.5, bass=0.4 + 0.55 * env,
                         sub=0.5 * env, lowmid=0.5, mid=0.55, highmid=0.45, high=0.5,
                         bands=bands.astype(np.float32), bands_peak=bands.astype(np.float32), waveform=wf,
                         onset=env, bpm=124.0, bpm_confidence=0.9, beat_phase=ph,
                         beat_count=int(t / beat_len), kick_count=int(t / beat_len), energy=0.6,
                         energy_long=0.5, silent=False)


class ThumbRenderer(QObject):
    ready = Signal(str, object)   # effect id, QImage

    def __init__(self, cfg: Config, ids: list[str], rows: int = 36):
        super().__init__()
        self.g = build_geometry(cfg, rows)
        self.queue = list(ids)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)

    def start(self):
        self.timer.start(15)

    def _tick(self):
        if not self.queue:
            self.timer.stop()
            return
        eid = self.queue.pop(0)
        cls = REGISTRY.get(eid)
        if cls is None:
            return
        try:
            e = cls(self.g, seed=4)
            pal = Palette.named(cls.palette)
            frame = None
            last_b = 0
            n = 75
            for i in range(n):
                f = synthetic_features(i)
                beat = f.beat_count != last_b
                last_b = f.beat_count
                frame = e.frame(Ctx(g=self.g, dt=1 / 30, audio=f, palette=pal, beat=beat, kick=beat,
                                    drop=(i == 20), strobe_ok=False, color=(1.0, 0.55, 0.2),
                                    tint=(1.0, 0.75, 0.5)))
            self.ready.emit(eid, render_thumb(np.clip(frame, 0, 1)))
        except Exception:
            pass
