"""Studio: user-built effects made of stacked layers.

A custom effect is a JSON-serialisable spec::

    {"name": "Seara mea", "layers": [
        {"effect": "aurora", "params": {...}, "palette": "aurora", "colors": [],
         "speed": 1.0, "intensity": 1.0, "sensitivity": 1.0,
         "direction": "up", "symmetry": "none", "blend": "add", "opacity": 1.0, "enabled": true}
    ], "transition": {"type": "crossfade", "time": 1.5}}
"""
from __future__ import annotations

import copy
from dataclasses import replace

import numpy as np

from ..core.geometry import Geometry
from .base import REGISTRY, Ctx, Effect, scale_features
from .palettes import Palette

DIRECTIONS = (("up", "Normal (în sus)"), ("down", "Inversat (în jos)"), ("flip_h", "Oglindit orizontal"),
              ("rotate", "Inversat + oglindit"))
SYMMETRIES = (("none", "Fără"), ("mirror_lr", "Stânga → dreapta"), ("mirror_rl", "Dreapta → stânga"),
              ("centre", "Din centru (ambele)"))
BLENDS = (("add", "Adunare"), ("screen", "Screen"), ("max", "Maxim"), ("multiply", "Multiplicare"),
          ("alpha", "Suprapunere"))

DEFAULT_LAYER = {
    "effect": "aurora", "params": {}, "palette": "auto", "colors": [], "speed": 1.0, "intensity": 1.0,
    "sensitivity": 1.0, "direction": "up", "symmetry": "none", "blend": "add", "opacity": 1.0, "enabled": True,
}


def default_spec(name: str = "Efectul meu") -> dict:
    l1 = dict(DEFAULT_LAYER, effect="aurora", palette="aurora")
    l2 = dict(DEFAULT_LAYER, effect="vertical_pulse", palette="neon", opacity=0.8)
    return {"name": name, "layers": [l1, l2], "transition": {"type": "crossfade", "time": 1.5}}


def normalize_spec(spec: dict) -> dict:
    s = copy.deepcopy(spec) if isinstance(spec, dict) else default_spec()
    s.setdefault("name", "Efectul meu")
    layers = []
    for l in s.get("layers", [])[:4]:
        if not isinstance(l, dict):
            continue
        m = dict(DEFAULT_LAYER)
        m.update({k: v for k, v in l.items() if k in DEFAULT_LAYER})
        if m["effect"] not in REGISTRY:
            m["effect"] = "aurora"
        layers.append(m)
    s["layers"] = layers or [dict(DEFAULT_LAYER)]
    tr = s.get("transition") or {}
    s["transition"] = {"type": tr.get("type", "crossfade"), "time": float(tr.get("time", 1.5))}
    return s


def apply_direction(img: np.ndarray, direction: str, g: Geometry) -> np.ndarray:
    order = np.argsort(g.col_x)
    if direction == "down":
        return img[:, ::-1]
    if direction == "flip_h":
        out = np.empty_like(img)
        out[order] = img[order[::-1]]
        return out
    if direction == "rotate":
        out = np.empty_like(img)
        out[order] = img[order[::-1]]
        return out[:, ::-1]
    return img


def apply_symmetry(img: np.ndarray, sym: str, g: Geometry) -> np.ndarray:
    if sym == "none":
        return img
    out = img.copy()
    left = g.side < 0
    right = ~left
    if sym == "mirror_lr":
        out[right] = img[g.mirror[right]]
    elif sym == "mirror_rl":
        out[left] = img[g.mirror[left]]
    elif sym == "centre":
        out = 0.5 * (img + img[g.mirror])
    return out


def blend(dst: np.ndarray, src: np.ndarray, mode: str, opacity: float) -> np.ndarray:
    src = src * opacity if mode in ("add", "screen", "max") else src
    if mode == "add":
        return dst + src
    if mode == "screen":
        a = np.clip(dst, 0, 1)
        b = np.clip(src, 0, 1)
        return 1 - (1 - a) * (1 - b)
    if mode == "max":
        return np.maximum(dst, src)
    if mode == "multiply":
        return dst * (1 - opacity + opacity * np.clip(src, 0, 1.5))
    # alpha: luminance of the layer acts as its mask
    lum = np.clip(src.max(axis=-1, keepdims=True), 0, 1) * opacity
    return dst * (1 - lum) + src * opacity


class LayeredEffect(Effect):
    id = "custom"
    name = "Efect personalizat"
    category = "studio"
    description = "Efect creat în Studio din straturi."
    palette = "custom"

    def __init__(self, g: Geometry, spec: dict, seed: int | None = None):
        self.spec = normalize_spec(spec)
        super().__init__(g, {}, seed)

    def setup(self):
        self.layers = []
        for l in self.spec["layers"]:
            cls = REGISTRY.get(l["effect"])
            if not cls:
                continue
            eff = cls(self.g, l.get("params") or {})
            pal = None
            if l.get("colors"):
                pal = Palette.named("custom", list(l["colors"]))
            elif l.get("palette") and l["palette"] != "auto":
                pal = Palette.named(l["palette"])
            else:
                pal = Palette.named(cls.palette)
            self.layers.append((l, eff, pal))

    @staticmethod
    def structure_key(spec: dict) -> str:
        """Changes to this key need a new instance; anything else is updated live."""
        import json
        s = normalize_spec(spec)
        return json.dumps([(l["effect"], l.get("palette"), list(l.get("colors") or [])) for l in s["layers"]])

    def update_spec(self, spec: dict) -> None:
        s = normalize_spec(spec)
        if len(s["layers"]) != len(self.layers):
            return
        self.spec = s
        new = []
        for l, (_, eff, pal) in zip(s["layers"], self.layers):
            for k, v in (l.get("params") or {}).items():
                if k in eff.p:
                    eff.p[k] = v
            new.append((l, eff, pal))
        self.layers = new

    @property
    def uses_strobe(self) -> bool:
        return any(getattr(e, "strobe", False) for _, e, _ in self.layers)

    def render(self, c: Ctx):
        out = self.zeros()
        for l, eff, pal in self.layers:
            if not l.get("enabled", True):
                continue
            feats = scale_features(c.audio, float(l.get("sensitivity", 1.0)))
            cc = replace(c, palette=pal, audio=feats, intensity=c.intensity * float(l.get("intensity", 1.0)),
                         speed=c.speed * float(l.get("speed", 1.0)))
            img = eff.frame(cc)
            img = apply_direction(img, l.get("direction", "up"), self.g)
            img = apply_symmetry(img, l.get("symmetry", "none"), self.g)
            out = blend(out, img, l.get("blend", "add"), float(l.get("opacity", 1.0)))
        return out
