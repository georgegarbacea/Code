"""User presets: save / load / delete / export / import."""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from .config import app_data_dir, load_json, save_json
from .state import ShowState

# state fields captured by a preset, per mode
_COMMON = ["brightness", "intensity", "speed", "sensitivity", "transition", "transition_time", "symmetric",
           "palette", "custom_palette", "color"]
FIELDS = {
    "music": _COMMON + ["music_effect", "effect_params"],
    "party": _COMMON + ["party_preset", "duration", "standby_enabled", "standby_scene", "standby_level",
                        "auto_sensitivity"],
    "ambient": ["brightness", "ambient_scene", "ambient_temp", "ambient_intensity", "ambient_speed", "color",
                "effect_params"],
    "studio": _COMMON + ["studio_spec"],
}
FORMAT = "lumibeat-preset/1"


class PresetStore:
    def __init__(self, path: Path | None = None):
        self.path = path or app_data_dir() / "presets.json"
        data = load_json(self.path, {"presets": []})
        self.presets: list[dict[str, Any]] = [p for p in data.get("presets", []) if self._valid(p)]

    @staticmethod
    def _valid(p: Any) -> bool:
        return isinstance(p, dict) and isinstance(p.get("name"), str) and p.get("mode") in FIELDS \
            and isinstance(p.get("data"), dict)

    def save(self) -> None:
        save_json(self.path, {"format": FORMAT, "presets": self.presets})

    def list(self, mode: str | None = None) -> list[dict]:
        return [p for p in self.presets if mode is None or p["mode"] == mode]

    def create(self, name: str, state: ShowState, mode: str | None = None) -> dict:
        mode = mode or state.mode
        d = state.to_dict(persist=True)
        data = {k: d[k] for k in FIELDS[mode] if k in d}
        p = {"id": uuid.uuid4().hex[:12], "name": name.strip() or "Presetare", "mode": mode,
             "created": time.strftime("%Y-%m-%d %H:%M"), "data": data}
        # replace a preset with the same name and mode
        self.presets = [x for x in self.presets if not (x["name"] == p["name"] and x["mode"] == mode)]
        self.presets.append(p)
        self.save()
        return p

    def delete(self, pid: str) -> None:
        self.presets = [p for p in self.presets if p["id"] != pid]
        self.save()

    def get(self, pid: str) -> dict | None:
        return next((p for p in self.presets if p["id"] == pid), None)

    @staticmethod
    def apply_values(p: dict) -> dict[str, Any]:
        """Values to push into the StateStore (mode included)."""
        vals = {k: v for k, v in p["data"].items() if k in FIELDS[p["mode"]]}
        vals["mode"] = p["mode"]
        return vals

    # ------------------------------------------------------------ files
    def export(self, path: str | Path, ids: list[str] | None = None) -> int:
        items = [p for p in self.presets if ids is None or p["id"] in ids]
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"format": FORMAT, "presets": items}, fh, indent=2, ensure_ascii=False)
        return len(items)

    def import_file(self, path: str | Path) -> int:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        items = data.get("presets", [data] if "mode" in data else [])
        n = 0
        for p in items:
            if not self._valid(p):
                continue
            p = dict(p)
            p["id"] = uuid.uuid4().hex[:12]
            self.presets = [x for x in self.presets if not (x["name"] == p["name"] and x["mode"] == p["mode"])]
            self.presets.append(p)
            n += 1
        self.save()
        return n
