"""Effect framework: parameters, render context, registry and vectorised helpers."""
from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field, replace
from typing import Any

import numpy as np

from ..audio.analysis import AudioFeatures, NUM_BANDS
from ..core.geometry import Geometry
from .palettes import Palette


@dataclass
class Param:
    key: str
    label: str
    kind: str = "float"          # float | int | bool | choice | color
    default: Any = 1.0
    lo: float = 0.0
    hi: float = 1.0
    choices: tuple = ()          # (value, label) pairs for kind == choice


@dataclass
class Ctx:
    g: Geometry
    dt: float
    audio: AudioFeatures
    palette: Palette
    beat: bool = False           # a tracked beat happened this frame
    kick: bool = False           # a kick drum onset happened this frame
    drop: bool = False           # a bass drop happened this frame
    intensity: float = 1.0       # audio reactivity scale
    speed: float = 1.0           # global speed multiplier
    strobe_ok: bool = False
    color: tuple = (1.0, 0.6, 0.2)
    tint: tuple = (1.0, 1.0, 1.0)
    time: float = 0.0            # wall-clock seconds since engine start

    @property
    def bpm(self) -> float:
        b = self.audio.bpm
        return b if 60 <= b <= 200 else 120.0


REGISTRY: dict[str, type["Effect"]] = {}


def register(cls):
    REGISTRY[cls.id] = cls
    return cls


CATEGORY_LABELS = {
    "music": "Muzică",
    "special": "Speciale perete",
    "ambient": "Ambient",
}


class Effect:
    id = "base"
    name = "Efect"
    category = "music"
    description = ""
    tags: tuple = ()
    palette = "neon"
    audio = True
    strobe = False
    params: tuple = ()

    def __init__(self, g: Geometry, params: dict | None = None, seed: int | None = None):
        self.g = g
        self.p = {pr.key: pr.default for pr in self.all_params()}
        if params:
            for k, v in params.items():
                if k in self.p:
                    self.p[k] = v
        self.t = 0.0
        self.rng = np.random.default_rng(seed)
        self.setup()

    # ------------------------------------------------------------ framework
    @classmethod
    def all_params(cls) -> tuple:
        base = (Param("speed", "Viteză efect", "float", 1.0, 0.1, 3.0),)
        return base + tuple(cls.params)

    def setup(self) -> None:
        pass

    def frame(self, c: Ctx) -> np.ndarray:
        self.t += c.dt * c.speed * float(self.p.get("speed", 1.0))
        out = self.render(c)
        return out

    def render(self, c: Ctx) -> np.ndarray:  # pragma: no cover - abstract
        return self.g.zeros()

    # -------------------------------------------------------------- helpers
    def zeros(self) -> np.ndarray:
        return np.zeros(self.g.shape, np.float32)

    def scaled_dt(self, c: Ctx) -> float:
        return c.dt * c.speed * float(self.p.get("speed", 1.0))


# --------------------------------------------------------------------------- helpers
def clamp01(x):
    return np.clip(x, 0.0, 1.0)


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0 + 1e-9), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def gauss(x, w):
    return np.exp(-(x * x) / (2.0 * w * w + 1e-9))


def hsv(h, s, v) -> np.ndarray:
    h = np.asarray(h, np.float32) % 1.0
    s = np.broadcast_to(np.asarray(s, np.float32), h.shape)
    v = np.broadcast_to(np.asarray(v, np.float32), h.shape)
    i = np.floor(h * 6).astype(np.int32)
    f = h * 6 - i
    p = v * (1 - s)
    q = v * (1 - f * s)
    t = v * (1 - (1 - f) * s)
    i = i % 6
    r = np.choose(i, [v, q, p, p, t, v])
    g = np.choose(i, [t, v, v, q, p, p])
    b = np.choose(i, [p, p, t, v, v, q])
    return np.stack([r, g, b], axis=-1).astype(np.float32)


_rng = np.random.default_rng(1337)
_PERM = np.concatenate([_rng.permutation(256)] * 2).astype(np.int32)
_VALS = _rng.random(256).astype(np.float32)


def _hash3(i, j, k):
    return _VALS[_PERM[(_PERM[(_PERM[i & 255] + j) & 255] + k) & 255]]


