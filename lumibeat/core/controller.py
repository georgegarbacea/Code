"""Application controller: owns configuration, state, audio, engine, Art-Net and the web remote.

Qt-free so it can be used by the desktop UI, the phone remote, the self-test and
unit tests alike.  Listeners are plain callables invoked from any thread.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

from ..audio.analysis import AudioAnalyzer
from ..audio.capture import AudioCapture
from ..effects import REGISTRY, ambient_effect_ids, music_effect_ids
from ..effects.custom import normalize_spec
from ..effects.palettes import PALETTES
from . import autostart
from .artnet import ArtNetOutput, NodeInfo
from .config import Config, app_data_dir, load_config, load_json, save_config, save_json
from .engine import Engine
from .mapping import TestPattern
from .party import PARTY_PRESETS
from .presets import PresetStore
from .state import MODES, ShowState, StateStore

log = logging.getLogger("lumibeat")

_RANGES = {
    "brightness": (0.0, 1.0), "intensity": (0.0, 1.5), "speed": (0.1, 3.0), "sensitivity": (0.2, 3.0),
    "duration": (0.25, 4.0), "transition_time": (0.1, 8.0), "ambient_intensity": (0.0, 1.0),
    "ambient_speed": (0.1, 3.0), "ambient_temp": (1800, 6500), "standby_level": (0.05, 1.0),
}


class Controller:
    def __init__(self, cfg: Config | None = None, data_dir=None, start_web: bool = True):
        self.data_dir = data_dir or app_data_dir()
        self.cfg_path = self.data_dir / "config.json"
        self.state_path = self.data_dir / "state.json"
        self.cfg = cfg or load_config(self.cfg_path)
        st = ShowState.from_dict(load_json(self.state_path, {}))
        self.store = StateStore(st)
        self.presets = PresetStore(self.data_dir / "presets.json")
        self.analyzer = AudioAnalyzer(48000, self.cfg.audio.block_size)
        self.analyzer.noise_gate_db = self.cfg.audio.noise_gate_db
        self.capture = AudioCapture(self.analyzer)
        self.artnet = ArtNetOutput()
        self.engine = Engine(self.cfg, self.store, self.analyzer, self.artnet)
        self.listeners: list[Callable[[str, Any], None]] = []
        self.web = None
        self._start_web = start_web
        self._save_timer: threading.Timer | None = None
        self._save_lock = threading.Lock()

    # ------------------------------------------------------------------ life
    def start(self) -> None:
        a = self.cfg.audio
        self.capture.start(a.source, a.device, a.block_size)
        if self.capture.source == "none" and a.source != "demo":
            log.warning("audio source %s unavailable: %s", a.source, self.capture.error)
        self._configure_artnet()
        self.engine.start()
        if self._start_web and self.cfg.web.enabled:
            self.start_web()
        self.emit("started", None)

    def shutdown(self) -> None:
        self.flush_state()
        try:
            self.stop_web()
        except Exception:
            pass
        self.engine.shutdown()
        self.artnet.shutdown()
        self.capture.stop()

    # ------------------------------------------------------------- listeners
    def on(self, cb: Callable[[str, Any], None]) -> None:
        self.listeners.append(cb)

    def emit(self, what: str, data: Any) -> None:
        for cb in list(self.listeners):
            try:
                cb(what, data)
            except Exception:
                log.exception("listener failed")

    # ------------------------------------------------------------------ state
    def state(self) -> ShowState:
        return self.store.snapshot()

    def set_state(self, **kw) -> dict:
        clean = {}
        for k, v in kw.items():
            if k in _RANGES:
                lo, hi = _RANGES[k]
                try:
                    v = type(lo)(min(hi, max(lo, float(v))))
                except (TypeError, ValueError):
                    continue
            if k == "mode" and v not in MODES:
                continue
            if k == "music_effect" and (v not in REGISTRY or REGISTRY[v].category not in ("music", "special")):
                continue
            if k == "ambient_scene" and v not in ambient_effect_ids():
                continue
            if k == "party_preset" and v not in PARTY_PRESETS:
                continue
            if k == "palette" and v not in PALETTES and v not in ("auto", "color"):
                continue
            if k == "studio_spec":
                v = normalize_spec(v)
            if k == "color" and (not isinstance(v, str) or not v.startswith("#") or len(v) not in (4, 7)):
                continue
            clean[k] = v
        changed = self.store.update(**clean)
        if changed:
            self.emit("state", changed)
            self._schedule_save()
        return changed

    def set_effect_param(self, effect_id: str, key: str, value: Any) -> None:
        self.store.set_effect_param(effect_id, key, value)
        self.emit("state", {"effect_params": True})
        self._schedule_save()

    def _schedule_save(self) -> None:
        with self._save_lock:
            if self._save_timer is None:
                self._save_timer = threading.Timer(1.5, self.flush_state)
                self._save_timer.daemon = True
                self._save_timer.start()

    def flush_state(self) -> None:
        with self._save_lock:
            self._save_timer = None
        try:
            save_json(self.state_path, self.store.snapshot().to_dict(persist=True))
        except OSError:
            log.exception("could not save state")

    # ------------------------------------------------------------ high level
    def toggle_led(self, on: bool | None = None) -> None:
        cur = self.store.get("led_on")
        self.set_state(led_on=(not cur) if on is None else bool(on))

    def set_strobe(self, enabled: bool) -> None:
        """Strobe effects are opt-in; the UI shows a photosensitivity warning first."""
        self.set_state(strobe_enabled=bool(enabled))

    def apply_preset(self, pid: str) -> bool:
        p = self.presets.get(pid)
        if not p:
            return False
        self.set_state(**PresetStore.apply_values(p))
        return True

    # ---------------------------------------------------------------- config
    def apply_config(self, cfg: Config, restart_audio: bool | None = None) -> None:
        old = self.cfg
        cfg.sanitize()
        self.cfg = cfg
        save_config(cfg, self.cfg_path)
        self.engine.apply_config(cfg)
        self.analyzer.noise_gate_db = cfg.audio.noise_gate_db
        if restart_audio is None:
            restart_audio = (old.audio.source, old.audio.device, old.audio.block_size) != \
                            (cfg.audio.source, cfg.audio.device, cfg.audio.block_size)
        if restart_audio:
            self.capture.start(cfg.audio.source, cfg.audio.device, cfg.audio.block_size)
        self._configure_artnet()
        if (old.web.enabled, old.web.port) != (cfg.web.enabled, cfg.web.port) or old.web.pin != cfg.web.pin:
            self.stop_web()
            if cfg.web.enabled and self._start_web:
                self.start_web()
        if autostart.is_supported() and autostart.is_enabled() != cfg.app.autostart:
            autostart.set_enabled(cfg.app.autostart)
        self.emit("config", None)

    def save_config(self) -> None:
        save_config(self.cfg, self.cfg_path)

    def _configure_artnet(self) -> None:
        n = self.cfg.network
        if not n.output_enabled and self.artnet.enabled:
            self.artnet.stop_transmission(self.engine.mapper.blackout())
        self.artnet.configure(n.output_enabled, n.controller_ip, n.interface_ip, n.art_sync,
                              n.poll_interval_s, n.use_sequence)

    def set_output_enabled(self, enabled: bool) -> None:
        cfg = self.cfg.copy()
        cfg.network.output_enabled = bool(enabled)
        self.apply_config(cfg, restart_audio=False)

    # -------------------------------------------------------------- hardware
    def discover(self, wait: float = 2.0) -> list[NodeInfo]:
        nodes = self.artnet.discover(wait)
        self.emit("nodes", nodes)
        return nodes

    def apply_node_mapping(self, node: NodeInfo) -> Config:
        """Use the controller's own port-address table (ArtPollReply SwOut) for our ports.

        Only the *start* universe of each port is reported by Art-Net; ports that need
        more than one universe continue on the following universes."""
        cfg = self.cfg.copy()
        cfg.network.controller_ip = node.ip
        for i, addr in enumerate(node.sw_out[:4]):
            cfg.ports[i].universe = int(addr)
        self.apply_config(cfg, restart_audio=False)
        return cfg

    def set_test(self, tp: TestPattern | None) -> None:
        self.engine.test = tp
        self.emit("test", tp)

    # ------------------------------------------------------------------- web
    def start_web(self) -> None:
        try:
            from ..web.server import WebRemote
        except Exception as e:  # pragma: no cover
            log.warning("web remote unavailable: %s", e)
            return
        self.web = WebRemote(self)
        self.web.start()

    def stop_web(self) -> None:
        if self.web:
            self.web.stop()
            self.web = None

    # ----------------------------------------------------------------- info
    def catalog(self) -> dict:
        from ..effects.base import effect_info
        from ..effects.palettes import PALETTE_ORDER
        from .party import PRESET_ORDER
        return {
            "music": [effect_info(REGISTRY[k]) for k in music_effect_ids()],
            "ambient": [effect_info(REGISTRY[k]) for k in ambient_effect_ids()],
            "palettes": [{"id": k, "name": PALETTES[k][0], "stops": PALETTES[k][1]} for k in PALETTE_ORDER],
            "party": [{"id": k, "name": PARTY_PRESETS[k]["name"], "desc": PARTY_PRESETS[k]["desc"]}
                      for k in PRESET_ORDER],
            "presets": [{"id": p["id"], "name": p["name"], "mode": p["mode"]} for p in self.presets.list()],
        }

    def status(self) -> dict:
        fo = self.engine.latest
        a = fo.audio
        return {
            "fps": round(self.engine.fps, 1),
            "effect": fo.effect, "effect_name": fo.effect_name, "section": fo.section, "style": fo.style,
            "beats_left": fo.beats_left, "standby": fo.standby, "power_w": round(fo.power_w, 1),
            "bpm": round(a.bpm, 1), "bpm_conf": round(a.bpm_confidence, 2), "level": round(a.level, 3),
            "bass": round(a.bass, 3), "mid": round(a.mid, 3), "high": round(a.high, 3),
            "beat_count": a.beat_count, "silent": a.silent,
            "audio": self.capture.info(), "artnet": self.artnet.stats(),
            "output_enabled": self.cfg.network.output_enabled, "time": time.time(),
        }
