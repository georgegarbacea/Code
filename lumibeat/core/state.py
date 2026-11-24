"""Live show state shared by the UI, the phone remote and the engine."""
from __future__ import annotations

import copy
import threading
from dataclasses import asdict, dataclass, field, fields
from typing import Any

from ..effects.custom import default_spec, normalize_spec

MODES = ("music", "party", "ambient", "studio")
MODE_LABELS = {"music": "Music", "party": "Party", "ambient": "Ambient", "studio": "Studio"}


@dataclass
class ShowState:
    led_on: bool = True
    mode: str = "music"
    music_effect: str = "spectrum_sym"
    palette: str = "auto"                      # auto = the effect's own palette
    custom_palette: list[str] = field(default_factory=lambda: ["#7c5cff", "#22d3ee", "#ff4fa3", "#7c5cff"])
    effect_params: dict[str, dict] = field(default_factory=dict)
    ambient_scene: str = "amb_fireplace"
    ambient_temp: int = 2700
    ambient_intensity: float = 0.8
    ambient_speed: float = 1.0
    party_preset: str = "auto_dj"
    studio_spec: dict = field(default_factory=default_spec)
    brightness: float = 0.8
    intensity: float = 1.0
    speed: float = 1.0
    sensitivity: float = 1.0
    duration: float = 1.0                      # party: effect duration multiplier
    transition: str = "crossfade"
    transition_time: float = 1.2
    strobe_enabled: bool = False               # never persisted: always off at start-up
    symmetric: bool = True
    auto_sensitivity: bool = True
    standby_enabled: bool = True
    standby_scene: str = "relax"
    standby_level: float = 0.35
    color: str = "#ff8a3d"

    PERSIST_EXCLUDE = ("strobe_enabled",)

    def to_dict(self, persist: bool = False) -> dict[str, Any]:
        d = asdict(self)
        if persist:
            for k in self.PERSIST_EXCLUDE:
                d.pop(k, None)
        return d

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "ShowState":
        s = ShowState()
        names = {f.name for f in fields(s)}
        for k, v in (d or {}).items():
            if k in names and k not in ShowState.PERSIST_EXCLUDE:
                try:
                    cur = getattr(s, k)
                    if isinstance(cur, bool):
                        v = bool(v)
                    elif isinstance(cur, int):
                        v = int(v)
                    elif isinstance(cur, float):
                        v = float(v)
                    setattr(s, k, v)
                except (TypeError, ValueError):
                    pass
        if s.mode not in MODES:
            s.mode = "music"
        s.studio_spec = normalize_spec(s.studio_spec)
        return s


class StateStore:
    """Thread-safe holder; ``snapshot()`` gives the engine a consistent copy."""

    def __init__(self, state: ShowState | None = None):
        self._lock = threading.RLock()
        self._s = state or ShowState()
        self.version = 0

    def snapshot(self) -> ShowState:
        with self._lock:
            return copy.deepcopy(self._s)

    def get(self, key: str) -> Any:
        with self._lock:
            return copy.deepcopy(getattr(self._s, key))

    def update(self, **kw) -> dict[str, Any]:
        changed = {}
        with self._lock:
            for k, v in kw.items():
                if not hasattr(self._s, k):
                    continue
                if getattr(self._s, k) != v:
                    setattr(self._s, k, copy.deepcopy(v))
                    changed[k] = v
            if changed:
                self.version += 1
        return changed

    def set_effect_param(self, effect_id: str, key: str, value: Any) -> None:
        with self._lock:
            d = dict(self._s.effect_params.get(effect_id, {}))
            d[key] = value
            self._s.effect_params = dict(self._s.effect_params, **{effect_id: d})
            self.version += 1
