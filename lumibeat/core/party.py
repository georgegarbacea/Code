"""Party mode: an automatic light-show director (Auto DJ).

Inputs every frame: analysed audio (BPM, beats, kicks, bass, mids, highs, energy,
build-up, breakdown, drops, silence).  Output: which effect + palette to show and
how to transition.  Changes happen on musical phrase boundaries (bars of 4 beats),
on sustained energy changes, and immediately on a bass drop.
"""
from __future__ import annotations

import random
from collections import deque
from dataclasses import dataclass, field

from ..audio.analysis import AudioFeatures

SECTION_LABELS = {
    "calm": "Calm", "groove": "Groove", "peak": "Peak", "build": "Build-up", "drop": "DROP",
    "standby": "Standby", "intro": "Intro",
}

PARTY_PRESETS: dict[str, dict] = {
    "club": {
        "name": "Club", "desc": "Efecte rapide, culori intense.",
        "palettes": ["club", "neon", "cyberpunk", "house"],
        "pools": {
            "calm": ["color_wash", "dual_waves", "aurora", "heartbeat"],
            "groove": ["spectrum_sym", "beat_ripple", "vertical_pulse", "comet_chase", "eq_sym", "bass_pulse"],
            "peak": ["fireplace_burst", "particles", "geometric", "feedback_warp", "glitch", "vertical_pulse"],
            "build": ["scanner", "spiral", "vertical_pulse", "theater_chase"],
            "drop": ["fireplace_burst", "center_explosion", "particles"],
        },
        "phrase_beats": 16, "speed": 1.2, "transition": ("wipe_out", 0.6), "palette_change": 0.6,
    },
    "festival": {
        "name": "Festival", "desc": "Explozii cromatice și unde luminoase.",
        "palettes": ["festival", "rainbow", "vaporwave", "neon"],
        "pools": {
            "calm": ["aurora", "dual_waves", "rainbow_waves", "plasma"],
            "groove": ["dual_waves", "beat_ripple", "rainbow_waves", "spectrum_sym", "light_rain"],
            "peak": ["center_explosion", "fireplace_burst", "particles", "tunnel", "feedback_warp"],
            "build": ["vertical_pulse", "spiral", "scanner", "comet_chase"],
            "drop": ["center_explosion", "fireplace_burst", "lightning"],
        },
        "phrase_beats": 16, "speed": 1.1, "transition": ("wipe_out", 0.8), "palette_change": 0.8,
    },
    "techno": {
        "name": "Techno", "desc": "Efecte geometrice sincronizate cu ritmul.",
        "palettes": ["techno", "ice", "mono", "cyberpunk"],
        "pools": {
            "calm": ["oscilloscope", "digital_rain", "horizontal_pulse"],
            "groove": ["geometric", "horizontal_pulse", "scanner", "eq_sym", "oscilloscope", "vertical_pulse"],
            "peak": ["geometric", "tunnel", "glitch", "vertical_pulse", "feedback_warp"],
            "build": ["scanner", "geometric", "spiral"],
            "drop": ["geometric", "lightning", "fireplace_burst"],
        },
        "phrase_beats": 16, "speed": 1.15, "transition": ("dissolve", 0.4), "palette_change": 0.3,
    },
    "disco": {
        "name": "Disco", "desc": "Culori dinamice și efecte retro.",
        "palettes": ["disco", "candy", "vaporwave", "rainbow"],
        "pools": {
            "calm": ["lava", "plasma", "twinkle", "color_wash"],
            "groove": ["disco_ball", "theater_chase", "bounce", "spectrum", "rainbow_waves"],
            "peak": ["disco_ball", "spiral", "bounce", "beat_ripple", "kaleidoscope"],
            "build": ["theater_chase", "scanner", "spiral"],
            "drop": ["disco_ball", "fireplace_burst", "center_explosion"],
        },
        "phrase_beats": 32, "speed": 1.0, "transition": ("crossfade", 1.0), "palette_change": 0.7,
    },
    "house": {
        "name": "House", "desc": "Groove constant, pulsații calde și unde.",
        "palettes": ["house", "club", "sunset", "neon"],
        "pools": {
            "calm": ["color_wash", "dual_waves", "lava", "heartbeat"],
            "groove": ["vertical_pulse", "dual_waves", "spectrum_sym", "bass_pulse", "comet_chase", "eq_sym"],
            "peak": ["fireplace_burst", "beat_ripple", "particles", "vertical_pulse", "digital_flames"],
            "build": ["vertical_pulse", "scanner", "spiral"],
            "drop": ["fireplace_burst", "particles", "center_explosion"],
        },
        "phrase_beats": 32, "speed": 1.0, "transition": ("wipe_out", 1.0), "palette_change": 0.5,
    },
    "chill": {
        "name": "Chill", "desc": "Animații lente și relaxante.",
        "palettes": ["chill", "ocean", "aurora", "candy"],
        "pools": {
            "calm": ["aurora", "lava", "color_wash", "twinkle", "plasma"],
            "groove": ["dual_waves", "aurora", "freq_waves", "light_rain", "plasma"],
            "peak": ["dual_waves", "beat_ripple", "kaleidoscope", "freq_waves"],
            "build": ["dual_waves", "freq_waves"],
            "drop": ["beat_ripple", "dual_waves"],
        },
        "phrase_beats": 64, "speed": 0.6, "transition": ("crossfade", 3.0), "palette_change": 0.5,
    },
    "elegant": {
        "name": "Elegant", "desc": "Culori calde și tranziții premium.",
        "palettes": ["elegant", "golden", "warm", "royal"],
        "pools": {
            "calm": ["cinematic", "color_wash", "lava", "twinkle"],
            "groove": ["cinematic", "dual_waves", "spectrum_sym", "light_rain", "heartbeat"],
            "peak": ["cinematic", "fireplace_burst", "dual_waves", "digital_flames"],
            "build": ["cinematic", "vertical_pulse"],
            "drop": ["cinematic", "fireplace_burst"],
        },
        "phrase_beats": 32, "speed": 0.75, "transition": ("crossfade", 2.5), "palette_change": 0.3,
    },
    "auto_dj": {
        "name": "Auto DJ", "desc": "Alege automat stilul și efectele potrivite muzicii.",
        "palettes": [], "pools": {}, "phrase_beats": 16, "speed": 1.0, "transition": ("crossfade", 1.0),
        "palette_change": 0.5,
    },
}
PRESET_ORDER = ["club", "festival", "techno", "disco", "house", "chill", "elegant", "auto_dj"]


