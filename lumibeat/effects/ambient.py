"""Ambient scenes: independent of the music, for everyday use."""
from __future__ import annotations

import math

import numpy as np

from .base import Ctx, Effect, Param, fbm, gauss, noise3, register, smoothstep
from .palettes import Palette, build_lut, hex2rgb, kelvin_to_rgb


class AmbientEffect(Effect):
    category = "ambient"
    audio = False
    tags = ("ambient",)


def _shade(col, br):
    return col * np.asarray(br, np.float32)[..., None]


@register
class AmbFireplace(AmbientEffect):
    id = "amb_fireplace"
    name = "Fireplace"
    description = "Simulare naturală de flăcări: bază caldă, limbi care pâlpâie, jar care urcă."
    palette = "fire"
    params = (
        Param("height", "Înălțime flăcări", "float", 0.45, 0.15, 1.0),
        Param("embers", "Jar / scântei", "float", 0.4, 0.0, 1.0),
    )

    def setup(self):
        self.embers = np.zeros((0, 3), np.float32)   # col, y, life

    def render(self, c: Ctx):
        g = self.g
        t = self.t
        cid = g.col_x[:, None] * 11.0
        flick = noise3(cid, t * 0.9, 1.0) * 0.6 + noise3(cid * 3, t * 2.3, 7.0) * 0.4
        h = float(self.p["height"]) * (0.7 + 0.6 * flick)
        tex = fbm(cid * 0.5, g.Y * 4.0 - t * 1.6, t * 0.2, 3)
        heat = 1.0 - g.Y / np.maximum(h, 0.05) + (tex - 0.5) * 0.5
        heat = np.clip(heat, 0, 1) ** 1.2
        out = c.palette.sample(heat * 0.85) * smoothstep(0.0, 0.25, heat)[..., None]
        # embers
        dt = self.scaled_dt(c)
        if self.rng.random() < float(self.p["embers"]) * dt * 6:
            self.embers = np.vstack([self.embers, [[self.rng.integers(0, 12), h.mean() * 0.8, 1.0]]]).astype(np.float32)
        if len(self.embers):
            e = self.embers
            e[:, 1] += dt * 0.12
            e[:, 2] -= dt * 0.35
            e = e[e[:, 2] > 0]
            self.embers = e
            for col, y, life in e:
                w = gauss(g.Y[0] - y, 0.01) * life
                out[int(col)] += w[:, None] * np.array([1.0, 0.45, 0.08], np.float32)
        return out


@register
class WarmWhite(AmbientEffect):
    id = "warm_white"
    name = "Warm White"
    description = "Lumină albă caldă, temperatura de culoare reglabilă."
    palette = "warm"
    params = (Param("gradient", "Gradient de jos în sus", "float", 0.2, 0.0, 1.0),)
    uses_temp = True

    def render(self, c: Ctx):
        g = self.g
        col = np.array(c.tint, np.float32)
        grad = 1.0 - float(self.p["gradient"]) * g.Y * 0.7
        return np.broadcast_to(col, g.shape) * grad[..., None]


@register
class GoldenHour(AmbientEffect):
    id = "golden_hour"
    name = "Golden Hour"
    description = "Gradient chihlimbar–auriu cu o strălucire care se plimbă lent."
    palette = "golden"

    def render(self, c: Ctx):
        g = self.g
        shimmer = 0.85 + 0.15 * noise3(g.X * 3 * g.aspect, g.Y * 2, self.t * 0.15)
        glow = gauss(g.X - (0.5 + 0.4 * math.sin(self.t * 0.03)), 0.35)
        v = 0.25 + 0.55 * (1 - g.Y) + 0.2 * glow
        return _shade(c.palette.sample(v), shimmer * (0.6 + 0.4 * glow))


@register
class NorthernLights(AmbientEffect):
    id = "northern_lights"
    name = "Northern Lights"
    description = "Aurora boreală lentă, verde–turcoaz–violet."
    palette = "aurora"

    def render(self, c: Ctx):
        g = self.g
        t = self.t * 0.5
        x = g.X * 2.5 * g.aspect
        n = fbm(x + t * 0.1, g.Y * 1.0 - t * 0.03, t * 0.05, 4)
        curtain = smoothstep(0.38, 0.72, n)
        rays = 0.65 + 0.35 * noise3(x * 5, t * 0.4, 1.7)
        env = smoothstep(0.0, 0.3, g.Y) * smoothstep(1.05, 0.5, g.Y)
        return _shade(c.palette.sample(n * 0.7 + g.Y * 0.3), curtain * rays * env * 1.1 + 0.03)


