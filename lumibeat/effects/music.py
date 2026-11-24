"""Music-reactive effects (MilkDrop-inspired), each a distinct algorithm."""
from __future__ import annotations

import math

import numpy as np
from scipy.ndimage import map_coordinates

from .base import (Ctx, Effect, Param, boost, clamp01, column_levels, fbm, gauss, hsv, noise3, register,
                   smoothstep)


def _shade(pal_vals: np.ndarray, bright) -> np.ndarray:
    return pal_vals * np.asarray(bright, np.float32)[..., None]


# ----------------------------------------------------------------------------- spectrum
@register
class SpectrumAnalyzer(Effect):
    id = "spectrum"
    name = "Spectrum Analyzer"
    description = "12 benzi de frecvență, de la bass (stânga) la înalte (dreapta), cu vârfuri."
    tags = ("groove", "peak", "spectrum")
    palette = "neon"
    params = (
        Param("color_mode", "Culoare după", "choice", "height", choices=(("height", "Înălțime"), ("column", "Coloană"))),
        Param("peaks", "Vârfuri", "bool", True),
        Param("glow", "Strălucire vârf", "float", 0.6, 0.0, 1.0),
    )

    def setup(self):
        self.peaks = np.zeros(12, np.float32)
        self.levels = np.zeros(12, np.float32)

    def levels_for(self, c: Ctx) -> np.ndarray:
        return column_levels(c, symmetric=False)

    def render(self, c: Ctx):
        g = self.g
        lv = boost(self.levels_for(c), c.intensity)
        self.levels = np.where(lv > self.levels, lv, self.levels * 0.9 + lv * 0.1)
        dt = self.scaled_dt(c)
        self.peaks = np.maximum(self.levels, self.peaks - dt * 0.35)
        h = self.levels[:, None]
        lit = smoothstep(h + 0.02, h - 0.02, g.Y)
        if self.p["color_mode"] == "height":
            col = c.palette.sample(g.Y * 0.8 + self.t * 0.02)
        else:
            col = c.palette.sample(g.col_x[:, None] * 0.9 + 0 * g.Y + self.t * 0.03)
        tip = gauss(g.Y - h, 0.04) * float(self.p["glow"])
        out = _shade(col, lit * (0.35 + 0.65 * g.Y / np.maximum(h, 0.05)) + tip)
        if self.p["peaks"]:
            pk = gauss(g.Y - self.peaks[:, None], 0.012)
            out += pk[..., None] * np.array([1.0, 1.0, 1.0], np.float32) * 0.9
        return out


@register
class SpectrumSymmetric(SpectrumAnalyzer):
    id = "spectrum_sym"
    name = "Spectrum Simetric"
    description = "Bass lângă șemineu, înaltele spre exterior, oglindit stânga–dreapta."
    palette = "club"

    def levels_for(self, c: Ctx):
        return column_levels(c, symmetric=True)

    def render(self, c: Ctx):
        out = super().render(c)
        # gentle colour drift outward from the fireplace
        shift = c.palette.sample(self.g.D * 0.35 - self.t * 0.05)
        return out * 0.7 + out * shift * 0.6


@register
class BassPulse(Effect):
    id = "bass_pulse"
    name = "Bass Pulse"
    description = "Tot peretele pulsează pe bass, cu flash pe fiecare kick."
    tags = ("groove", "peak", "calm")
    palette = "club"
    params = (Param("base", "Lumină de fond", "float", 0.08, 0.0, 0.5),)

    def setup(self):
        self.flash = 0.0

    def render(self, c: Ctx):
        g = self.g
        if c.kick:
            self.flash = 1.0
        self.flash *= math.exp(-c.dt * 7.0)
        b = float(boost(c.audio.bass, c.intensity)) ** 1.4
        lvl = float(self.p["base"]) + 0.75 * b + 0.35 * self.flash
        col = c.palette.sample(self.t * 0.05 + g.Y * 0.25 + g.D * 0.15)
        vert = 0.65 + 0.35 * (1 - g.Y) ** 0.5
        return _shade(col, np.clip(lvl * vert, 0, 1.2))


@register
class Aurora(Effect):
    id = "aurora"
    name = "Aurora Borealis"
    description = "Cortine de lumină care curg, modulate de frecvențele medii."
    tags = ("calm", "groove")
    palette = "aurora"
    audio = True
    params = (Param("rays", "Raze verticale", "float", 0.7, 0.0, 1.0),)

    def render(self, c: Ctx):
        g = self.g
        t = self.t
        x = g.X * 3.0 * g.aspect
        n = fbm(x + t * 0.12, g.Y * 1.2 - t * 0.05, t * 0.07, 3)
        curtain = smoothstep(0.35, 0.75, n)
        rays = 0.6 + 0.4 * noise3(x * 4.0, t * 0.6, 3.3) * float(self.p["rays"])
        env = smoothstep(0.0, 0.25, g.Y) * smoothstep(1.05, 0.55, g.Y)
        a = c.audio
        drive = 0.45 + 0.55 * float(boost(0.6 * a.mid + 0.4 * a.level, c.intensity))
        col = c.palette.sample(n * 0.8 + g.Y * 0.35 + t * 0.02)
        return _shade(col, curtain * rays * env * drive * 1.25)


