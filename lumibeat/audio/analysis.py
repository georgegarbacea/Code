"""Real-time music analysis.

Per hop (default 512 samples ≈ 10.7 ms @ 48 kHz):
* windowed FFT (SciPy) over a 2048-sample sliding buffer
* 32 log-spaced bands (30 Hz .. 16 kHz) with spectral tilt compensation
* adaptive noise floor per band + noise gate (noise filtering)
* automatic gain control: global + per-band normalisation with fast attack / slow release
* spectral-flux onset envelope (full band + bass band)
* tempo (BPM) by autocorrelation of the onset envelope with a tempo prior and octave check
* beat phase tracking (PLL style) -> beat events + continuous beat phase
* kick detection, build-up / breakdown detection and bass-drop detection
* silence detection (for the ambient standby)
"""
from __future__ import annotations

import math
import threading
import time
from collections import deque
from dataclasses import dataclass, field

import numpy as np
from scipy import fft as sfft
from scipy.signal import get_window

NUM_BANDS = 32


@dataclass
class AudioFeatures:
    t: float = 0.0
    level: float = 0.0          # normalised loudness 0..1 (AGC)
    level_l: float = 0.0
    level_r: float = 0.0
    rms_db: float = -100.0
    bass: float = 0.0           # 30..150 Hz
    sub: float = 0.0            # 30..60 Hz
    lowmid: float = 0.0         # 150..500 Hz
    mid: float = 0.0            # 500..2 kHz
    highmid: float = 0.0        # 2..5 kHz
    high: float = 0.0           # 5..16 kHz
    bands: np.ndarray = field(default_factory=lambda: np.zeros(NUM_BANDS, np.float32))
    bands_peak: np.ndarray = field(default_factory=lambda: np.zeros(NUM_BANDS, np.float32))
    waveform: np.ndarray = field(default_factory=lambda: np.zeros(64, np.float32))
    onset: float = 0.0          # onset strength 0..1
    bpm: float = 0.0
    bpm_confidence: float = 0.0
    beat_phase: float = 0.0     # 0..1 between predicted beats
    beat_count: int = 0         # increments on every tracked beat
    kick_count: int = 0         # increments on every detected kick (bass onset)
    drop_count: int = 0         # increments on every detected bass drop
    energy: float = 0.0         # ~1 s smoothed intensity
    energy_long: float = 0.0    # ~10 s smoothed intensity
    buildup: float = 0.0        # 0..1 build-up likelihood
    breakdown: bool = False
    silent: bool = True
    silence_s: float = 0.0
    latency_ms: float = 0.0