def noise3(x, y, z) -> np.ndarray:
    """Smooth value noise in [0,1]."""
    x = np.asarray(x, np.float32)
    y = np.asarray(y, np.float32)
    z = np.asarray(z, np.float32)
    x, y, z = np.broadcast_arrays(x, y, z)
    xi = np.floor(x).astype(np.int32)
    yi = np.floor(y).astype(np.int32)
    zi = np.floor(z).astype(np.int32)
    xf, yf, zf = x - xi, y - yi, z - zi
    u = xf * xf * (3 - 2 * xf)
    v = yf * yf * (3 - 2 * yf)
    w = zf * zf * (3 - 2 * zf)
    c000 = _hash3(xi, yi, zi)
    c100 = _hash3(xi + 1, yi, zi)
    c010 = _hash3(xi, yi + 1, zi)
    c110 = _hash3(xi + 1, yi + 1, zi)
    c001 = _hash3(xi, yi, zi + 1)
    c101 = _hash3(xi + 1, yi, zi + 1)
    c011 = _hash3(xi, yi + 1, zi + 1)
    c111 = _hash3(xi + 1, yi + 1, zi + 1)
    x00 = c000 + (c100 - c000) * u
    x10 = c010 + (c110 - c010) * u
    x01 = c001 + (c101 - c001) * u
    x11 = c011 + (c111 - c011) * u
    y0 = x00 + (x10 - x00) * v
    y1 = x01 + (x11 - x01) * v
    return y0 + (y1 - y0) * w


def fbm(x, y, z, octaves: int = 3) -> np.ndarray:
    total = 0.0
    amp = 0.5
    freq = 1.0
    norm = 0.0
    for _ in range(octaves):
        total = total + noise3(x * freq, y * freq, z * freq) * amp
        norm += amp
        amp *= 0.5
        freq *= 2.0
    return total / norm


def bands_to(bands: np.ndarray, n: int) -> np.ndarray:
    """Group the analyser bands into ``n`` bars (log spaced already)."""
    edges = np.linspace(0, len(bands), n + 1).astype(int)
    return np.array([bands[edges[i]:max(edges[i] + 1, edges[i + 1])].max() for i in range(n)], np.float32)


def column_levels(c: Ctx, symmetric: bool, bands: np.ndarray | None = None) -> np.ndarray:
    """One level per column. symmetric -> bass at the fireplace, treble outermost."""
    b = c.audio.bands if bands is None else bands
    # skip the very top bands (little musical content)
    b = b[: NUM_BANDS - 4]
    if symmetric:
        lv6 = bands_to(b, 6)
        return lv6[c.g.inner]
    lv = bands_to(b, 12)
    order = np.argsort(c.g.col_x)
    out = np.zeros(12, np.float32)
    out[order] = lv
    return out


def boost(x, intensity: float):
    """Apply audio-reactivity intensity to a 0..1 signal."""
    return np.clip(np.asarray(x) * (0.4 + 0.6 * intensity), 0.0, 1.0) if intensity < 1 else \
        np.clip(1 - (1 - np.asarray(x)) ** intensity, 0.0, 1.0)


def scale_features(f: AudioFeatures, k: float) -> AudioFeatures:
    if abs(k - 1.0) < 1e-3:
        return f
    return replace(
        f,
        level=min(1.0, f.level * k), level_l=min(1.0, f.level_l * k), level_r=min(1.0, f.level_r * k),
        bass=min(1.0, f.bass * k), sub=min(1.0, f.sub * k), lowmid=min(1.0, f.lowmid * k),
        mid=min(1.0, f.mid * k), highmid=min(1.0, f.highmid * k), high=min(1.0, f.high * k),
        bands=np.clip(f.bands * k, 0, 1), bands_peak=np.clip(f.bands_peak * k, 0, 1),
        energy=min(1.0, f.energy * k),
    )


def effect_info(cls) -> dict:
    return {
        "id": cls.id,
        "name": cls.name,
        "category": cls.category,
        "description": cls.description,
        "tags": list(cls.tags),
        "palette": cls.palette,
        "audio": cls.audio,
        "strobe": cls.strobe,
        "params": [
            {"key": p.key, "label": p.label, "kind": p.kind, "default": p.default, "lo": p.lo, "hi": p.hi,
             "choices": [list(ch) for ch in p.choices]}
            for p in cls.all_params()
        ],
    }


def deepcopy_params(p: dict) -> dict:
    return copy.deepcopy(p)
