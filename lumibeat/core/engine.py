"""Show engine: renders the virtual matrix at the simulator frame rate and feeds Art-Net.

Runs in its own thread so the LEDs keep playing while the window is minimised or
hidden in the tray.  The UI and the phone remote only read ``engine.latest``.
"""
from __future__ import annotations

import math
import threading
import time
import traceback
from collections import deque
from dataclasses import dataclass, field, replace

import numpy as np

from ..audio.analysis import AudioAnalyzer, AudioFeatures
from ..effects import REGISTRY, Ctx, LayeredEffect, Palette
from ..effects.palettes import PALETTES, kelvin_to_rgb, hex2rgb
from ..effects.transitions import Transition
from .artnet import ArtNetOutput
from .config import Config
from .geometry import Geometry, build_geometry
from .mapping import OutputMapper, TestPattern
from .party import SECTION_LABELS, PartyDirector
from .state import StateStore


@dataclass
class FrameOut:
    preview: np.ndarray                 # (12, rows, 3) float 0..1 as it will look on the wall
    t: float = 0.0
    fps: float = 0.0
    power_w: float = 0.0
    power_scale: float = 1.0
    effect: str = ""
    effect_name: str = ""
    palette: str = ""
    section: str = ""
    style: str = ""
    beats_left: int = 0
    standby: bool = False
    audio: AudioFeatures = field(default_factory=AudioFeatures)
    safety_limited: bool = False
    test: bool = False


_REL_6500 = np.array(kelvin_to_rgb(6500), np.float32)


