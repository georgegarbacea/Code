"""Colour palettes (gradients sampled through 256-entry look-up tables)."""
from __future__ import annotations

import numpy as np


def hex2rgb(h: str) -> tuple[float, float, float]:
    h = h.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        return (int(h[0:2], 16) / 255.0, int(h[2:4], 16) / 255.0, int(h[4:6], 16) / 255.0)
    except (ValueError, IndexError):
        return (1.0, 1.0, 1.0)


def rgb2hex(c) -> str:
    r, g, b = (int(max(0, min(1, v)) * 255 + 0.5) for v in c[:3])
    return f"#{r:02x}{g:02x}{b:02x}"


# name -> (label, [hex stops], cyclic)
PALETTES: dict[str, tuple[str, list[str], bool]] = {
    "neon":      ("Neon", ["#ff00e6", "#7a00ff", "#00d5ff", "#00ffa2", "#ff00e6"], True),
    "rainbow":   ("Curcubeu", ["#ff0000", "#ff8800", "#ffee00", "#00ff44", "#00aaff", "#5500ff", "#ff00aa", "#ff0000"], True),
    "club":      ("Club", ["#ff0055", "#ff00d4", "#2200ff", "#00c8ff", "#ff0055"], True),
    "festival":  ("Festival", ["#ff2a00", "#ffcc00", "#00ff88", "#00b3ff", "#c800ff", "#ff2a00"], True),
    "techno":    ("Techno", ["#0011ff", "#00e5ff", "#ffffff", "#00e5ff", "#0011ff"], True),
    "disco":     ("Disco", ["#ff00a8", "#ffd000", "#00f0ff", "#9d00ff", "#ff00a8"], True),
    "house":     ("House", ["#ff6a00", "#ff0080", "#8a2be2", "#00bfff", "#ff6a00"], True),
    "chill":     ("Chill", ["#1a2a6c", "#2a9d8f", "#8ecae6", "#b388eb", "#1a2a6c"], True),
    "elegant":   ("Elegant", ["#2b1300", "#a0522d", "#ffb347", "#ffe8c2", "#ffb347", "#2b1300"], True),
    "fire":      ("Foc", ["#000000", "#5a0000", "#e01e00", "#ff7a00", "#ffd34d", "#fff6d8"], False),
    "ice":       ("Gheață", ["#000814", "#003566", "#00b4d8", "#caf0f8", "#ffffff"], False),
    "ocean":     ("Ocean", ["#001427", "#003f5c", "#0077b6", "#00b4d8", "#90e0ef", "#003f5c"], True),
    "forest":    ("Pădure", ["#051f0b", "#1b5e20", "#4caf50", "#aed581", "#ffe082", "#1b5e20"], True),
    "aurora":    ("Aurora", ["#00ff9c", "#00c3ff", "#5a00ff", "#c800ff", "#00ff9c"], True),
    "sunset":    ("Apus", ["#2d0b4e", "#8e1e6e", "#ff3d3d", "#ff8c1a", "#ffd166"], False),
    "golden":    ("Golden Hour", ["#3a1500", "#c8641e", "#ffae42", "#ffd98a", "#fff1d0"], False),
    "lava":      ("Lavă", ["#120000", "#7a0000", "#ff2200", "#ff9500", "#7a0000"], True),
    "cyberpunk": ("Cyberpunk", ["#fcee0a", "#ff003c", "#00f0ff", "#711c91", "#fcee0a"], True),
    "vaporwave": ("Vaporwave", ["#ff71ce", "#01cdfe", "#05ffa1", "#b967ff", "#fffb96", "#ff71ce"], True),
    "royal":     ("Regal", ["#1a0033", "#4b0082", "#9b30ff", "#ffd700", "#4b0082"], True),
    "matrix":    ("Matrix", ["#000000", "#003b00", "#00aa22", "#66ff66", "#e0ffe0"], False),
    "candy":     ("Bomboane", ["#ff5e8a", "#ffb3c6", "#a0e7e5", "#b4f8c8", "#fbe7c6", "#ff5e8a"], True),
    "warm":      ("Alb cald", ["#401a00", "#ff9a3c", "#ffd5a0", "#fff4e0"], False),
    "mono":      ("Alb", ["#000000", "#ffffff"], False),
    "custom":    ("Personalizat", ["#7c5cff", "#22d3ee", "#ff4fa3", "#7c5cff"], True),
}

PALETTE_ORDER = list(PALETTES.keys())


def build_lut(stops: list[str], cyclic: bool = False, n: int = 256) -> np.ndarray:
    cols = np.array([hex2rgb(s) for s in stops], dtype=np.float32)
    if len(cols) == 1:
        cols = np.vstack([cols, cols])
    xs = np.linspace(0, 1, len(cols))
    t = np.linspace(0, 1, n)
    lut = np.stack([np.interp(t, xs, cols[:, i]) for i in range(3)], axis=1).astype(np.float32)
    return lut


def single_color_stops(hex_color: str) -> list[str]:
    """Monochrome palette built around one user-picked colour."""
    r, g, b = hex2rgb(hex_color)
    dark = rgb2hex((r * 0.15, g * 0.15, b * 0.15))
    mid = hex_color
    light = rgb2hex((r + (1 - r) * 0.55, g + (1 - g) * 0.55, b + (1 - b) * 0.55))
    return [dark, mid, light, mid, dark]


class Palette:
    """Sampling helper around a LUT; ``sample`` accepts any array of positions."""

    def __init__(self, lut: np.ndarray, cyclic: bool = True):
        self.lut = lut.astype(np.float32)
        self.cyclic = cyclic
        self.n = len(lut)

    @staticmethod
    def named(name: str, custom: list[str] | None = None) -> "Palette":
        if name == "custom" and custom:
            return Palette(build_lut(custom, True), True)
        label, stops, cyc = PALETTES.get(name, PALETTES["neon"])
        return Palette(build_lut(stops, cyc), cyc)

    def sample(self, v) -> np.ndarray:
        v = np.asarray(v, dtype=np.float32)
        if self.cyclic:
            v = v - np.floor(v)
        else:
            v = np.clip(v, 0.0, 1.0)
        idx = (v * (self.n - 1)).astype(np.int32)
        return self.lut[idx]

    def blend(self, other: "Palette", k: float) -> "Palette":
        return Palette(self.lut + (other.lut - self.lut) * float(k), other.cyclic if k > 0.5 else self.cyclic)


def kelvin_to_rgb(k: float) -> tuple[float, float, float]:
    """Approximate black-body colour (Tanner Helland), 1000..12000 K."""
    t = max(1000.0, min(12000.0, k)) / 100.0
    if t <= 66:
        r = 1.0
        g = (99.4708025861 * np.log(t) - 161.1195681661) / 255.0
        b = 0.0 if t <= 19 else (138.5177312231 * np.log(t - 10) - 305.0447927307) / 255.0
    else:
        r = 329.698727446 * ((t - 60) ** -0.1332047592) / 255.0
        g = 288.1221695283 * ((t - 60) ** -0.0755148492) / 255.0
        b = 1.0
    return (float(np.clip(r, 0, 1)), float(np.clip(g, 0, 1)), float(np.clip(b, 0, 1)))