@register
class Ocean(AmbientEffect):
    id = "ocean"
    name = "Ocean"
    description = "Valuri albastre care alunecă orizontal, cu reflexii de spumă."
    palette = "ocean"

    def render(self, c: Ctx):
        g = self.g
        t = self.t
        x = g.X * g.aspect
        swell = 0.5 + 0.5 * np.sin(2 * np.pi * (x * 0.8 - t * 0.08) + g.Y * 2.0)
        caustic = fbm(x * 3 + t * 0.15, g.Y * 3 - t * 0.05, t * 0.1, 3)
        foam = smoothstep(0.68, 0.8, caustic) * 0.6
        v = 0.3 + 0.4 * swell * (1 - g.Y * 0.5) + 0.3 * caustic
        out = _shade(c.palette.sample(v * 0.8), 0.35 + 0.65 * v)
        return out + foam[..., None] * np.array([0.6, 0.85, 1.0], np.float32)


@register
class Forest(AmbientEffect):
    id = "forest"
    name = "Forest"
    description = "Verde de pădure cu pete de lumină care trec printre frunze."
    palette = "forest"

    def render(self, c: Ctx):
        g = self.g
        t = self.t
        leaves = fbm(g.X * 4 * g.aspect + t * 0.03, g.Y * 3 + t * 0.02, t * 0.08, 4)
        dapple = smoothstep(0.62, 0.78, noise3(g.X * 6 * g.aspect - t * 0.1, g.Y * 5, t * 0.2))
        base = _shade(c.palette.sample(0.15 + leaves * 0.5), 0.35 + 0.5 * leaves)
        return base + dapple[..., None] * np.array([0.85, 0.95, 0.45], np.float32) * 0.6


@register
class Sunset(AmbientEffect):
    id = "sunset"
    name = "Sunset"
    description = "Cer de apus: violet sus, portocaliu și roșu jos, cu soarele care coboară lent."
    palette = "sunset"

    def render(self, c: Ctx):
        g = self.g
        sun_y = 0.65 - 0.5 * ((self.t * 0.01) % 1.0)
        sun = gauss(g.Y - sun_y, 0.12) * gauss(g.D, 0.6)
        v = (1 - g.Y) * 0.9 + 0.1 * noise3(g.X * 2, g.Y * 2, self.t * 0.05)
        out = _shade(c.palette.sample(v), 0.45 + 0.4 * (1 - g.Y))
        return out + sun[..., None] * np.array([1.0, 0.6, 0.25], np.float32) * 0.7


@register
class Relax(AmbientEffect):
    id = "relax"
    name = "Relax"
    description = "Respirație lentă (6 cicluri/minut) în culori pastelate."
    palette = "candy"
    params = (Param("breaths", "Respirații pe minut", "float", 6.0, 3.0, 12.0),)

    def render(self, c: Ctx):
        g = self.g
        br = 0.25 + 0.75 * (0.5 - 0.5 * math.cos(2 * math.pi * self.t * float(self.p["breaths"]) / 60.0))
        col = c.palette.sample(self.t * 0.01 + g.D * 0.15 + g.Y * 0.05)
        return _shade(col, br * (0.8 + 0.2 * (1 - g.Y)))


@register
class Cinema(AmbientEffect):
    id = "cinema"
    name = "Cinema"
    description = "Iluminare de fundal discretă (bias light), neutră, doar la baza profilelor."
    palette = "mono"
    uses_temp = True

    def render(self, c: Ctx):
        g = self.g
        col = np.array(c.tint, np.float32) * 0.35
        fall = smoothstep(0.45, 0.0, g.Y)
        return np.broadcast_to(col, g.shape) * fall[..., None]


@register
class Night(AmbientEffect):
    id = "night"
    name = "Night Mode"
    description = "Lumină de veghe foarte slabă, chihlimbar, doar jos (nu deranjează somnul)."
    palette = "warm"

    def render(self, c: Ctx):
        g = self.g
        fall = smoothstep(0.18, 0.0, g.Y) * 0.18
        return np.broadcast_to(np.array([1.0, 0.38, 0.06], np.float32), g.shape) * fall[..., None]


@register
class SolidColor(AmbientEffect):
    id = "solid_color"
    name = "Culoare Fixă"
    description = "O singură culoare aleasă de tine (din aplicație sau de pe telefon)."
    palette = "custom"
    params = (Param("gradient", "Gradient de jos în sus", "float", 0.0, 0.0, 1.0),)

    def render(self, c: Ctx):
        g = self.g
        grad = 1.0 - float(self.p["gradient"]) * g.Y * 0.8
        return np.broadcast_to(np.array(c.color, np.float32), g.shape) * grad[..., None]


AMBIENT_ORDER = ["amb_fireplace", "warm_white", "golden_hour", "northern_lights", "ocean", "forest",
                 "sunset", "relax", "cinema", "night", "solid_color"]
