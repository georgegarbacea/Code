"""Effects designed for this wall: 6 + 6 vertical profiles around a central fireplace."""
from __future__ import annotations

import math

import numpy as np

from .base import Ctx, Effect, Param, boost, column_levels, fbm, gauss, noise3, register, smoothstep


def _shade(col, br):
    return col * np.asarray(br, np.float32)[..., None]


@register
class FireplaceBurst(Effect):
    id = "fireplace_burst"
    name = "Explozie din Șemineu"
    category = "special"
    description = "Explozie luminoasă din zona șemineului care se propagă spre exterior, pe ambele părți."
    tags = ("peak", "groove")
    palette = "festival"
    params = (
        Param("trigger", "Declanșare", "choice", "beat", choices=(("beat", "Fiecare bătaie"), ("bar", "Fiecare măsură"), ("kick", "Kick"))),
        Param("width", "Grosime front", "float", 0.12, 0.04, 0.3),
    )

    def setup(self):
        self.waves: list[list[float]] = []   # front position, strength, hue
        self.beats = 0
        self.hue = 0.0
        self.core = 0.0

    def render(self, c: Ctx):
        g = self.g
        dt = self.scaled_dt(c)
        trig = False
        mode = self.p["trigger"]
        if c.beat:
            self.beats += 1
        if mode == "beat" and c.beat:
            trig = True
        elif mode == "bar" and c.beat and self.beats % 4 == 0:
            trig = True
        elif mode == "kick" and c.kick:
            trig = True
        if c.drop:
            trig = True
        if trig:
            self.hue += 0.17
            s = 1.4 if c.drop else 0.8 + 0.4 * c.audio.bass * c.intensity
            self.waves.append([-0.1, s, self.hue])
            self.core = 1.0
        speed = 1.1 * c.bpm / 120.0
        out = self.zeros()
        w = float(self.p["width"])
        # vertical spread centred on the fireplace height that widens as the front travels
        keep = []
        for wv in self.waves:
            wv[0] += speed * dt
            wv[1] *= math.exp(-dt * 0.9)
            if wv[0] > 1.4 or wv[1] < 0.03:
                continue
            front = gauss(g.D - wv[0], w) + 0.35 * gauss(g.D - wv[0] + 0.15, w * 2)
            vspread = gauss(g.Y - g.centre_y, 0.25 + 0.7 * max(0.0, wv[0]))
            out += c.palette.sample(wv[2] + g.D * 0.15) * (front * vspread * wv[1])[..., None]
            keep.append(wv)
        self.waves = keep[-10:]
        self.core *= math.exp(-dt * 5)
        inner = (g.inner[:, None] == 0) * gauss(g.Y - g.centre_y, 0.3)
        out += np.array([1.0, 0.75, 0.45], np.float32) * (inner * self.core * 0.8)[..., None]
        return out


@register
class DualWaves(Effect):
    id = "dual_waves"
    name = "Unde Stânga–Dreapta"
    category = "special"
    description = "Unde care pornesc din centru și se deplasează simultan spre stânga și spre dreapta."
    tags = ("groove", "calm", "peak")
    palette = "ocean"
    params = (
        Param("style", "Stil", "choice", "height", choices=(("height", "Înălțime (val)"), ("bands", "Benzi de culoare"))),
        Param("wavelength", "Lungime de undă", "float", 0.6, 0.2, 2.0),
    )

    def setup(self):
        self.ph = 0.0
        self.kick = 0.0

    def render(self, c: Ctx):
        g = self.g
        dt = self.scaled_dt(c)
        self.ph += dt * c.bpm / 120.0 * (0.8 + 0.6 * c.audio.energy)
        if c.kick:
            self.kick = 1.0
        self.kick *= math.exp(-dt * 4)
        lam = float(self.p["wavelength"])
        phase = 2 * np.pi * (g.D / lam - self.ph)
        if self.p["style"] == "height":
            amp = 0.25 + 0.25 * float(boost(c.audio.bass, c.intensity)) + 0.15 * self.kick
            h = 0.5 + amp * np.sin(phase)
            body = smoothstep(h + 0.03, h - 0.03, g.Y)
            col = c.palette.sample(g.Y * 0.5 + g.D * 0.3 - self.ph * 0.1)
            crest = gauss(g.Y - h, 0.03)
            return _shade(col, body * (0.35 + 0.5 * g.Y) + crest)
        band = 0.5 + 0.5 * np.sin(phase)
        col = c.palette.sample(g.D / lam * 0.5 - self.ph * 0.5)
        return _shade(col, (0.15 + 0.85 * band ** 2) * (0.6 + 0.4 * c.audio.level + 0.3 * self.kick))