@dataclass
class PartyDecision:
    effect: str
    palette: str
    transition: tuple[str, float] | None = None   # set when the effect changes this frame
    section: str = "intro"
    style: str = ""
    beats_left: int = 0
    standby: bool = False
    speed: float = 1.0
    flash: bool = False


@dataclass
class _Stats:
    bpm: deque = field(default_factory=lambda: deque(maxlen=60))
    energy: deque = field(default_factory=lambda: deque(maxlen=60))
    bass: deque = field(default_factory=lambda: deque(maxlen=60))
    high: deque = field(default_factory=lambda: deque(maxlen=60))
    mid: deque = field(default_factory=lambda: deque(maxlen=60))


class PartyDirector:
    def __init__(self, seed: int | None = None):
        self.rng = random.Random(seed)
        self.reset()

    def reset(self) -> None:
        self.effect = ""
        self.palette = ""
        self.section = "intro"
        self.pending_section = "intro"
        self.pending_t = 0.0
        self.beats_in = 0
        self.time_in = 0.0
        self.history: deque = deque(maxlen=5)
        self.pal_history: deque = deque(maxlen=3)
        self.standby = False
        self.drop_hold = 0
        self.style = "club"
        self.stats = _Stats()
        self.stat_t = 0.0
        self.style_beats = 0

    # ------------------------------------------------------------- analysis
    def classify(self, f: AudioFeatures) -> str:
        e = f.energy
        rel = e / max(0.05, f.energy_long)
        if f.buildup > 0.6 and e > 0.12:
            return "build"
        if f.breakdown or e < 0.22 or rel < 0.55:
            return "calm"
        if e > 0.55 or (rel > 1.25 and e > 0.4):
            return "peak"
        return "groove"

    def choose_style(self) -> str:
        """Auto DJ: pick a musical style from tempo and spectral balance."""
        def avg(d, default=0.0):
            return sum(d) / len(d) if d else default

        bpm = avg(self.stats.bpm, 120)
        e = avg(self.stats.energy)
        bass = avg(self.stats.bass)
        high = avg(self.stats.high)
        mid = avg(self.stats.mid)
        if len(self.stats.energy) < 12:
            return self.style if self.style in PARTY_PRESETS and self.style != "auto_dj" else "house"
        if e < 0.2:
            return "elegant" if mid > bass else "chill"
        if bpm < 98:
            return "chill" if e < 0.45 else "elegant"
        if bpm >= 132:
            return "festival" if high > 0.55 and bass < 0.6 else "techno"
        if bpm >= 122:
            return "club" if e > 0.5 else "house"
        if bpm >= 110:
            return "house" if bass > 0.5 else "disco"
        return "disco"

    # --------------------------------------------------------------- update
    def update(self, f: AudioFeatures, beat: bool, drop: bool, dt: float, preset: str,
               duration: float = 1.0, standby_enabled: bool = True, standby_scene: str = "relax",
               strobe_ok: bool = False) -> PartyDecision:
        p = PARTY_PRESETS.get(preset, PARTY_PRESETS["auto_dj"])
        self.time_in += dt
        if beat:
            self.beats_in += 1
            self.style_beats += 1
            if self.drop_hold > 0:
                self.drop_hold -= 1

        # rolling stats for Auto DJ (sampled ~4x per second)
        self.stat_t += dt
        if self.stat_t > 0.25 and not f.silent:
            self.stat_t = 0.0
            if f.bpm > 0:
                self.stats.bpm.append(f.bpm)
            self.stats.energy.append(f.energy)
            self.stats.bass.append(f.bass)
            self.stats.high.append(f.high)
            self.stats.mid.append(f.mid)

        if preset == "auto_dj":
            if not self.effect or self.style_beats >= 64 or (self.style_beats >= 16 and len(self.stats.energy) < 40):
                self.style_beats = 0
                self.style = self.choose_style()
            style_p = PARTY_PRESETS[self.style]
            label = f"Auto DJ → {style_p['name']}"
        else:
            self.style = preset
            style_p = p
            label = p["name"]

        # ---- standby when the music stops
        if standby_enabled and f.silent and f.silence_s > 4.0:
            if not self.standby:
                self.standby = True
                self.section = "standby"
                self.effect = standby_scene
                return PartyDecision(standby_scene, "auto", ("crossfade", 3.0), "standby", label, 0, True)
            return PartyDecision(self.effect, self.palette or "auto", None, "standby", label, 0, True)
        if self.standby and not f.silent:
            self.standby = False
            self.effect = ""  # force a fresh pick

        # ---- section classification with hysteresis
        sec = self.classify(f)
        if sec != self.pending_section:
            self.pending_section = sec
            self.pending_t = 0.0
        else:
            self.pending_t += dt

        phrase = max(4, int(round(style_p["phrase_beats"] * duration)))
        change = None
        flash = False
        if drop:
            sec = "drop"
            pool = list(style_p["pools"]["drop"])
            if strobe_ok and self.rng.random() < 0.25:
                pool.append("strobe")
            change = (pool, ("flash", 0.45))
            self.drop_hold = 16
            flash = True
        elif not self.effect:
            change = (style_p["pools"][sec if sec in style_p["pools"] else "groove"], ("crossfade", 1.5))
        elif self.pending_t > 1.5 and self.pending_section != self.section and self.drop_hold <= 0 \
                and (self.beats_in >= 8 or self.time_in > 6):
            sec = self.pending_section
            change = (style_p["pools"][sec], style_p["transition"])
        elif (self.beats_in >= phrase and f.beat_count % 4 == 0 and beat) or \
                (f.bpm <= 0 and self.time_in > phrase * 0.5):
            key = self.section if self.section in style_p["pools"] else "groove"
            if self.drop_hold > 0:
                key = "peak"
            change = (style_p["pools"][key], style_p["transition"])

        if self.effect == "strobe" and self.beats_in >= 8 and change is None:
            change = (style_p["pools"]["peak"], ("crossfade", 0.5))

        transition = None
        if change is not None:
            pool, transition = change
            if sec != "drop" and self.drop_hold <= 0:
                self.section = self.pending_section if self.pending_t > 1.5 else sec
            else:
                self.section = sec
            choices = [e for e in pool if e not in self.history] or list(pool)
            new = self.rng.choice(choices)
            if new == self.effect and len(pool) > 1:
                new = self.rng.choice([e for e in pool if e != self.effect])
            self.effect = new
            self.history.append(new)
            self.beats_in = 0
            self.time_in = 0.0
            if not self.palette or self.rng.random() < style_p["palette_change"] or sec == "drop":
                pals = [x for x in style_p["palettes"] if x not in self.pal_history] or style_p["palettes"]
                self.palette = self.rng.choice(pals)
                self.pal_history.append(self.palette)
        beats_left = max(0, phrase - self.beats_in)
        return PartyDecision(self.effect, self.palette or "auto", transition, self.section, label, beats_left,
                             False, style_p["speed"], flash)