@register
class Plasma(Effect):
    id = "plasma"
    name = "Plasma"
    description = "Plasmă clasică demoscene, accelerată de energie."
    tags = ("calm", "groove", "retro")
    palette = "vaporwave"
    params = (Param("scale", "Scară", "float", 1.0, 0.3, 3.0),)

    def setup(self):
        self.phase = 0.0

    def render(self, c: Ctx):
        g = self.g
        s = float(self.p["scale"])
        self.phase += self.scaled_dt(c) * (0.6 + 1.6 * c.audio.energy)
        t = self.phase
        x = g.X * g.aspect * 6 * s
        y = g.Y * 6 * s
        v = (np.sin(x + t) + np.sin(y * 0.8 + t * 1.3) + np.sin((x + y) * 0.6 + t * 0.7)
             + np.sin(np.sqrt((x - 3 * s) ** 2 + (y - 3 * s) ** 2) + t * 1.1))
        col = c.palette.sample(v / 8.0 + 0.5 + t * 0.03)
        br = 0.55 + 0.45 * float(boost(c.audio.level, c.intensity))
        return _shade(col, br)


@register
class RainbowWaves(Effect):
    id = "rainbow_waves"
    name = "Rainbow Waves"
    description = "Valuri de curcubeu care urcă în ritmul piesei."
    tags = ("groove", "peak")
    palette = "rainbow"
    params = (Param("waves", "Număr valuri", "float", 2.0, 0.5, 6.0),)

    def render(self, c: Ctx):
        g = self.g
        k = float(self.p["waves"])
        ph = g.Y * k - self.t * c.bpm / 120.0 + g.X * 0.6
        hue = c.palette.sample(g.X * 0.5 + g.Y * 0.3 - self.t * 0.1)
        wave = 0.35 + 0.65 * (0.5 + 0.5 * np.sin(2 * np.pi * ph)) ** 2
        lvl = 0.5 + 0.5 * float(boost(c.audio.level, c.intensity))
        return _shade(hue, wave * lvl)