@register
class SymmetricEQ(Effect):
    id = "eq_sym"
    name = "Egalizator Simetric"
    category = "special"
    description = "Egalizator segmentat cu 6 benzi pe fiecare grup de profile, oglindit față de șemineu."
    tags = ("groove", "peak", "spectrum")
    palette = "neon"
    params = (
        Param("segments", "Segmente", "int", 14, 6, 30),
        Param("classic", "Culori clasice (verde-galben-roșu)", "bool", False),
    )

    def setup(self):
        self.lv = np.zeros(12, np.float32)
        self.pk = np.zeros(12, np.float32)

    def render(self, c: Ctx):
        g = self.g
        lv = boost(column_levels(c, True), c.intensity)
        self.lv = np.where(lv > self.lv, lv, self.lv * 0.85 + lv * 0.15)
        self.pk = np.maximum(self.lv, self.pk - self.scaled_dt(c) * 0.3)
        nseg = int(self.p["segments"])
        segpos = g.Y * nseg
        seg_i = np.floor(segpos)
        gap = (segpos - seg_i) < 0.78
        lit = (seg_i / nseg) < self.lv[:, None]
        if self.p["classic"]:
            from .base import hsv
            col = hsv(0.33 - 0.33 * (seg_i / nseg), 1.0, 1.0)
        else:
            col = c.palette.sample(seg_i / nseg * 0.7 + g.D * 0.2 + self.t * 0.02)
        out = _shade(col, (lit & gap).astype(np.float32))
        pk_seg = np.floor(self.pk * nseg)[:, None]
        out += ((seg_i == pk_seg) & gap)[..., None] * np.array([1, 1, 1], np.float32) * 0.8
        return out


@register
class DigitalFlames(Effect):
    id = "digital_flames"
    name = "Flăcări Digitale"
    category = "special"
    description = "Limbi de foc stilizate care urcă pe toate profilele, înalte pe bass."
    tags = ("groove", "peak", "warm")
    palette = "fire"
    params = (Param("height", "Înălțime flăcări", "float", 0.55, 0.2, 1.0),)

    def setup(self):
        self.boost = 0.0

    def render(self, c: Ctx):
        g = self.g
        if c.kick:
            self.boost = 1.0
        self.boost *= math.exp(-self.scaled_dt(c) * 3.5)
        t = self.t
        base_h = float(self.p["height"])
        colid = g.col_x[:, None] * 13.0
        tongue = noise3(colid, t * 1.3, 0.5) * 0.35 + noise3(colid * 2.1, t * 2.7, 4.2) * 0.15
        h = base_h * 0.6 + tongue + 0.35 * float(boost(c.audio.bass, c.intensity)) + 0.25 * self.boost
        tex = fbm(colid * 0.6, g.Y * 5.0 - t * 2.5, t * 0.3, 3)
        heat = (1.0 - g.Y / np.maximum(h, 0.08)) + (tex - 0.5) * 0.6
        heat = np.clip(heat, 0, 1)
        return c.palette.sample(heat * 0.95) * smoothstep(0.02, 0.2, heat)[..., None]


@register
class LightRain(Effect):
    id = "light_rain"
    name = "Ploaie Luminoasă"
    category = "special"
    description = "Picături de lumină sincronizate cu bătăile, care se sparg la baza profilelor."
    tags = ("groove", "calm")
    palette = "ice"
    params = (
        Param("drops", "Picături pe bătaie", "int", 3, 1, 8),
        Param("splash", "Stropire", "bool", True),
    )

    def setup(self):
        self.drops: list[list[float]] = []   # col, y, v, hue
        self.splash = np.zeros(12, np.float32)
        self.buf = self.zeros()
        self.eighth = 0.0

    def render(self, c: Ctx):
        g = self.g
        dt = self.scaled_dt(c)
        n = 0
        if c.beat:
            n += int(self.p["drops"])
        ph8 = (c.audio.beat_phase * 2) % 1.0
        if ph8 < self.eighth and c.audio.high > 0.3:
            n += 1
        self.eighth = ph8
        for _ in range(n):
            self.drops.append([int(self.rng.integers(0, 12)), 1.05, 1.0 + self.rng.random() * 0.5,
                               float(self.rng.random())])
        v_mul = c.bpm / 120.0
        self.buf *= 0.78 ** (dt * 60)
        keep = []
        for d in self.drops:
            d[2] += 1.6 * dt
            d[1] -= d[2] * dt * v_mul
            if d[1] <= 0.0:
                self.splash[d[0]] = 1.0
                continue
            head = gauss(g.Y[0] - d[1], 0.012)
            self.buf[d[0]] = np.maximum(self.buf[d[0]], head[:, None] * (0.5 + 0.5 * c.palette.sample(d[3])))
            keep.append(d)
        self.drops = keep[-150:]
        self.splash *= math.exp(-dt * 5)
        out = self.buf.copy()
        if self.p["splash"]:
            spl = gauss(g.Y, 0.05) * self.splash[:, None]
            out += c.palette.sample(0.8)[None, None, :] * spl[..., None]
        return out


