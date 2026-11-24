"""Built-in demo track (procedural house music, 124 BPM).

Lets the simulator, Party mode and Auto DJ be tested without any music playing.
The arrangement contains an intro, groove, build-up, bass drop, breakdown,
second drop, outro and a few seconds of silence (to exercise the standby).
"""
from __future__ import annotations

import numpy as np

BPM = 124.0
SPB = 60.0 / BPM
BAR = SPB * 4

# (start_bar, end_bar, name)
SECTIONS = [
    (0, 8, "intro"),
    (8, 16, "groove"),
    (16, 24, "build"),
    (24, 40, "drop"),
    (40, 48, "breakdown"),
    (48, 52, "build"),
    (52, 68, "drop"),
    (68, 72, "outro"),
]
SONG_BARS = 72
SILENCE_S = 6.0
LOOP_S = SONG_BARS * BAR + SILENCE_S

_BASS_NOTES = np.array([55.0, 43.65, 65.41, 49.0])         # A1 F1 C2 G1
_CHORDS = np.array([
    [220.0, 261.63, 329.63],   # Am
    [174.61, 220.0, 261.63],   # F
    [261.63, 329.63, 392.0],   # C
    [196.0, 246.94, 293.66],   # G
])


def section_at(t: float) -> str:
    tt = t % LOOP_S
    bar = tt / BAR
    for a, b, name in SECTIONS:
        if a <= bar < b:
            return name
    return "silence"


class DemoSynth:
    def __init__(self, sample_rate: int = 48000, seed: int = 7):
        self.sr = sample_rate
        self.n = 0
        self.rng = np.random.default_rng(seed)

    def render(self, frames: int) -> np.ndarray:
        sr = self.sr
        t = (self.n + np.arange(frames)) / sr
        self.n += frames
        tt = t % LOOP_S
        beat = tt / SPB
        bar = beat / 4.0
        bar_i = np.floor(bar).astype(int)
        in_song = bar < SONG_BARS

        sec = np.full(frames, 8)
        for k, (a, b, _) in enumerate(SECTIONS):
            sec = np.where((bar >= a) & (bar < b), k, sec)
        name = np.array([s[2] for s in SECTIONS] + ["silence"])[sec]
        is_drop = name == "drop"
        is_groove = name == "groove"
        is_build = name == "build"
        is_intro = name == "intro"
        is_break = name == "breakdown"
        is_outro = name == "outro"

        tb = (beat % 1.0) * SPB
        # kick
        kick_on = is_drop | is_groove | is_outro
        ph = 2 * np.pi * (45.0 * tb + 3.0 * (1 - np.exp(-30.0 * tb)))
        kick = np.sin(ph) * np.exp(-tb * 8.0) * kick_on * 0.9
        # clap on beats 2 and 4
        bi = np.floor(beat).astype(int)
        clap_on = (bi % 2 == 1) & (is_drop | is_groove)
        noise = self.rng.standard_normal(frames).astype(np.float32)
        hp = np.empty_like(noise)
        hp[0] = noise[0]
        hp[1:] = noise[1:] - noise[:-1]
        clap = noise * np.exp(-tb * 22.0) * clap_on * 0.25
        # hats on the off-beat eighths (+ 16ths in drops)
        t8 = ((beat * 2) % 1.0) * SPB / 2
        odd8 = (np.floor(beat * 2).astype(int) % 2) == 1
        hat_on = (is_drop | is_groove | is_intro | is_break | is_build) & odd8
        hats = hp * np.exp(-t8 * 70.0) * hat_on * 0.12
        t16 = ((beat * 4) % 1.0) * SPB / 4
        hats += hp * np.exp(-t16 * 120.0) * is_drop * 0.05
        # bass on the "and" of each beat
        note = _BASS_NOTES[bar_i % 4]
        gate = ((beat % 1.0) > 0.5) & ((beat % 1.0) < 0.95) & (is_drop | is_groove)
        bass = sum(np.sin(2 * np.pi * note * h * t) / h for h in range(1, 5)) * gate * 0.35
        bass *= np.exp(-((beat % 1.0) - 0.5) * 3)
        # pad chords
        ch = _CHORDS[bar_i % 4]
        pad = (np.sin(2 * np.pi * ch[:, 0] * t) + np.sin(2 * np.pi * ch[:, 1] * t) +
               np.sin(2 * np.pi * ch[:, 2] * t)) / 3.0
        pad_lvl = np.where(is_break | is_intro, 0.18, np.where(is_drop, 0.08, 0.05))
        pad *= pad_lvl * (0.7 + 0.3 * np.sin(2 * np.pi * 0.25 * t))
        # build: accelerating snare roll + noise riser
        prog = np.where(is_build & (bar < 30), (bar - 16) / 8.0, np.where(is_build, (bar - 48) / 4.0, 0.0))
        prog = np.clip(prog, 0.0, 1.0)
        rate = 2 + np.floor(prog * 4) * 2               # hits per beat 2..10
        tr = ((beat * rate) % 1.0) * SPB / rate
        snare = noise * np.exp(-tr * 40.0) * is_build * (0.08 + 0.25 * prog)
        riser = hp * is_build * prog ** 2 * 0.12

        mix = kick + clap + hats + bass + pad + snare + riser
        mix = np.where(in_song, mix, 0.0)
        mix = np.tanh(mix * 1.2) * 0.6
        stereo = np.stack([mix + hats * 0.3, mix - hats * 0.3], axis=1).astype(np.float32)
        return stereo