@register
class Fire(Effect):
    id = "fire"
    name = "Fire"
    description = "Simulare de foc pe fiecare profil (difuzie termică), alimentată de bass."
    tags = ("groove", "warm", "peak")
    palette = "fire"
    params = (
        Param("cooling", "Răcire", "float", 0.55, 0.2, 1.0),
        Param("sparking", "Scântei", "float", 0.6, 0.1, 1.0),
    )

    def setup(self):
        self.heat = np.zeros((12, self.g.rows), np.float32)
        self.acc = 0.0

    def step(self, c: Ctx):
        H = self.g.rows
        cool = float(self.p["cooling"]) * 2.2 / max(8, H) * 10
        self.heat -= self.rng.random(self.heat.shape).astype(np.float32) * cool * 0.12
        np.clip(self.heat, 0, 1, out=self.heat)
        h = self.heat
        up = h.copy()
        up[:, 2:] = (h[:, 1:-1] + h[:, :-2] * 2) / 3.0
        up[:, 1] = (h[:, 0] + h[:, 1]) / 2.0
        self.heat = up
        drive = float(boost(c.audio.bass * 0.7 + c.audio.level * 0.3, c.intensity))
        spark_p = float(self.p["sparking"]) * (0.25 + 0.75 * drive)
        n = max(2, H // 10)
        for col in range(12):
            if self.rng.random() < spark_p:
                y = self.rng.integers(0, n)
                self.heat[col, y] = min(1.0, self.heat[col, y] + 0.5 + 0.5 * self.rng.random())
        if c.kick:
            self.heat[:, :n] = np.maximum(self.heat[:, :n], 0.9)

    def render(self, c: Ctx):
        self.acc += self.scaled_dt(c) * 60.0
        steps = 0
        while self.acc >= 1.0 and steps < 4:
            self.step(c)
            self.acc -= 1.0
            steps += 1
        return c.palette.sample(self.heat * 0.95) * smoothstep(0.0, 0.15, self.heat)[..., None]


@register
class Waterfall(Effect):
    id = "waterfall"
    name = "Waterfall"
    description = "Spectrogramă în cascadă: spectrul curge de sus în jos."
    tags = ("groove", "spectrum")
    palette = "ice"
    params = (
        Param("symmetric", "Simetric", "bool", True),
        Param("rate", "Viteză curgere", "float", 1.0, 0.2, 3.0),
    )

    def setup(self):
        self.hist = np.zeros((12, self.g.rows), np.float32)
        self.acc = 0.0

    def render(self, c: Ctx):
        lv = boost(column_levels(c, bool(self.p["symmetric"])), c.intensity)
        self.acc += self.scaled_dt(c) * float(self.p["rate"]) * self.g.rows * 0.9
        n = int(self.acc)
        if n > 0:
            self.acc -= n
            n = min(n, self.g.rows)
            self.hist[:, :-n] = self.hist[:, n:]
            self.hist[:, -n:] = lv[:, None]
        else:
            self.hist[:, -1] = np.maximum(self.hist[:, -1], lv)
        v = self.hist
        return _shade(c.palette.sample(v * 0.9 + 0.05), np.clip(v * 1.2, 0, 1))


@register
class MeteorShower(Effect):
    id = "meteor_shower"
    name = "Meteor Shower"
    description = "Meteoriți cu coadă care cad pe profile, mai mulți pe kick."
    tags = ("groove", "peak", "particles")
    palette = "ice"
    params = (
        Param("density", "Densitate", "float", 0.5, 0.05, 1.0),
        Param("trail", "Coadă", "float", 0.85, 0.5, 0.97),
    )

    def setup(self):
        self.buf = self.zeros()
        self.m: list[list[float]] = []   # col, y, speed, hue

    def render(self, c: Ctx):
        dt = self.scaled_dt(c)
        rate = float(self.p["density"]) * (0.6 + 3.0 * c.audio.energy)
        if self.rng.random() < rate * dt * 4:
            self.m.append([self.rng.integers(0, 12), 1.05, 0.6 + self.rng.random() * 0.8, self.rng.random()])
        if c.kick:
            for _ in range(2 + int(3 * c.intensity)):
                self.m.append([self.rng.integers(0, 12), 1.05, 0.9 + self.rng.random(), self.rng.random()])
        decay = float(self.p["trail"]) ** (dt * 60)
        self.buf *= decay * (0.9 + 0.1 * self.rng.random(self.buf.shape[:2]).astype(np.float32))[..., None]
        H = self.g.rows
        alive = []
        for mt in self.m:
            mt[1] -= mt[2] * dt * (c.bpm / 120.0)
            if mt[1] < -0.1:
                continue
            col = int(mt[0])
            y = mt[1] * H
            idx = np.arange(H)
            head = gauss(idx - y, 1.0)
            color = c.palette.sample(mt[3])
            self.buf[col] = np.maximum(self.buf[col], head[:, None] * (0.6 * color + 0.4))
            alive.append(mt)
        self.m = alive[-80:]
        return self.buf


@register
class DigitalRain(Effect):
    id = "digital_rain"
    name = "Digital Rain"
    description = "Ploaie digitală în stil cod verde, cu viteza dată de înalte."
    tags = ("groove", "geometric", "calm")
    palette = "matrix"
    params = (Param("density", "Densitate", "float", 0.5, 0.1, 1.0),)

    def setup(self):
        self.buf = np.zeros((12, self.g.rows), np.float32)
        self.drops: list[list[float]] = []
        self.glyph = self.rng.random((12, self.g.rows)).astype(np.float32)

    def render(self, c: Ctx):
        dt = self.scaled_dt(c)
        H = self.g.rows
        rate = float(self.p["density"]) * (1.0 + 4.0 * c.audio.high + 2 * c.audio.level)
        for col in range(12):
            if self.rng.random() < rate * dt * 0.8:
                self.drops.append([col, H + 1.0, (8 + self.rng.random() * 18) * (H / 60.0)])
        self.buf *= 0.9 ** (dt * 60)
        nxt = []
        for d in self.drops:
            d[1] -= d[2] * dt * (0.8 + c.audio.high)
            yi = int(d[1])
            if yi < 0:
                continue
            if yi < H:
                self.buf[d[0], yi] = 1.0
            nxt.append(d)
        self.drops = nxt[-200:]
        if self.rng.random() < 0.3:
            self.glyph = np.where(self.rng.random(self.glyph.shape) < 0.05, self.rng.random(self.glyph.shape),
                                  self.glyph).astype(np.float32)
        v = self.buf * (0.6 + 0.4 * self.glyph)
        col = c.palette.sample(v)
        head = (self.buf > 0.97).astype(np.float32)[..., None]
        return col * (1 - head) + head * np.array([0.8, 1.0, 0.85], np.float32)


@register
class BeatRipple(Effect):
    id = "beat_ripple"
    name = "Beat Ripple"
    description = "Inele concentrice pornesc din șemineu la fiecare bătaie."
    tags = ("groove", "peak")
    palette = "neon"
    params = (Param("width", "Grosime inel", "float", 0.06, 0.02, 0.2),)

    def setup(self):
        self.rings: list[list[float]] = []
        self.hue = 0.0

    def render(self, c: Ctx):
        dt = self.scaled_dt(c)
        if c.beat or (c.kick and not self.rings):
            self.hue += 0.13
            self.rings.append([0.0, 1.0 * (0.5 + 0.5 * c.intensity), self.hue])
        out = self.zeros()
        speed = 0.55 * c.bpm / 120.0
        keep = []
        w = float(self.p["width"])
        for r in self.rings:
            r[0] += speed * dt
            r[1] *= math.exp(-dt * 1.2)
            if r[0] > 1.3 or r[1] < 0.02:
                continue
            ring = gauss(self.g.R - r[0], w) * r[1]
            out += c.palette.sample(r[2] + self.g.R * 0.2) * ring[..., None]
            keep.append(r)
        self.rings = keep[-12:]
        out += c.palette.sample(self.hue)[None, None, :] * 0.04
        return out


@register
class CenterExplosion(Effect):
    id = "center_explosion"
    name = "Center Explosion"
    description = "Artificii: o rachetă urcă lângă șemineu și explodează în scântei care cad."
    tags = ("peak", "particles")
    palette = "festival"
    params = (Param("sparks", "Scântei", "int", 70, 20, 160),)

    def setup(self):
        self.parts = np.zeros((0, 6), np.float32)   # x, y, vx, vy, life, hue
        self.rocket: list[float] | None = None
        self.buf = self.zeros()
        self.cool = 0.0

    def render(self, c: Ctx):
        g = self.g
        dt = self.scaled_dt(c)
        self.cool -= dt
        launch = c.drop or (c.beat and self.cool <= 0 and c.audio.energy > 0.3)
        if launch and self.rocket is None:
            # the rocket climbs the two profiles next to the fireplace
            self.rocket = [0.0, 1.0 + 0.5 * self.rng.random(), self.rng.random()]
            self.cool = 4 * 60.0 / c.bpm
        self.buf *= 0.86 ** (dt * 60)
        if self.rocket:
            rk = self.rocket
            rk[0] += rk[1] * dt
            trail = gauss(g.Y - rk[0], 0.02) + 0.4 * np.clip(1 - (rk[0] - g.Y) * 6, 0, 1) * (g.Y < rk[0])
            mask = (g.inner[:, None] == 0)
            self.buf += (trail * mask)[..., None] * np.array([1, 0.8, 0.5], np.float32)
            if rk[0] > 0.6 + 0.2 * self.rng.random():
                n = int(self.p["sparks"])
                ang = self.rng.random(n) * 2 * np.pi
                sp = 0.25 + self.rng.random(n) * 0.5
                new = np.stack([np.full(n, g.centre_x), np.full(n, rk[0]), np.cos(ang) * sp * 0.6,
                                np.sin(ang) * sp * 0.5, np.full(n, 1.0), rk[2] + self.rng.random(n) * 0.15], 1)
                self.parts = np.vstack([self.parts, new.astype(np.float32)])[-400:]
                self.rocket = None
        if len(self.parts):
            p = self.parts
            p[:, 0] += p[:, 2] * dt
            p[:, 1] += p[:, 3] * dt
            p[:, 3] -= 0.35 * dt
            p[:, 2] *= 0.995
            p[:, 4] -= dt * 0.6
            p = p[p[:, 4] > 0]
            self.parts = p
            cols = c.palette.sample(p[:, 5])
            wx = np.exp(-((g.col_x[:, None] - p[None, :, 0]) ** 2) / (2 * 0.03 ** 2))      # (C, n)
            wy = np.exp(-((g.Y[0][:, None] - p[None, :, 1]) ** 2) / (2 * 0.018 ** 2))      # (H, n)
            wgt = (wx[:, None, :] * wy[None, :, :] * p[None, None, :, 4]).astype(np.float32)
            self.buf += np.einsum("chn,nk->chk", wgt, cols)
        return np.clip(self.buf, 0, 1.5)


@register
class Particles(Effect):
    id = "particles"
    name = "Particles"
    description = "Particule care țâșnesc de jos pe bass și cad sub gravitație."
    tags = ("groove", "peak", "particles")
    palette = "cyberpunk"
    params = (Param("amount", "Cantitate", "float", 0.6, 0.1, 1.0),)

    def setup(self):
        self.p_ = np.zeros((0, 5), np.float32)   # col, y, vy, life, hue
        self.buf = self.zeros()

    def render(self, c: Ctx):
        dt = self.scaled_dt(c)
        g = self.g
        n_new = 0
        if c.kick:
            n_new += int(6 + 14 * float(self.p["amount"]) * c.intensity)
        if self.rng.random() < dt * 8 * float(self.p["amount"]) * (0.3 + c.audio.level):
            n_new += 1
        if n_new:
            new = np.stack([self.rng.integers(0, 12, n_new).astype(np.float32), np.zeros(n_new),
                            0.6 + self.rng.random(n_new) * (0.6 + 0.8 * c.audio.bass),
                            np.ones(n_new), self.rng.random(n_new)], 1).astype(np.float32)
            self.p_ = np.vstack([self.p_, new])[-300:]
        self.buf *= 0.8 ** (dt * 60)
        if len(self.p_):
            p = self.p_
            p[:, 1] += p[:, 2] * dt
            p[:, 2] -= 0.9 * dt
            p[:, 3] -= dt * 0.5
            p = p[(p[:, 3] > 0) & (p[:, 1] > -0.05)]
            self.p_ = p
            cols = c.palette.sample(p[:, 4] + self.t * 0.05)
            yy = g.Y[0][None, :]
            for k in range(len(p)):
                ci = int(p[k, 0])
                w = gauss(yy[0] - p[k, 1], 0.015) * p[k, 3]
                self.buf[ci] += w[:, None] * cols[k]
        return np.clip(self.buf, 0, 1.4)


@register
class FrequencyWaves(Effect):
    id = "freq_waves"
    name = "Frequency Waves"
    description = "Trei unde sinusoidale (bass, medii, înalte) care se suprapun."
    tags = ("calm", "groove")
    palette = "neon"
    params = (Param("thickness", "Grosime", "float", 0.05, 0.02, 0.15),)

    def render(self, c: Ctx):
        g = self.g
        a = c.audio
        out = self.zeros()
        th = float(self.p["thickness"])
        x = g.X * g.aspect
        specs = ((a.bass, 1.2, 0.6, 0.0), (a.mid, 2.3, 1.1, 0.33), (a.high, 3.7, 1.9, 0.66))
        for lvl, k, f, hue in specs:
            amp = 0.06 + 0.34 * float(boost(lvl, c.intensity))
            y0 = 0.5 + amp * np.sin(2 * np.pi * (x * k * 0.5 - self.t * f * 0.5))
            line = gauss(g.Y - y0, th)
            out += c.palette.sample(hue + self.t * 0.02)[None, None, :] * line[..., None]
        return out


@register
class VUStereo(Effect):
    id = "vu_stereo"
    name = "VU Stereo"
    description = "VU-metru stereo: canalul stâng pe stânga, dreptul pe dreapta."
    tags = ("groove", "peak", "spectrum")
    palette = "matrix"
    params = ()

    def setup(self):
        self.pk = np.zeros(2, np.float32)

    def render(self, c: Ctx):
        g = self.g
        a = c.audio
        lv = np.array([a.level_l, a.level_r], np.float32)
        lv = boost(lv, c.intensity)
        self.pk = np.maximum(lv, self.pk - self.scaled_dt(c) * 0.4)
        side = (g.side > 0).astype(int)
        h = lv[side][:, None] * (1.0 - 0.06 * g.inner[:, None])
        lit = smoothstep(h + 0.015, h - 0.015, g.Y)
        # classic green -> yellow -> red by height
        col = hsv(0.33 - 0.33 * g.Y, 1.0, 1.0)
        out = col * lit[..., None]
        pk = gauss(g.Y - self.pk[side][:, None], 0.012)
        return out + pk[..., None] * 0.9


@register
class Oscilloscope(Effect):
    id = "oscilloscope"
    name = "Osciloscop"
    description = "Forma de undă a sunetului desenată peste cele 12 profile, cu persistență."
    tags = ("groove", "geometric")
    palette = "techno"
    params = (Param("persist", "Persistență", "float", 0.8, 0.3, 0.95),)

    def setup(self):
        self.buf = self.zeros()

    def render(self, c: Ctx):
        g = self.g
        wf = c.audio.waveform
        xs = np.linspace(0, 1, len(wf))
        w = np.interp(g.col_x, xs, wf) * (0.4 + 0.6 * c.intensity)
        y0 = 0.5 + 0.45 * np.clip(w, -1, 1)
        line = gauss(g.Y - y0[:, None], 0.025)
        self.buf *= float(self.p["persist"]) ** (self.scaled_dt(c) * 60)
        col = c.palette.sample(g.col_x[:, None] * 0.3 + self.t * 0.05 + 0 * g.Y)
        self.buf = np.maximum(self.buf, col * line[..., None])
        return self.buf


@register
class FeedbackWarp(Effect):
    id = "feedback_warp"
    name = "MilkDrop Warp"
    description = "Buclă de feedback cu zoom și rotație (ca MilkDrop) în care se injectează spectrul."
    tags = ("groove", "peak", "cinematic")
    palette = "vaporwave"
    params = (
        Param("zoom", "Zoom", "float", 0.96, 0.85, 1.05),
        Param("rotation", "Rotație", "float", 0.02, -0.15, 0.15),
        Param("decay", "Persistență", "float", 0.93, 0.8, 0.99),
    )

    def setup(self):
        self.buf = self.zeros()
        C, H = 12, self.g.rows
        cy, cx = np.meshgrid(np.arange(H, dtype=np.float32), np.arange(C, dtype=np.float32))
        self.cx, self.cy = cx, cy

    def render(self, c: Ctx):
        g = self.g
        C, H = 12, g.rows
        dt = self.scaled_dt(c)
        zoom = float(self.p["zoom"]) - 0.05 * c.audio.bass * c.intensity
        rot = float(self.p["rotation"]) * (1 + 2 * c.audio.mid) + 0.02 * math.sin(self.t * 0.3)
        # work in a physical-aspect space so rotation looks round
        ax = 1.0 / C
        ay = 1.0 / H / max(0.2, g.aspect)
        ox, oy = (C - 1) / 2.0, g.centre_y * (H - 1)
        dx = (self.cx - ox) * ax
        dy = (self.cy - oy) * ay
        k = zoom ** (dt * 60)
        a = rot * dt * 60 * 0.2
        ca, sa = math.cos(a), math.sin(a)
        sx = (dx * ca - dy * sa) * k / ax + ox
        sy = (dx * sa + dy * ca) * k / ay + oy
        dec = float(self.p["decay"]) ** (dt * 60)
        warped = np.empty_like(self.buf)
        for ch in range(3):
            warped[..., ch] = map_coordinates(self.buf[..., ch], [sx, sy], order=1, mode="constant", cval=0.0)
        self.buf = warped * dec
        # inject: spectrum bars around the fireplace + beat sparks
        lv = column_levels(c, True)
        inj = gauss(g.Y - (g.centre_y + (lv[:, None] - 0.5) * 0.4), 0.03) * lv[:, None]
        col = c.palette.sample(self.t * 0.07 + g.D * 0.3)
        self.buf += col * inj[..., None] * 0.6
        if c.beat:
            ci = self.rng.integers(0, C)
            yi = self.rng.integers(0, H)
            self.buf[ci, max(0, yi - 2):yi + 3] += c.palette.sample(self.rng.random()) * 1.2
        return np.clip(self.buf, 0, 1.5)


@register
class Tunnel(Effect):
    id = "tunnel"
    name = "Tunel Hiperspațial"
    description = "Inele care zboară din șemineu spre tine, cu dungi în spirală."
    tags = ("peak", "geometric", "cinematic")
    palette = "techno"
    params = (Param("stripes", "Dungi", "int", 6, 0, 12),)

    def setup(self):
        self.z = 0.0

    def render(self, c: Ctx):
        g = self.g
        self.z += self.scaled_dt(c) * (0.6 + 1.4 * c.audio.energy) * c.bpm / 120.0
        r = g.R + 0.04
        depth = np.log(r) * 2.5 - self.z
        rings = 0.5 + 0.5 * np.cos(2 * np.pi * depth)
        rings = rings ** 3
        st = int(self.p["stripes"])
        stripes = (0.6 + 0.4 * np.cos(g.A * st + self.z * 2)) if st else 1.0
        col = c.palette.sample(depth * 0.25)
        br = rings * stripes * smoothstep(0.0, 0.25, g.R) * (0.5 + 0.5 * float(boost(c.audio.level, c.intensity)))
        return _shade(col, br)


@register
class LavaLamp(Effect):
    id = "lava"
    name = "Lava Lamp"
    description = "Metabile care plutesc lent și pulsează pe bass."
    tags = ("calm", "retro", "warm")
    palette = "lava"
    params = (Param("blobs", "Bule", "int", 6, 3, 10),)

    def setup(self):
        n = 10
        self.ph = self.rng.random((n, 4)).astype(np.float32) * 6.28

    def render(self, c: Ctx):
        g = self.g
        n = int(self.p["blobs"])
        t = self.t * 0.35
        f = np.zeros((12, g.rows), np.float32)
        x = g.X * g.aspect
        for i in range(n):
            p = self.ph[i]
            bx = (0.5 + 0.45 * math.sin(t * 0.7 + p[0])) * g.aspect
            by = 0.5 + 0.45 * math.sin(t * (0.5 + 0.1 * i) + p[1])
            r = 0.12 + 0.04 * math.sin(t + p[2]) + 0.05 * c.audio.bass * c.intensity
            f += r * r / ((x - bx) ** 2 + (g.Y - by) ** 2 + 1e-3)
        v = smoothstep(0.6, 1.6, f)
        col = c.palette.sample(0.35 + 0.5 * v + self.t * 0.01)
        return _shade(col, 0.12 + 0.88 * v)


@register
class Kaleidoscope(Effect):
    id = "kaleidoscope"
    name = "Caleidoscop"
    description = "Model oglindit radial în jurul șemineului."
    tags = ("groove", "geometric")
    palette = "candy"
    params = (Param("segments", "Segmente", "int", 6, 3, 12),)

    def render(self, c: Ctx):
        g = self.g
        n = int(self.p["segments"])
        seg = 2 * np.pi / n
        a = np.abs(((g.A + self.t * 0.2) % seg) - seg / 2)
        r = g.R
        v = np.sin(r * 12 - self.t * 2) * np.cos(a * 7 + self.t) + noise3(r * 4, a * 3, self.t * 0.3)
        col = c.palette.sample(v * 0.4 + r * 0.5 + self.t * 0.05)
        br = 0.4 + 0.6 * smoothstep(-0.2, 0.9, v) * (0.5 + 0.5 * float(boost(c.audio.level, c.intensity)))
        return _shade(col, br)


@register
class Bounce(Effect):
    id = "bounce"
    name = "Bile Săltărețe"
    description = "O bilă pe fiecare profil, aruncată în sus de kick-uri."
    tags = ("groove", "retro")
    palette = "rainbow"
    params = (Param("gravity", "Gravitație", "float", 1.6, 0.5, 4.0),)

    def setup(self):
        self.y = np.zeros(12, np.float32)
        self.v = np.zeros(12, np.float32)
        self.buf = self.zeros()

    def render(self, c: Ctx):
        dt = self.scaled_dt(c)
        if c.kick or c.beat:
            k = self.rng.random(12) < 0.5 + 0.4 * c.intensity
            lv = column_levels(c, True)
            self.v = np.where(k, np.maximum(self.v, 0.6 + 1.2 * lv), self.v)
        self.v -= float(self.p["gravity"]) * dt
        self.y += self.v * dt
        hit = self.y < 0
        self.y[hit] = 0
        self.v[hit] = -self.v[hit] * 0.45
        self.buf *= 0.75 ** (dt * 60)
        g = self.g
        ball = gauss(g.Y - self.y[:, None], 0.02)
        col = c.palette.sample(g.col_x[:, None] + 0 * g.Y + self.t * 0.03)
        self.buf = np.maximum(self.buf, col * ball[..., None])
        return self.buf


@register
class Scanner(Effect):
    id = "scanner"
    name = "Scanner Larson"
    description = "Un fascicul care baleiază peretele stânga–dreapta în tempo."
    tags = ("groove", "retro", "build")
    palette = "lava"
    params = (
        Param("mode", "Direcție", "choice", "horizontal",
              choices=(("horizontal", "Orizontal"), ("vertical", "Vertical"), ("both", "Ambele"))),
        Param("width", "Lățime", "float", 0.08, 0.03, 0.3),
    )

    def setup(self):
        self.buf = self.zeros()

    def render(self, c: Ctx):
        g = self.g
        dt = self.scaled_dt(c)
        period = 2 * 60.0 / c.bpm * 2      # one sweep every 2 beats
        ph = (self.t / period) % 2.0
        pos = ph if ph < 1 else 2 - ph
        w = float(self.p["width"])
        mode = self.p["mode"]
        if mode == "horizontal":
            f = gauss(g.X - pos, w)
        elif mode == "vertical":
            f = gauss(g.Y - pos, w)
        else:
            f = np.maximum(gauss(g.X - pos, w), gauss(g.Y - (1 - pos), w))
        self.buf *= 0.85 ** (dt * 60)
        col = c.palette.sample(0.6 + 0.2 * f)
        self.buf = np.maximum(self.buf, col * f[..., None] * (0.6 + 0.4 * c.audio.level + 0.2))
        return self.buf


@register
class Twinkle(Effect):
    id = "twinkle"
    name = "Stele Sclipitoare"
    description = "Pixeli care sclipesc aleator; înaltele aprind mai multe stele."
    tags = ("calm",)
    palette = "royal"
    params = (Param("density", "Densitate", "float", 0.35, 0.05, 1.0),)

    def setup(self):
        shp = (12, self.g.rows)
        self.ph = self.rng.random(shp).astype(np.float32)
        self.rate = (0.3 + self.rng.random(shp) * 1.2).astype(np.float32)
        self.hue = self.rng.random(shp).astype(np.float32)

    def render(self, c: Ctx):
        dens = float(self.p["density"]) * (0.6 + 1.2 * c.audio.high * c.intensity)
        self.ph += self.rate * self.scaled_dt(c) * 0.5
        wrap = self.ph >= 1
        if wrap.any():
            self.ph[wrap] -= 1
            self.hue[wrap] = self.rng.random(int(wrap.sum()))
        star = np.sin(np.pi * self.ph) ** 8
        mask = (self.hue < dens).astype(np.float32)
        col = c.palette.sample(self.hue * 3)
        return col * (star * mask)[..., None] + col * 0.03


@register
class CometChase(Effect):
    id = "comet_chase"
    name = "Comete"
    description = "Comete care parcurg profilele în serpentină, în ritmul melodiei."
    tags = ("groove", "peak", "build")
    palette = "neon"
    params = (
        Param("count", "Număr comete", "int", 3, 1, 8),
        Param("mirror", "Simetric din centru", "bool", True),
    )

    def render(self, c: Ctx):
        g = self.g
        if self.p["mirror"]:
            colidx = g.inner[:, None].astype(np.float32)
            n = 6.0
        else:
            colidx = np.argsort(np.argsort(g.col_x))[:, None].astype(np.float32)
            n = 12.0
        up = (colidx % 2 == 0)
        s = (colidx + np.where(up, g.Y, 1 - g.Y)) / n   # 0..1 along the snake path
        k = int(self.p["count"])
        pos = self.t * 0.08 * c.bpm / 120.0
        d = (s * k - pos * k) % 1.0
        tail = np.exp(-(1.0 - d) * 12.0)   # head at d -> 1, tail behind it
        col = c.palette.sample(s + self.t * 0.03)
        return _shade(col, tail * (0.6 + 0.4 * float(boost(c.audio.level, c.intensity))))


@register
class TheaterChase(Effect):
    id = "theater_chase"
    name = "Theater Chase"
    description = "Lumini de marchiză retro care avansează pe fiecare bătaie."
    tags = ("groove", "retro")
    palette = "disco"
    params = (Param("spacing", "Spațiere", "int", 3, 2, 8),)

    def setup(self):
        self.step = 0

    def render(self, c: Ctx):
        g = self.g
        if c.beat:
            self.step += 1
        sp = int(self.p["spacing"])
        seglen = max(2, g.rows // 24)
        row = (np.arange(g.rows)[None, :] // seglen)
        sub = (self.t * 4) % 1.0
        on = ((row + self.step + g.inner[:, None]) % sp == 0)
        col = c.palette.sample((row // sp) * 0.17 + self.step * 0.11 + 0 * g.X)
        br = on.astype(np.float32) * (0.75 + 0.25 * sub) * (0.6 + 0.4 * c.audio.level)
        return _shade(col, br)


@register
class DiscoBall(Effect):
    id = "disco_ball"
    name = "Glob Disco"
    description = "Reflexii de glob cu oglinzi care se rotesc pe perete."
    tags = ("groove", "retro")
    palette = "disco"
    params = (Param("spots", "Reflexii", "int", 40, 10, 120),)

    def setup(self):
        n = 120
        self.sx = self.rng.random(n).astype(np.float32)
        self.sy = self.rng.random(n).astype(np.float32)
        self.sh = self.rng.random(n).astype(np.float32)

    def render(self, c: Ctx):
        g = self.g
        n = int(self.p["spots"])
        x = (self.sx[:n] + self.t * 0.05) % 1.0
        y = self.sy[:n]
        dx = (g.X[:, :, None] - x[None, None, :]) * g.aspect
        dx = np.minimum(np.abs(dx), g.aspect - np.abs(dx))
        dy = g.Y[:, :, None] - y[None, None, :]
        w = np.exp(-(dx * dx + dy * dy) / (2 * 0.02 ** 2))
        cols = 0.5 * c.palette.sample(self.sh[:n]) + 0.5
        out = np.einsum("chn,nk->chk", w.astype(np.float32), cols)
        wash = c.palette.sample(self.t * 0.03 + g.Y * 0.2) * 0.06
        sparkle = 0.7 + 0.3 * float(boost(c.audio.high, c.intensity))
        return out * sparkle + wash


@register
class Geometric(Effect):
    id = "geometric"
    name = "Geometric Techno"
    description = "Modele geometrice tăiate pe bătaie: tablă de șah, diagonale, blocuri."
    tags = ("peak", "geometric", "build")
    palette = "techno"
    params = (Param("beats", "Bătăi pe model", "int", 1, 1, 8),)

    def setup(self):
        self.idx = 0
        self.cnt = 0
        self.fade = 1.0
        self.hue = 0.0

    def pattern(self, k: int) -> np.ndarray:
        g = self.g
        ci = np.argsort(np.argsort(g.col_x))[:, None]
        r = (g.Y * 8).astype(int)
        pats = [
            ((ci + r) % 2 == 0),
            (ci % 2 == 0) & (g.Y >= 0),
            (r % 2 == 0) & (ci >= 0),
            (((ci + r) // 2) % 2 == 0),
            (g.inner[:, None] % 3 == 0) & (g.Y >= 0),
            (np.abs(g.Y - 0.5) < 0.18) | (g.inner[:, None] == 0),
            ((g.inner[:, None] + (g.Y * 6).astype(int)) % 3 == 0),
            (g.Y > 0.5) == (g.side[:, None] > 0),
        ]
        return pats[k % len(pats)].astype(np.float32)

    def render(self, c: Ctx):
        if c.beat:
            self.cnt += 1
            if self.cnt >= int(self.p["beats"]):
                self.cnt = 0
                self.idx = int(self.rng.integers(0, 8))
                self.hue += 0.21
                self.fade = 1.0
        self.fade = max(0.55, self.fade - self.scaled_dt(c) * 1.2)
        pat = self.pattern(self.idx)
        col = c.palette.sample(self.hue + self.g.D * 0.2)
        return _shade(col, pat * self.fade * (0.7 + 0.3 * float(boost(c.audio.bass, c.intensity))))


@register
class Spiral(Effect):
    id = "spiral"
    name = "Spirală"
    description = "Dungi diagonale ca un stâlp de frizerie, oglindite simetric."
    tags = ("groove", "retro", "build")
    palette = "candy"
    params = (Param("stripes", "Dungi", "float", 3.0, 1.0, 10.0),)

    def render(self, c: Ctx):
        g = self.g
        k = float(self.p["stripes"])
        v = g.Y * k + g.D * k * 0.8 - self.t * 0.6 * c.bpm / 120.0
        s = smoothstep(0.3, 0.5, 0.5 + 0.5 * np.sin(2 * np.pi * v))
        col = c.palette.sample(np.floor(v) * 0.23)
        return _shade(col, s * (0.5 + 0.5 * float(boost(c.audio.level, c.intensity))))


@register
class Glitch(Effect):
    id = "glitch"
    name = "Glitch Digital"
    description = "Blocuri digitale deplasate și inversate pe atacuri."
    tags = ("peak", "geometric")
    palette = "cyberpunk"
    params = (Param("chaos", "Haos", "float", 0.5, 0.1, 1.0),)

    def setup(self):
        self.blocks: list[list] = []

    def render(self, c: Ctx):
        g = self.g
        base = c.palette.sample(g.Y * 0.4 + self.t * 0.05 + 0 * g.X) * 0.25
        dt = self.scaled_dt(c)
        if c.kick or (c.audio.onset > 0.6 and self.rng.random() < float(self.p["chaos"])):
            for _ in range(1 + int(3 * float(self.p["chaos"]))):
                c0 = int(self.rng.integers(0, 12))
                c1 = min(12, c0 + int(self.rng.integers(1, 5)))
                y0 = float(self.rng.random())
                h = 0.05 + float(self.rng.random()) * 0.3
                self.blocks.append([c0, c1, y0, h, 0.25, float(self.rng.random())])
        out = base
        keep = []
        for b in self.blocks:
            b[4] -= dt
            if b[4] <= 0:
                continue
            m = np.zeros((12, g.rows), np.float32)
            m[b[0]:b[1]] = ((g.Y[b[0]:b[1]] > b[2]) & (g.Y[b[0]:b[1]] < b[2] + b[3]))
            col = c.palette.sample(b[5])
            if b[5] > 0.7:
                col = 1 - col
            out = out * (1 - m[..., None]) + m[..., None] * col
            keep.append(b)
        self.blocks = keep[-20:]
        scan = 0.85 + 0.15 * (np.arange(g.rows) % 2)[None, :]
        return out * scan[..., None]


@register
class Heartbeat(Effect):
    id = "heartbeat"
    name = "Heartbeat"
    description = "Puls dublu (lub-dub) pe fiecare bătaie, radiind din șemineu."
    tags = ("calm", "groove")
    palette = "lava"
    params = ()

    def render(self, c: Ctx):
        ph = c.audio.beat_phase if c.audio.bpm > 0 else (self.t * 1.0) % 1.0
        env = math.exp(-((ph - 0.02) ** 2) / 0.002) + 0.7 * math.exp(-((ph - 0.22) ** 2) / 0.002)
        env = min(1.0, env)
        g = self.g
        spread = gauss(g.R - 0.1 * env, 0.35 + 0.3 * env)
        col = c.palette.sample(0.4 + 0.3 * env + g.R * 0.2)
        return _shade(col, (0.08 + 0.92 * env * (0.5 + 0.5 * c.intensity)) * spread)


@register
class Lightning(Effect):
    id = "lightning"
    name = "Fulgere"
    description = "Fulgere ramificate pe drop-uri și kick-uri puternice, peste nori întunecați."
    tags = ("peak", "cinematic")
    palette = "ice"
    params = (Param("chance", "Frecvență", "float", 0.35, 0.05, 1.0),)

    def setup(self):
        self.bolt = np.zeros((12, self.g.rows), np.float32)
        self.flash = 0.0
        self.cool = 0.0

    def render(self, c: Ctx):
        g = self.g
        dt = self.scaled_dt(c)
        self.cool -= dt
        trig = c.drop or (c.kick and c.audio.bass > 0.6 and self.rng.random() < float(self.p["chance"]))
        if trig and self.cool <= 0:
            self.cool = 0.45
            self.bolt[:] = 0
            col = int(self.rng.integers(0, 12))
            H = g.rows
            for y in range(H - 1, -1, -1):
                self.bolt[col, y] = 1.0
                if self.rng.random() < 0.08:
                    col = int(np.clip(col + self.rng.choice([-1, 1]), 0, 11))
                    self.bolt[col, y] = 1.0
            self.flash = 0.35
        self.bolt *= math.exp(-dt * 9)
        self.flash *= math.exp(-dt * 12)
        clouds = fbm(g.X * 4 * g.aspect + self.t * 0.05, g.Y * 2, self.t * 0.1) * smoothstep(0.3, 1.0, g.Y)
        out = c.palette.sample(clouds * 0.5)[..., :] * (clouds * 0.25)[..., None]
        out += self.bolt[..., None] * np.array([0.85, 0.9, 1.0], np.float32)
        out += self.flash * np.array([0.5, 0.55, 0.7], np.float32)
        return out


@register
class Strobe(Effect):
    id = "strobe"
    name = "Stroboscop"
    description = "Flash-uri scurte sincronizate pe bătăi. Necesită activarea separată a stroboscopului."
    tags = ("peak",)
    palette = "mono"
    strobe = True
    params = (
        Param("division", "Flash-uri pe bătaie", "choice", "1", choices=(("0.5", "1/2"), ("1", "1"), ("2", "2"))),
        Param("colored", "Colorat", "bool", False),
    )

    def setup(self):
        self.on = 0.0
        self.last = 0.0
        self.k = 0

    def render(self, c: Ctx):
        div = float(self.p["division"])
        if not c.strobe_ok:
            # safety: degrade to a soft beat pulse
            ph = c.audio.beat_phase
            return np.ones(self.g.shape, np.float32) * (0.15 + 0.35 * math.exp(-ph * 6))
        ph = (c.audio.beat_phase * div) % 1.0
        if ph < self.last:
            self.on = 0.035
            self.k += 1
        self.last = ph
        self.on -= c.dt
        if self.on > 0:
            col = c.palette.sample(self.k * 0.17) if self.p["colored"] else np.ones(3, np.float32)
            return np.broadcast_to(col, self.g.shape).astype(np.float32).copy()
        return self.zeros()


@register
class ColorWash(Effect):
    id = "color_wash"
    name = "Color Wash"
    description = "Spălare lină de culoare pe tot peretele, respirând cu volumul."
    tags = ("calm",)
    palette = "chill"
    params = ()

    def render(self, c: Ctx):
        g = self.g
        col = c.palette.sample(self.t * 0.04 + g.X * 0.4 + g.Y * 0.1)
        return _shade(col, 0.35 + 0.65 * float(boost(c.audio.energy, c.intensity)))