class AudioAnalyzer:
    def __init__(self, sample_rate: int = 48000, hop: int = 512, nfft: int = 2048):
        self.lock = threading.Lock()
        self.sensitivity = 1.0
        self.noise_gate_db = -62.0
        self.auto_gain = True
        self.reset(sample_rate, hop, nfft)

    # ----------------------------------------------------------------- setup
    def reset(self, sample_rate: int, hop: int | None = None, nfft: int | None = None) -> None:
        with self.lock:
            self.sr = int(sample_rate)
            self.hop = int(hop or getattr(self, "hop", 512))
            self.nfft = int(nfft or getattr(self, "nfft", 2048))
            while self.nfft < 2 * self.hop:
                self.nfft *= 2
            self.frame_rate = self.sr / self.hop
            self.buf = np.zeros(self.nfft, np.float32)
            self.win = get_window("hann", self.nfft).astype(np.float32)
            freqs = sfft.rfftfreq(self.nfft, 1.0 / self.sr)
            edges = np.geomspace(30.0, min(16000.0, self.sr / 2 - 1), NUM_BANDS + 1)
            self.band_bins: list[tuple[int, int]] = []
            for i in range(NUM_BANDS):
                lo = int(np.searchsorted(freqs, edges[i]))
                hi = max(lo + 1, int(np.searchsorted(freqs, edges[i + 1])))
                self.band_bins.append((lo, hi))
            centres = np.sqrt(edges[:-1] * edges[1:])
            # +3 dB/octave tilt so pink-ish music looks flat
            self.tilt_db = (3.0 * np.log2(centres / 1000.0)).astype(np.float32)
            self.centres = centres

            def bsel(lo, hi):
                return np.where((centres >= lo) & (centres < hi))[0]

            self.idx_sub = bsel(30, 60)
            self.idx_bass = bsel(30, 150)
            self.idx_lowmid = bsel(150, 500)
            self.idx_mid = bsel(500, 2000)
            self.idx_highmid = bsel(2000, 5000)
            self.idx_high = bsel(5000, 17000)
            self.bass_bins = int(np.searchsorted(freqs, 160.0))

            self.floor_db = np.full(NUM_BANDS, -90.0, np.float32)
            self.peak_db = np.full(NUM_BANDS, -40.0, np.float32)
            self.gpeak_db = -30.0
            self.bands_s = np.zeros(NUM_BANDS, np.float32)
            self.bands_pk = np.zeros(NUM_BANDS, np.float32)
            self.prev_logmag: np.ndarray | None = None
            self.level_ref = 0.05
            self.level_s = 0.0
            self.lvl_l = 0.0
            self.lvl_r = 0.0

            n_env = int(self.frame_rate * 8)
            self.env = deque([0.0] * n_env, maxlen=n_env)
            self.flux_hist = deque([0.0] * int(self.frame_rate), maxlen=int(self.frame_rate))
            self.bflux_hist = deque([0.0] * int(self.frame_rate), maxlen=int(self.frame_rate))
            self.frame_idx = 0
            self.bpm = 0.0
            self.bpm_conf = 0.0
            self.bpm_hist = np.zeros(181, np.float32)   # vote histogram over 60..240 bpm
            self.last_tempo_eval = 0
            self.period = 0.0                           # beat period in frames
            self.next_beat = 0.0                        # predicted frame index of next beat
            self.last_beat_frame = 0.0
            self.beat_count = 0
            self.kick_count = 0
            self.last_kick_frame = -1000
            self.drop_count = 0
            self.last_drop_frame = -100000
            self.energy = 0.0
            self.energy_long = 0.0
            self.bass_short = 0.0
            self.bass_long = 0.0
            self.low_bass_frames = 0
            self.breakdown_ref = 0.0
            self.sub_short = 0.0
            self.sub_long = -100.0
            self.high_hist = deque([0.0] * int(self.frame_rate * 6), maxlen=int(self.frame_rate * 6))
            self.onset_rate_hist = deque([0.0] * int(self.frame_rate * 6), maxlen=int(self.frame_rate * 6))
            self.silent_frames = 10 ** 6
            self.features = AudioFeatures()
            self._resid = None

    # ---------------------------------------------------------------- process
    def process(self, block: np.ndarray, capture_time: float | None = None) -> AudioFeatures:
        """Feed one block (frames, channels) of float32 audio. Blocks may be any size;
        they are consumed in hop-sized chunks."""
        if block.ndim == 1:
            block = block[:, None]
        if block.shape[1] > 2:
            block = block[:, :2]
        if self._resid is not None and self._resid.shape[1] == block.shape[1]:
            block = np.concatenate([self._resid, block], axis=0)
        n = block.shape[0]
        out = self.features
        pos = 0
        while n - pos >= self.hop:
            out = self._process_hop(block[pos:pos + self.hop])
            pos += self.hop
        self._resid = block[pos:].copy() if pos < n else None
        if capture_time is not None:
            out.latency_ms = max(0.0, (time.perf_counter() - capture_time) * 1000.0)
        return out

    def _process_hop(self, chunk: np.ndarray) -> AudioFeatures:
        fr = self.frame_rate
        self.frame_idx += 1
        fi = self.frame_idx
        mono = chunk.mean(axis=1).astype(np.float32)
        m = len(mono)
        self.buf = np.roll(self.buf, -m)
        self.buf[-m:] = mono

        rms = float(np.sqrt(np.mean(mono ** 2) + 1e-12))
        rms_db = 20.0 * math.log10(rms + 1e-9)
        if chunk.shape[1] >= 2:
            l = float(np.sqrt(np.mean(chunk[:, 0] ** 2) + 1e-12))
            r = float(np.sqrt(np.mean(chunk[:, 1] ** 2) + 1e-12))
        else:
            l = r = rms
        gated = rms_db < self.noise_gate_db
        self.silent_frames = self.silent_frames + 1 if gated else 0

        # ---- automatic gain on overall level (fast attack, ~8 s release)
        if self.auto_gain:
            if rms > self.level_ref:
                self.level_ref += (rms - self.level_ref) * 0.25
            else:
                self.level_ref *= 0.9995 ** (512 / self.hop)
            self.level_ref = max(self.level_ref, 10 ** (self.noise_gate_db / 20) * 4)
            ref = self.level_ref
        else:
            ref = 0.3
        sens = self.sensitivity
        level = 0.0 if gated else min(1.0, (rms / ref) * 0.9 * sens)
        lvl_l = 0.0 if gated else min(1.0, (l / ref) * 0.9 * sens)
        lvl_r = 0.0 if gated else min(1.0, (r / ref) * 0.9 * sens)
        a = 0.5 if level > self.level_s else 0.12
        self.level_s += (level - self.level_s) * a
        self.lvl_l += (lvl_l - self.lvl_l) * (0.5 if lvl_l > self.lvl_l else 0.12)
        self.lvl_r += (lvl_r - self.lvl_r) * (0.5 if lvl_r > self.lvl_r else 0.12)

        # ---- spectrum
        spec = np.abs(sfft.rfft(self.buf * self.win)).astype(np.float32)
        power = spec ** 2 / (self.nfft * 0.5)
        bp = np.array([power[lo:hi].mean() for lo, hi in self.band_bins], np.float32)
        db = 10.0 * np.log10(bp + 1e-14) + self.tilt_db

        # adaptive noise floor (min statistics) - drops fast, rises slowly
        up = 0.01 * (512 / self.hop)
        self.floor_db = np.where(db < self.floor_db, db * 0.3 + self.floor_db * 0.7, self.floor_db + up)
        self.floor_db = np.maximum(self.floor_db, -110.0)
        # per-band and global peaks (AGC)
        rel = 0.04 * (512 / self.hop)
        self.peak_db = np.where(db > self.peak_db, db, self.peak_db - rel)
        self.peak_db = np.maximum(self.peak_db, self.floor_db + 24.0)
        gmax = float(db.max())
        if gmax > self.gpeak_db:
            self.gpeak_db = gmax
        else:
            self.gpeak_db -= rel
        self.gpeak_db = max(self.gpeak_db, float(self.floor_db.mean()) + 30.0)
        if self.auto_gain:
            n_band = (db - self.floor_db - 4.0) / np.maximum(6.0, self.peak_db - self.floor_db - 4.0)
            n_glob = (db - (self.gpeak_db - 45.0)) / 45.0
            norm = 0.45 * n_band + 0.55 * n_glob
        else:
            norm = (db + 70.0) / 60.0
        norm = np.clip(norm * sens, 0.0, 1.0).astype(np.float32)
        if gated:
            norm[:] = 0.0
        att = norm > self.bands_s
        self.bands_s = np.where(att, self.bands_s + (norm - self.bands_s) * 0.6, self.bands_s + (norm - self.bands_s) * 0.18)
        self.bands_pk = np.maximum(self.bands_s, self.bands_pk - 0.012 * (512 / self.hop))

        def bavg(idx):
            return float(self.bands_s[idx].mean()) if len(idx) else 0.0

        bass = bavg(self.idx_bass)
        sub = bavg(self.idx_sub)
        lowmid = bavg(self.idx_lowmid)
        mid = bavg(self.idx_mid)
        highmid = bavg(self.idx_highmid)
        high = bavg(self.idx_high)

        # ---- onset envelope (spectral flux of log magnitude)
        logmag = np.log1p(spec * 10.0)
        if self.prev_logmag is None:
            self.prev_logmag = logmag
        diff = logmag - self.prev_logmag
        self.prev_logmag = logmag
        pos = np.maximum(diff, 0.0)
        flux = float(pos.mean())
        bflux = float(pos[1:self.bass_bins].mean()) if self.bass_bins > 2 else flux
        if gated:
            flux = bflux = 0.0
        self.flux_hist.append(flux)
        self.bflux_hist.append(bflux)
        fmean = float(np.mean(self.flux_hist)) + 1e-6
        fstd = float(np.std(self.flux_hist)) + 1e-6
        onset = float(np.clip((flux - fmean) / (3.0 * fstd), 0.0, 1.0))
        env_v = max(0.0, flux - fmean * 0.9) + 0.6 * max(0.0, bflux - float(np.mean(self.bflux_hist)))
        self.env.append(env_v)
        self.onset_rate_hist.append(1.0 if onset > 0.5 else 0.0)

        # ---- kick detection (bass onset with adaptive threshold and refractory period)
        bmean = float(np.mean(self.bflux_hist))
        bstd = float(np.std(self.bflux_hist)) + 1e-6
        if not gated and bflux > bmean + 1.6 * bstd and bflux > 1e-4 and fi - self.last_kick_frame > 0.22 * fr \
                and bass > 0.25:
            self.kick_count += 1
            self.last_kick_frame = fi

        # ---- tempo estimate every ~0.5 s
        if fi - self.last_tempo_eval >= fr * 0.5:
            self.last_tempo_eval = fi
            self._estimate_tempo()

        # ---- beat tracking
        self._track_beats(fi)

        # ---- energy / sections
        e_in = 0.6 * self.level_s + 0.4 * bass
        self.energy += (e_in - self.energy) * (1.0 / (fr * 1.0))
        self.energy_long += (e_in - self.energy_long) * (1.0 / (fr * 10.0))
        self.bass_short += (bass - self.bass_short) * (1.0 / (fr * 0.35))
        self.bass_long += (bass - self.bass_long) * (1.0 / (fr * 8.0))
        self.high_hist.append(0.5 * high + 0.5 * highmid)

        # sub-bass (kick drum region) tracks the "four on the floor"; it disappears in
        # breakdowns / build-ups and comes back hard on the drop
        # absolute (not AGC-normalised) sub-bass power, so hi-hats / snare rolls
        # in a build-up are not mistaken for kicks
        sub_pow = float(bp[self.idx_sub].mean()) if len(self.idx_sub) else 0.0
        sub_db = 10.0 * math.log10(sub_pow + 1e-14)
        self.sub_short += (sub_pow - self.sub_short) * (1.0 / (fr * 0.25))
        sdb = 10.0 * math.log10(self.sub_short + 1e-14)
        if sub_db > self.sub_long:
            self.sub_long = sub_db
        else:
            self.sub_long -= 1.0 / fr          # peak decays 1 dB/s
        self.sub_long = max(self.sub_long, -100.0)
        has_ref = self.sub_long > float(self.floor_db[self.idx_sub].mean() if len(self.idx_sub) else -90) + 15
        low_sub = (not gated) and has_ref and sdb < self.sub_long - 12.0
        if low_sub:
            self.low_bass_frames += 1
        elif sdb > self.sub_long - 8.0:
            if self.low_bass_frames > fr * 2.0 and fi - self.last_drop_frame > fr * 8:
                self.drop_count += 1
                self.last_drop_frame = fi
            self.low_bass_frames = 0
        breakdown = low_sub and self.low_bass_frames > fr * 1.0
        # build-up: rising highs + onset density over the last seconds
        hh = np.asarray(self.high_hist)
        third = len(hh) // 3
        rise = float(hh[-third:].mean() - hh[:third].mean())
        dens = float(np.mean(list(self.onset_rate_hist)[-int(fr * 2):]))
        buildup = float(np.clip(rise * 4.0 + dens * 1.5 - sub * 0.8, 0.0, 1.0))
        if breakdown:
            buildup = max(buildup, min(1.0, self.low_bass_frames / (fr * 8.0)))

        silent = self.silent_frames > fr * 0.4
        wf = self.buf[-512:][:: 8].copy()
        pk = float(np.abs(wf).max()) + 1e-6
        wf = wf / max(pk, self.level_ref * 2.5)

        phase = 0.0
        if self.period > 0:
            phase = float(np.clip((fi - self.last_beat_frame) / self.period, 0.0, 1.0))
        f = AudioFeatures(
            t=fi / fr, level=self.level_s, level_l=self.lvl_l, level_r=self.lvl_r, rms_db=rms_db,
            bass=bass, sub=sub, lowmid=lowmid, mid=mid, highmid=highmid, high=high,
            bands=self.bands_s.copy(), bands_peak=self.bands_pk.copy(), waveform=wf.astype(np.float32),
            onset=onset, bpm=self.bpm if not silent else self.bpm, bpm_confidence=self.bpm_conf,
            beat_phase=phase, beat_count=self.beat_count, kick_count=self.kick_count,
            drop_count=self.drop_count, energy=float(np.clip(self.energy, 0, 1)),
            energy_long=float(np.clip(self.energy_long, 0, 1)), buildup=buildup, breakdown=breakdown,
            silent=silent, silence_s=self.silent_frames / fr if silent else 0.0,
        )
        self.features = f
        return f

    # ------------------------------------------------------------------ tempo
    def _estimate_tempo(self) -> None:
        env = np.asarray(self.env, dtype=np.float32)
        if env.max() <= 1e-6 or self.silent_frames > self.frame_rate:
            self.bpm_conf *= 0.9
            return
        env = env - env.mean()
        n = len(env)
        spec = np.fft.rfft(env, 2 * n)
        ac = np.fft.irfft(spec * np.conj(spec))[:n]
        if ac[0] <= 0:
            return
        ac = ac / ac[0]
        fr = self.frame_rate
        bpms = np.arange(60, 241, dtype=np.float32)
        lags = fr * 60.0 / bpms
        vals = np.interp(lags, np.arange(n), ac)
        # harmonic support: a true beat period also correlates at 2x and 0.5x
        vals2 = np.interp(lags * 2, np.arange(n), ac, right=0)
        vals_h = np.interp(lags / 2, np.arange(n), ac)
        score = vals + 0.5 * vals2 + 0.25 * vals_h
        prior = np.exp(-0.5 * (np.log2(bpms / 122.0) / 0.9) ** 2)
        score = score * prior
        best = int(np.argmax(score))
        conf = float(max(0.0, vals[best]))
        self.bpm_hist *= 0.92
        if conf > 0.05:
            w = np.exp(-0.5 * ((bpms - bpms[best]) / 1.5) ** 2)
            self.bpm_hist += w * conf
        hb = int(np.argmax(self.bpm_hist))
        if self.bpm_hist[hb] > 0.15:
            # parabolic refine on the histogram
            if 0 < hb < len(self.bpm_hist) - 1:
                y0, y1, y2 = self.bpm_hist[hb - 1:hb + 2]
                d = (y0 - y2) / (2 * (y0 - 2 * y1 + y2) + 1e-9)
                d = float(np.clip(d, -0.5, 0.5))
            else:
                d = 0.0
            new_bpm = float(bpms[hb] + d)
            self.bpm = new_bpm if self.bpm == 0 else self.bpm + (new_bpm - self.bpm) * 0.5
            self.period = fr * 60.0 / self.bpm
        self.bpm_conf = float(np.clip(conf * 1.6, 0.0, 1.0))

    def _align_phase(self, fi: int) -> None:
        """Comb-filter phase estimate over the onset envelope; nudges the beat predictor."""
        env = np.asarray(self.env, dtype=np.float32)
        P = self.period
        n = len(env)
        K = int(min(8, (n - 1) // max(1.0, P)))
        if K < 2 or env.max() <= 0:
            return
        phis = np.arange(int(P))
        ks = np.arange(K) * P
        idx = (n - 1 - phis[:, None] - ks[None, :]).round().astype(int)
        idx = np.clip(idx, 0, n - 1)
        wts = 0.85 ** np.arange(K)
        scores = (env[idx] * wts[None, :]).sum(axis=1)
        phi = int(np.argmax(scores))
        last_est = fi - phi
        nb = last_est + P * math.ceil((fi - last_est + 1e-6) / P)
        if self.next_beat <= 0:
            self.next_beat = nb
            return
        delta = nb - self.next_beat
        delta = (delta + P / 2) % P - P / 2
        self.next_beat += 0.5 * delta

    def _track_beats(self, fi: int) -> None:
        if self.period <= 0:
            return
        P = self.period
        if fi - getattr(self, "_last_align", -10 ** 9) >= self.frame_rate * 0.25:
            self._last_align = fi
            self._align_phase(fi)
        if self.next_beat <= 0:
            self.next_beat = fi + P
        while fi >= self.next_beat:
            if self.silent_frames < self.frame_rate * 0.4:
                self.beat_count += 1
            self.last_beat_frame = self.next_beat
            self.next_beat += P

    # -------------------------------------------------------------- snapshot
    def snapshot(self) -> AudioFeatures:
        return self.features