class Engine:
    def __init__(self, cfg: Config, store: StateStore, analyzer: AudioAnalyzer, artnet: ArtNetOutput):
        self.store = store
        self.analyzer = analyzer
        self.artnet = artnet
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._running = False
        self.director = PartyDirector()
        self.test: TestPattern | None = None
        self.scan_universe: int | None = None    # diagnostic: light one universe with dim white
        self.error = ""
        self.fps = 0.0
        self._last_counts = (0, 0, 0)
        self._clock0 = time.perf_counter()
        self.apply_config(cfg)
        self.latest = FrameOut(preview=self.g.zeros())

    # ---------------------------------------------------------------- config
    def apply_config(self, cfg: Config) -> None:
        with self._lock:
            self.cfg = cfg
            self.g: Geometry = build_geometry(cfg)
            self.mapper = OutputMapper(cfg)
            self.sim_fps = cfg.app.sim_fps
            self._reset_render()

    def _reset_render(self) -> None:
        self.cur = None
        self.cur_key = ""
        self.prev = None
        self.trans: Transition | None = None
        self.pal = Palette.named("neon")
        self.pal_target = self.pal
        self.pal_key = ""
        self.pal_k = 1.0
        self.pal_from = self.pal
        self.led_level = 1.0
        self.prev_frame = self.g.zeros()
        self.lum_slow = 0.0
        self.lum_prev = 0.0
        self.flashes: deque = deque(maxlen=16)
        self.limit_until = 0.0
        self._last_sent: dict[int, bytes] | None = None
        self._last_send_t = 0.0
        self._standby_level = 1.0

    # ------------------------------------------------------------- lifecycle
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, name="show-engine", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)

    def shutdown(self) -> None:
        """Controlled stop: fade, blackout the installation, close the socket."""
        self.stop()
        try:
            self.artnet.stop_transmission(self.mapper.blackout())
        except Exception:
            pass

    def _run(self) -> None:
        last = time.perf_counter()
        frames = 0
        t_fps = last
        while self._running:
            period = 1.0 / max(10, self.sim_fps)
            now = time.perf_counter()
            dt = min(0.1, now - last)
            last = now
            try:
                with self._lock:
                    self.step(dt, now)
                self.error = ""
            except Exception as e:  # never let one bad frame kill the show
                self.error = f"{type(e).__name__}: {e}"
                traceback.print_exc()
                with self._lock:
                    self.cur = None
                    self.cur_key = ""
            frames += 1
            if now - t_fps >= 1.0:
                self.fps = frames / (now - t_fps)
                frames, t_fps = 0, now
            sleep = period - (time.perf_counter() - now)
            if sleep > 0:
                time.sleep(sleep)

    # ------------------------------------------------------------------ frame
    def _make_effect(self, kind: str, eff_id: str, params: dict, spec: dict | None = None):
        if kind == "studio":
            return LayeredEffect(self.g, spec or {})
        cls = REGISTRY.get(eff_id) or REGISTRY["spectrum_sym"]
        return cls(self.g, params)

    def _palette_for(self, name: str, effect_cls, custom: list[str], color: str) -> tuple[str, Palette]:
        if name in ("", "auto"):
            name = getattr(effect_cls, "palette", "neon")
        if name == "custom":
            return "custom:" + ",".join(custom), Palette.named("custom", custom)
        if name == "color":
            from ..effects.palettes import single_color_stops
            stops = single_color_stops(color)
            return "color:" + color, Palette.named("custom", stops)
        if name not in PALETTES:
            name = "neon"
        return name, Palette.named(name)

    def step(self, dt: float, now: float | None = None) -> FrameOut:
        now = time.perf_counter() if now is None else now
        st = self.store.snapshot()
        g = self.g
        self.analyzer.sensitivity = st.sensitivity
        self.analyzer.auto_gain = st.auto_sensitivity
        f = self.analyzer.snapshot()
        bc, kc, dc = f.beat_count, f.kick_count, f.drop_count
        lb, lk, ld = self._last_counts
        beat, kick, drop = bc != lb, kc != lk, dc != ld
        self._last_counts = (bc, kc, dc)

        section = style = ""
        beats_left = 0
        standby = False
        trans_req = None
        speed = st.speed
        tint_rel = None
        intensity = st.intensity
        brightness = st.brightness

        # ---- decide what to show
        if st.mode == "party":
            dec = self.director.update(f, beat, drop, dt, st.party_preset, st.duration, st.standby_enabled,
                                       st.standby_scene, st.strobe_enabled)
            eff_id, pal_name = dec.effect, dec.palette
            params = st.effect_params.get(eff_id, {})
            key = f"party:{eff_id}"
            kind = "effect"
            trans_req = dec.transition
            section, style, beats_left, standby = SECTION_LABELS.get(dec.section, dec.section), dec.style, \
                dec.beats_left, dec.standby
            speed = st.speed * dec.speed
        else:
            if self.director.effect:
                self.director.reset()
            if st.mode == "ambient":
                eff_id = st.ambient_scene if st.ambient_scene in REGISTRY else "amb_fireplace"
                pal_name = "auto" if eff_id != "solid_color" else "color"
                params = st.effect_params.get(eff_id, {})
                kind = "effect"
                key = f"ambient:{eff_id}"
                speed = st.ambient_speed
                brightness = st.brightness * st.ambient_intensity
                intensity = 1.0
                temp_rgb = np.array(kelvin_to_rgb(st.ambient_temp), np.float32)
                if not getattr(REGISTRY[eff_id], "uses_temp", False) and eff_id != "solid_color":
                    tint_rel = temp_rgb / np.maximum(_REL_6500, 1e-3)
                    tint_rel = tint_rel / tint_rel.max()
                    # keep neutral scenes neutral at 6500 K; stronger tint as temperature falls/rises
            elif st.mode == "studio":
                eff_id = "custom"
                pal_name = "auto"
                params = {}
                kind = "studio"
                key = "studio:" + LayeredEffect.structure_key(st.studio_spec)
            else:
                eff_id = st.music_effect if st.music_effect in REGISTRY else "spectrum_sym"
                pal_name = st.palette
                params = st.effect_params.get(eff_id, {})
                kind = "effect"
                key = f"music:{eff_id}"

        if st.mode != "party" and self.director.standby:
            self.director.standby = False

        # strobe safety: never show the strobe effect unless explicitly enabled
        if eff_id == "strobe" and not st.strobe_enabled:
            eff_id = "bass_pulse"
            key += ":safe"

        # ---- effect instance / transitions
        if key != self.cur_key or self.cur is None:
            new = self._make_effect(kind, eff_id, params, st.studio_spec if kind == "studio" else None)
            if self.cur is not None:
                tk, tt = trans_req or ((st.studio_spec.get("transition", {}).get("type", st.transition),
                                         st.studio_spec.get("transition", {}).get("time", st.transition_time))
                                        if kind == "studio" else (st.transition, st.transition_time))
                self.prev = self.cur
                self.trans = Transition(tk, tt, g)
            self.cur = new
            self.cur_key = key
        elif kind == "effect" and params:
            for k, v in params.items():
                if k in self.cur.p:
                    self.cur.p[k] = v
        elif kind == "studio" and isinstance(self.cur, LayeredEffect):
            self.cur.update_spec(st.studio_spec)

        # ---- palette (smoothly blended)
        effect_cls = type(self.cur)
        pkey, ptarget = self._palette_for(pal_name, effect_cls, st.custom_palette, st.color)
        if pkey != self.pal_key:
            self.pal_from = self.pal
            self.pal_target = ptarget
            self.pal_key = pkey
            self.pal_k = 0.0
        if self.pal_k < 1.0:
            self.pal_k = min(1.0, self.pal_k + dt / 1.2)
            self.pal = self.pal_from.blend(self.pal_target, self.pal_k)
        else:
            self.pal = self.pal_target

        color = hex2rgb(st.color)
        ctx = Ctx(g=g, dt=dt, audio=f, palette=self.pal, beat=beat, kick=kick, drop=drop, intensity=intensity,
                  speed=speed, strobe_ok=st.strobe_enabled, color=color,
                  tint=kelvin_to_rgb(st.ambient_temp), time=now - self._clock0)

        frame = self.cur.frame(ctx)
        if self.trans is not None and self.prev is not None:
            pal_prev = self.pal
            a = self.prev.frame(replace(ctx, palette=pal_prev))
            self.trans.step(dt)
            frame = self.trans.mix(a, frame)
            if self.trans.done:
                self.trans = None
                self.prev = None
        if tint_rel is not None:
            frame = frame * tint_rel
        if (st.symmetric and st.mode == "party") and not standby:
            # left/right synchronisation: mirror the left group onto the right group
            right = g.side > 0
            frame = frame.copy()
            frame[right] = 0.5 * frame[right] + 0.5 * frame[g.mirror[right]]
        frame = np.clip(frame, 0.0, 1.0).astype(np.float32)

        # ---- photosensitivity guard (when strobe is disabled)
        safety = False
        lum = float(frame.mean())
        if not st.strobe_enabled:
            self.lum_slow += (lum - self.lum_slow) * min(1.0, dt * 2.0)
            if lum > self.lum_slow + 0.25 and self.lum_prev <= self.lum_slow + 0.12:
                self.flashes.append(now)
            recent = [t for t in self.flashes if now - t < 1.0]
            if len(recent) >= 3:
                self.limit_until = now + 1.0
            if now < self.limit_until:
                safety = True
                max_rise = 2.5 * dt
                frame = np.minimum(frame, self.prev_frame + max_rise)
        self.lum_prev = float(frame.mean())
        self.prev_frame = frame

        # ---- master level: LED on/off fade, standby dimming
        target = 1.0 if st.led_on else 0.0
        self.led_level += (target - self.led_level) * min(1.0, dt * 5.0)
        if abs(self.led_level - target) < 0.002:
            self.led_level = target
        sb_target = st.standby_level if standby else 1.0
        self._standby_level += (sb_target - self._standby_level) * min(1.0, dt * 1.0)
        level = brightness * self.led_level * self._standby_level

        # ---- output
        test = self.test
        scan = self.scan_universe
        if scan is not None:
            universes = {int(scan): bytes([60]) * 510 + b"\x00\x00"}
            preview = self.g.zeros()
            if self.artnet.enabled and now - self._last_send_t > 1 / 25:
                if self.artnet.send_frame(universes):
                    self._last_send_t = now
            out = FrameOut(preview=preview, t=now - self._clock0, fps=self.fps, effect="scan",
                           effect_name=f"Scanare univers {scan}", audio=f, test=True)
            self.latest = out
            return out
        if test is not None and test.kind not in ("", "off"):
            test.t = now - self._clock0
            universes = self.mapper.map(None, 1.0, test)
            preview = self.g.zeros() if test.kind in ("chain", "chaincount") else self._test_preview(test)
        else:
            universes = self.mapper.map(frame, level)
            preview = frame * (level * self.cfg.output.max_brightness * self.mapper.last_scale)
        self._maybe_send(universes, now)

        eff_name = getattr(self.cur, "name", eff_id)
        if kind == "studio":
            eff_name = st.studio_spec.get("name", "Studio")
        out = FrameOut(
            preview=preview.astype(np.float32), t=now - self._clock0, fps=self.fps,
            power_w=self.mapper.last_power_w, power_scale=self.mapper.last_scale, effect=eff_id,
            effect_name=eff_name, palette=pal_name, section=section, style=style, beats_left=beats_left,
            standby=standby, audio=f, safety_limited=safety, test=test is not None and test.kind != "off",
        )
        self.latest = out
        return out

    def _maybe_send(self, universes: dict[int, bytes], now: float) -> None:
        net = self.cfg.network
        if not self.artnet.enabled or not universes:
            return
        fps = min(float(net.target_fps), self.mapper.hardware_fps_cap())
        if net.adaptive_fps:
            fps *= self.artnet.fps_scale
        interval = 1.0 / max(1.0, fps)
        if now - self._last_send_t < interval:
            return
        if net.send_on_change and self._last_sent == universes and \
                now - self._last_send_t < 1.0 / max(0.2, net.keepalive_hz):
            return
        if self.artnet.send_frame(universes):
            self._last_sent = universes
            self._last_send_t = now

    def _test_preview(self, tp: TestPattern) -> np.ndarray:
        """Show the calibration pattern on the simulator, in physical orientation."""
        cols = self.mapper.test_colors(tp)
        out = self.g.zeros()
        rows = self.g.rows
        for s in self.mapper.segments:
            seg = cols[s.start:s.start + s.pixels]
            pos = self.mapper.g_pos[s.start:s.start + s.pixels]
            ordered = np.zeros_like(seg)
            ordered[pos] = seg
            src = (np.arange(s.pixels) + 0.5) / s.pixels
            dst = (np.arange(rows) + 0.5) / rows
            if s.pixels >= rows:
                # many physical pixels per row: max-pool so single test pixels stay visible
                idx = np.minimum((src * rows).astype(int), rows - 1)
                for ch in range(3):
                    np.maximum.at(out[s.profile, :, ch], idx, ordered[:, ch])
            else:
                for ch in range(3):
                    out[s.profile, :, ch] = np.interp(dst, src, ordered[:, ch])
        return out * self.cfg.output.max_brightness