@register
class VerticalPulse(Effect):
    id = "vertical_pulse"
    name = "Pulsații Verticale"
    category = "special"
    description = "Fiecare bătaie trimite un puls de lumină de jos în sus, întâi pe profilele din centru."
    tags = ("groove", "peak", "build")
    palette = "club"
    params = (
        Param("thickness", "Grosime", "float", 0.12, 0.04, 0.4),
        Param("stagger", "Decalaj centru→exterior", "float", 0.08, 0.0, 0.3),
    )

    def setup(self):
        self.pulses: list[list[float]] = []   # age (beats), hue, strength
        self.hue = 0.0

    def render(self, c: Ctx):
        g = self.g
        beat_len = 60.0 / c.bpm
        if c.beat or (c.drop and not self.pulses):
            self.hue += 0.19
            self.pulses.append([0.0, self.hue, 0.7 + 0.3 * float(boost(c.audio.bass, c.intensity))])
        out = self.zeros()
        keep = []
        th = float(self.p["thickness"])
        st = float(self.p["stagger"])
        for p in self.pulses:
            p[0] += self.scaled_dt(c) / beat_len
            pos = p[0] - st * g.inner[:, None]
            if (pos > 1.4).all():
                continue
            band = gauss(g.Y - pos * 1.15, th) * (pos > -0.1)
            out += c.palette.sample(p[1] + g.Y * 0.2) * (band * p[2])[..., None]
            keep.append(p)
        self.pulses = keep[-8:]
        return out


@register
class HorizontalPulse(Effect):
    id = "horizontal_pulse"
    name = "Pulsații Orizontale"
    category = "special"
    description = "Linii orizontale peste toate cele 12 profile: jos bass, sus înalte, pulsând pe frecvențe."
    tags = ("groove", "geometric")
    palette = "neon"
    params = (Param("lines", "Linii", "int", 4, 2, 8),)

    def render(self, c: Ctx):
        g = self.g
        a = c.audio
        n = int(self.p["lines"])
        lv = np.interp(np.linspace(0, 1, n), [0, 0.33, 0.66, 1.0], [a.bass, a.lowmid, a.mid, a.high])
        out = self.zeros()
        for i in range(n):
            y = (i + 0.5) / n
            l = float(boost(lv[i], c.intensity))
            th = 0.015 + 0.06 * l
            spread = 0.25 + 0.75 * l   # line grows outward from the fireplace with level
            mask = smoothstep(spread + 0.05, spread - 0.05, g.D)
            band = gauss(g.Y - y, th) * mask * (0.25 + 0.75 * l)
            out += c.palette.sample(i / n + self.t * 0.03) * band[..., None]
        return out


@register
class Cinematic(Effect):
    id = "cinematic"
    name = "Cinematic"
    category = "special"
    description = "Fascicule largi care baleiază lent peretele, cu „reveal” dramatic pe drop."
    tags = ("calm", "cinematic", "build")
    palette = "elegant"
    params = (Param("beams", "Fascicule", "int", 2, 1, 3),)

    def setup(self):
        self.reveal = 0.0

    def render(self, c: Ctx):
        g = self.g
        dt = self.scaled_dt(c)
        if c.drop:
            self.reveal = 1.0
        self.reveal *= math.exp(-dt * 0.8)
        out = self.zeros()
        e = c.audio.energy
        n = int(self.p["beams"])
        for i in range(n):
            ph = self.t * (0.11 + 0.04 * i) + i * 2.1
            x = 0.5 + 0.55 * math.sin(ph)
            w = 0.07 + 0.12 * e
            beam = gauss(g.X - x, w) * (0.35 + 0.65 * smoothstep(1.1, 0.1, g.Y))
            out += c.palette.sample(0.3 + 0.25 * i + 0.1 * math.sin(ph * 0.5)) * beam[..., None] * (0.5 + 0.6 * e)
        # dramatic reveal from the fireplace outward
        front = 1.2 * (1 - self.reveal)
        rv = smoothstep(front + 0.2, front - 0.1, g.D) * self.reveal
        out += np.array([1.0, 0.82, 0.6], np.float32) * rv[..., None]
        vignette = 0.75 + 0.25 * (1 - g.D)
        return out * vignette[..., None]
