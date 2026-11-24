"""Virtual matrix -> physical pixels -> Art-Net universes.

* every profile is resampled from the virtual height to its real pixel count
* the DATA direction (↑ / ↓ serpentine wiring) is compensated, so row 0 of the
  virtual matrix is always the physical bottom
* profiles are concatenated per port in DATA-chain order
* the port stream is split into universes exactly as configured (start universe,
  start channel, pixels per universe) - a port is NOT assumed to be one universe
* colour order, white balance, gamma, global brightness ceiling and an
  electrical power limiter are applied here
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .config import Config, NUM_PROFILES

# WS2811 @ 800 kHz: 24 bit * 1.25 us = 30 us per pixel, + >=280 us reset latch
WS2811_US_PER_PIXEL = 30.0
WS2811_RESET_US = 300.0

_ORDER_IDX = {
    "RGB": (0, 1, 2), "RBG": (0, 2, 1), "GRB": (1, 0, 2),
    "GBR": (1, 2, 0), "BRG": (2, 0, 1), "BGR": (2, 1, 0),
}


@dataclass
class Segment:
    profile: int
    port: int          # 0-based
    start: int         # global pixel index of the first *lit* pixel of this profile
    skip: int
    pixels: int
    data_up: bool


@dataclass
class UniverseSlice:
    universe: int
    channel_offset: int     # 0-based channel inside the universe
    port: int               # 0-based port
    first_pixel: int        # pixel index inside the port stream
    count: int


@dataclass
class MapReport:
    ok: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    info: list[str] = field(default_factory=list)
    port_pixels: list[int] = field(default_factory=list)
    port_universes: list[list[int]] = field(default_factory=list)
    max_fps_ws2811: float = 0.0
    total_pixels: int = 0


@dataclass
class TestPattern:
    """Calibration patterns that bypass the effects and address real pixels."""

    kind: str = "off"            # off | solid | pixel | count | direction | ports | marks | blackout
    profile: int = -1            # -1 = all profiles
    color: tuple[float, float, float] = (1.0, 1.0, 1.0)
    index: int = 0               # pixel position (from bottom) or count
    t: float = 0.0               # animation time for direction test


class OutputMapper:
    def __init__(self, cfg: Config):
        self.rebuild(cfg)

    # ------------------------------------------------------------------ setup
    def rebuild(self, cfg: Config) -> None:
        self.cfg = cfg
        self.rows = cfg.wall.matrix_rows
        self.segments: list[Segment] = []
        self.port_len = [0, 0, 0, 0]
        self.port_start = [0, 0, 0, 0]
        chains: list[list] = [[], [], [], []]
        for p in cfg.profiles[:NUM_PROFILES]:
            chains[p.port - 1].append(p)
        g = 0
        for port in range(4):
            self.port_start[port] = g
            chain = sorted(chains[port], key=lambda pr: (pr.chain_pos, pr.index))
            off = 0
            for pr in chain:
                self.segments.append(
                    Segment(pr.index, port, g + off + pr.skip_pixels, pr.skip_pixels, pr.pixels, pr.data_up)
                )
                off += pr.skip_pixels + pr.pixels
            self.port_len[port] = off
            g += off
        self.total = g

        n = max(1, g)
        self.g_col = np.zeros(n, dtype=np.int32)
        self.g_i0 = np.zeros(n, dtype=np.int32)
        self.g_i1 = np.zeros(n, dtype=np.int32)
        self.g_w = np.zeros(n, dtype=np.float32)
        self.g_gain = np.zeros((n, 3), dtype=np.float32)   # 0 for skipped / disabled pixels
        self.g_trim = np.zeros((n, 3), dtype=np.float32)   # trims only (tests light disabled profiles too)
        self.g_wpp = np.zeros(n, dtype=np.float32)          # watts per pixel at full white
        self.g_pos = np.zeros(n, dtype=np.int32)            # position from the bottom (physical)
        self.g_prof = np.full(n, -1, dtype=np.int32)
        self.g_data_index = np.zeros(n, dtype=np.int32)     # index in the profile's data order
        rows = self.rows
        for s in self.segments:
            pr = cfg.profiles[s.profile]
            j = np.arange(s.pixels)
            pos = j if s.data_up else (s.pixels - 1 - j)
            v = (pos + 0.5) / s.pixels * rows - 0.5
            v = np.clip(v, 0, rows - 1)
            i0 = np.floor(v).astype(np.int32)
            i1 = np.minimum(i0 + 1, rows - 1)
            sl = slice(s.start, s.start + s.pixels)
            self.g_col[sl] = s.profile
            self.g_i0[sl] = i0
            self.g_i1[sl] = i1
            self.g_w[sl] = (v - i0).astype(np.float32)
            trim = np.array([pr.gain_r, pr.gain_g, pr.gain_b], np.float32) * pr.brightness
            self.g_trim[sl] = trim
            if pr.enabled:
                self.g_gain[sl] = trim
            self.g_wpp[sl] = cfg.output.watts_per_meter * (pr.length_cm / 100.0) / max(1, s.pixels)
            self.g_pos[sl] = pos
            self.g_prof[sl] = s.profile
            self.g_data_index[sl] = j
        self.g_w3 = self.g_w[:, None]

        # universe slices
        self.slices: list[UniverseSlice] = []
        self.port_universes: list[list[int]] = []
        for port in range(4):
            pc = cfg.ports[port]
            us: list[int] = []
            remaining = self.port_len[port]
            first = 0
            uni = pc.universe
            off = (pc.start_channel - 1)
            while remaining > 0:
                cap = min(pc.pixels_per_universe, (512 - off) // 3)
                if cap <= 0:
                    uni += 1
                    off = 0
                    continue
                cnt = min(cap, remaining)
                self.slices.append(UniverseSlice(uni, off, port, first, cnt))
                us.append(uni)
                first += cnt
                remaining -= cnt
                uni += 1
                off = 0
            self.port_universes.append(us)
        self.universe_len: dict[int, int] = {}
        for sl_ in self.slices:
            end = sl_.channel_offset + sl_.count * 3
            self.universe_len[sl_.universe] = max(self.universe_len.get(sl_.universe, 0), end)
        for u in list(self.universe_len):
            ln = self.universe_len[u]
            self.universe_len[u] = min(512, max(2, ln + (ln & 1)))
        self._order = [_ORDER_IDX.get(cfg.ports[p].color_order, (0, 1, 2)) for p in range(4)]
        self._gamma = float(cfg.output.gamma)
        self.last_power_w = 0.0
        self.last_scale = 1.0

    # --------------------------------------------------------------- validate
    def report(self) -> MapReport:
        cfg = self.cfg
        r = MapReport(port_pixels=list(self.port_len), port_universes=[list(u) for u in self.port_universes])
        r.total_pixels = self.total
        for port in range(4):
            pc = cfg.ports[port]
            if self.port_len[port] > pc.max_pixels:
                r.errors.append(
                    f"Portul {port + 1}: {self.port_len[port]} pixeli depășesc capacitatea declarată de {pc.max_pixels}."
                )
            chain = [p for p in cfg.profiles if p.port == port + 1]
            pos = [p.chain_pos for p in chain]
            if len(set(pos)) != len(pos):
                r.warnings.append(f"Portul {port + 1}: poziții duplicate în lanțul DATA ({pos}).")
        if self.total > 4096:
            r.errors.append(f"Total {self.total} pixeli > 4096 (capacitatea declarată a SP801E).")
        # overlap detection
        used: dict[int, list[tuple[int, int, int]]] = {}
        for s in self.slices:
            a, b = s.channel_offset, s.channel_offset + s.count * 3
            for (a2, b2, p2) in used.get(s.universe, []):
                if a < b2 and a2 < b:
                    r.errors.append(
                        f"Universul {s.universe}: canalele portului {s.port + 1} se suprapun cu portul {p2 + 1}."
                    )
            used.setdefault(s.universe, []).append((a, b, s.port))
        worst = max(self.port_len) if self.port_len else 0
        t_us = worst * WS2811_US_PER_PIXEL + WS2811_RESET_US
        r.max_fps_ws2811 = 1e6 / t_us if worst else 0.0
        r.info.append(
            f"Cel mai lung lanț: {worst} pixeli → refresh WS2811 maxim teoretic ≈ {r.max_fps_ws2811:.0f} FPS."
        )
        r.info.append(f"Universuri folosite: {sorted(self.universe_len)}")
        r.ok = not r.errors
        return r

    def hardware_fps_cap(self) -> float:
        worst = max(self.port_len) if self.port_len else 0
        if not worst:
            return 60.0
        return 1e6 / (worst * WS2811_US_PER_PIXEL + WS2811_RESET_US)

    # ------------------------------------------------------------------- map
    def physical_colors(self, frame: np.ndarray) -> np.ndarray:
        """Resample the virtual matrix to every physical pixel (float 0..1, data order)."""
        a = frame[self.g_col, self.g_i0]
        b = frame[self.g_col, self.g_i1]
        return a + (b - a) * self.g_w3

    def test_colors(self, tp: TestPattern) -> np.ndarray:
        c = np.zeros((max(1, self.total), 3), dtype=np.float32)
        col = np.array(tp.color, dtype=np.float32)
        sel = np.ones(len(c), bool) if tp.profile < 0 else (self.g_prof == tp.profile)
        sel &= self.g_prof >= 0
        if tp.kind == "solid":
            c[sel] = col
        elif tp.kind == "pixel":
            c[sel & (self.g_pos == tp.index)] = col
        elif tp.kind == "count":
            # light the first N pixels in DATA order - the end of the lit run shows the real length
            c[sel & (self.g_data_index < tp.index)] = col
            c[sel & (self.g_data_index == tp.index - 1)] = (1.0, 0.0, 0.0)
        elif tp.kind == "direction":
            # bottom red -> top blue, plus a white dot travelling upward
            for s in self.segments:
                if tp.profile >= 0 and s.profile != tp.profile:
                    continue
                sl = slice(s.start, s.start + s.pixels)
                pos = self.g_pos[sl].astype(np.float32) / max(1, s.pixels - 1)
                c[sl, 0] = (1 - pos) * 0.6
                c[sl, 2] = pos * 0.6
                dot = int((tp.t * 0.5 % 1.0) * s.pixels)
                c[sl][np.abs(self.g_pos[sl] - dot) <= 1] = (1, 1, 1)
        elif tp.kind == "ports":
            pal = np.array([(1, 0, 0), (0, 1, 0), (0, 0, 1), (1, 1, 1)], np.float32) * 0.6
            for s in self.segments:
                c[s.start:s.start + s.pixels] = pal[s.port]
        elif tp.kind == "marks":
            m = sel & (self.g_pos % 10 == 0)
            c[sel] = (0.05, 0.05, 0.05)
            c[m] = (1, 1, 1)
            c[sel & (self.g_pos % 50 == 0)] = (1, 0, 0)
        return c

    def map(self, frame: np.ndarray | None, brightness: float, test: TestPattern | None = None) -> dict[int, bytes]:
        if self.total == 0:
            return {}
        if test is not None and test.kind not in ("off", ""):
            lin = self.test_colors(test) * self.g_trim  # trims apply, disabled profiles stay testable
            lin *= self.cfg.output.max_brightness
        else:
            lin = self.physical_colors(frame) * self.g_gain
            lin *= float(np.clip(brightness, 0, 1)) * self.cfg.output.max_brightness
        np.clip(lin, 0.0, 1.0, out=lin)
        if self._gamma != 1.0:
            lin = lin ** self._gamma
        # power estimate: PWM duty is proportional to current
        power = float(np.dot(lin.mean(axis=1), self.g_wpp))
        scale = 1.0
        lim = self.cfg.output.power_limit_w
        if lim > 0 and power > lim:
            scale = lim / power
            lin *= scale
            power = lim
        self.last_power_w = power
        self.last_scale = scale
        out8 = (lin * 255.0 + 0.5).astype(np.uint8)
        streams = []
        for port in range(4):
            a = self.port_start[port]
            b = a + self.port_len[port]
            seg = out8[a:b][:, self._order[port]]
            streams.append(seg.reshape(-1))
        unis: dict[int, bytearray] = {u: bytearray(n) for u, n in self.universe_len.items()}
        for s in self.slices:
            data = streams[s.port][s.first_pixel * 3:(s.first_pixel + s.count) * 3]
            unis[s.universe][s.channel_offset:s.channel_offset + len(data)] = data.tobytes()
        return {u: bytes(b) for u, b in unis.items()}

    def blackout(self) -> dict[int, bytes]:
        return {u: bytes(n) for u, n in self.universe_len.items()}
