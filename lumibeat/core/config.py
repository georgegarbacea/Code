"""Configuration model for LumiBeat Studio.

Everything the user can edit (hardware layout, Art-Net mapping, audio source,
web remote, application behaviour) lives here and is persisted as JSON in the
per-user application data directory.
"""
from __future__ import annotations

import copy
import json
import os
import secrets
import sys
import threading
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

APP_NAME = "LumiBeat Studio"
APP_VERSION = "1.0.0"
NUM_PROFILES = 12

COLOR_ORDERS = ("RGB", "RBG", "GRB", "GBR", "BRG", "BGR")


def app_data_dir() -> Path:
    """Directory used for settings, presets and the uploaded wall photo."""
    override = os.environ.get("LUMIBEAT_HOME")
    if override:
        p = Path(override)
    elif sys.platform == "win32":
        p = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / APP_NAME
    elif sys.platform == "darwin":
        p = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        p = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "lumibeat-studio"
    p.mkdir(parents=True, exist_ok=True)
    return p


# --------------------------------------------------------------------------------------
# Hardware model
# --------------------------------------------------------------------------------------
@dataclass
class ProfileConfig:
    """One vertical aluminium LED profile (one column of the virtual matrix)."""

    index: int = 0                 # 0..11, left to right
    name: str = ""
    enabled: bool = True
    port: int = 1                  # SP801E output port 1..4
    chain_pos: int = 0             # position in that port's DATA chain (0 = first)
    data_up: bool = True           # True: DATA enters at the bottom (pixel 0 is at the bottom)
    pixels: int = 84               # real addressable pixels (WS2811 ICs) - set by calibration
    skip_pixels: int = 0           # pixels at the start of this segment that must stay dark
    length_cm: float = 140.0
    x_cm: float = 0.0              # centre of the profile, measured from the left wall edge
    bottom_cm: float = 40.0        # height of the lowest LED above the floor
    brightness: float = 1.0        # per-profile brightness trim
    gain_r: float = 1.0            # white-balance trims
    gain_g: float = 1.0
    gain_b: float = 1.0
    view: list[float] | None = None  # [x_bottom, y_bottom, x_top, y_top] normalised over the wall image

    @property
    def label(self) -> str:
        return self.name or f"Profil {self.index + 1}"


@dataclass
class PortConfig:
    """Physical output port of the controller and its Art-Net mapping."""

    number: int = 1
    universe: int = 0              # Art-Net Port-Address (15 bit: Net<<8 | SubNet<<4 | Universe)
    start_channel: int = 1         # 1-based DMX start channel inside the first universe
    pixels_per_universe: int = 170 # 170 RGB pixels = 510 channels
    color_order: str = "RGB"
    max_pixels: int = 1024         # declared controller capacity (to be verified)


@dataclass
class WallConfig:
    wall_width_cm: float = 600.0
    wall_height_cm: float = 270.0
    profile_spacing_cm: float = 30.0      # centre-to-centre distance between neighbouring profiles
    fireplace_gap_cm: float = 190.0       # centre-to-centre distance between profile 6 and 7
    fireplace_width_cm: float = 150.0
    fireplace_height_cm: float = 60.0
    fireplace_bottom_cm: float = 55.0
    matrix_rows: int = 84                 # virtual matrix height (pixels per column)
    photo_path: str = ""                  # optional real photo of the wall
    photo_brightness: float = 0.55        # how bright the photo is shown when LEDs are off


@dataclass
class OutputConfig:
    max_brightness: float = 0.85          # global brightness ceiling (0..1)
    power_limit_w: float = 240.0          # estimated electrical limit
    watts_per_meter: float = 15.0         # strip consumption at full white
    gamma: float = 2.0
    supply_w: float = 500.0


@dataclass
class NetworkConfig:
    output_enabled: bool = False          # False = simulator only
    controller_ip: str = ""               # unicast target; empty = broadcast on interface
    interface_ip: str = ""                # local interface to bind; empty = automatic
    target_fps: int = 40
    adaptive_fps: bool = True
    send_on_change: bool = True           # reduce traffic when the frame is static
    keepalive_hz: float = 2.0
    art_sync: bool = False
    poll_interval_s: float = 6.0
    use_sequence: bool = True
    full_packets: bool = True             # always send 512 channels per universe (some nodes require it)
    universes_per_port: int = 0           # send at least N universes per port (= "Uni Count"); 0 = only what is needed


@dataclass
class AudioConfig:
    source: str = "loopback"              # loopback | mic | demo
    device: str = ""                      # device name for loopback/mic (empty = Windows default)
    block_size: int = 512                 # hop size, lower = less latency
    noise_gate_db: float = -62.0
    auto_gain: bool = True


@dataclass
class WebConfig:
    enabled: bool = True
    port: int = 8787
    pin: str = ""
    secret: str = ""
    allow_public_clients: bool = False    # never true by default: only LAN / private ranges


@dataclass
class AppConfig:
    autostart: bool = False
    start_minimized: bool = False
    close_to_tray: bool = True
    sim_fps: int = 60
    show_fireplace_flame: bool = True
    first_run: bool = True


@dataclass
class Config:
    wall: WallConfig = field(default_factory=WallConfig)
    profiles: list[ProfileConfig] = field(default_factory=list)
    ports: list[PortConfig] = field(default_factory=list)
    output: OutputConfig = field(default_factory=OutputConfig)
    network: NetworkConfig = field(default_factory=NetworkConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    web: WebConfig = field(default_factory=WebConfig)
    app: AppConfig = field(default_factory=AppConfig)

    # ---------------------------------------------------------------- defaults
    @staticmethod
    def default() -> "Config":
        c = Config()
        c.apply_default_layout()
        c.ports = default_ports()
        c.web.pin = f"{secrets.randbelow(10**6):06d}"
        c.web.secret = secrets.token_urlsafe(32)
        return c

    def apply_default_layout(self) -> None:
        """The user's installation: 12 vertical profiles, 6 left / 6 right of the fireplace,
        3 profiles per port wired serpentine (up, down, up)."""
        w = self.wall
        xs = profile_x_positions(w)
        profs = []
        for i in range(NUM_PROFILES):
            port = i // 3 + 1
            pos = i % 3
            profs.append(
                ProfileConfig(
                    index=i,
                    name=f"Profil {i + 1}",
                    port=port,
                    chain_pos=pos,
                    data_up=(pos % 2 == 0),   # ↑ ↓ ↑
                    pixels=w.matrix_rows,
                    x_cm=xs[i],
                )
            )
        self.profiles = profs

    # ------------------------------------------------------------- persistence
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Config":
        c = Config.default()
        for sect in ("wall", "output", "network", "audio", "web", "app"):
            if isinstance(d.get(sect), dict):
                setattr(c, sect, _merge_dc(getattr(c, sect), d[sect]))
        if isinstance(d.get("profiles"), list) and d["profiles"]:
            profs = []
            for i in range(NUM_PROFILES):
                base = c.profiles[i]
                src = d["profiles"][i] if i < len(d["profiles"]) else {}
                p = _merge_dc(base, src if isinstance(src, dict) else {})
                p.index = i
                profs.append(p)
            c.profiles = profs
        if isinstance(d.get("ports"), list) and d["ports"]:
            ports = []
            for i in range(4):
                base = c.ports[i]
                src = d["ports"][i] if i < len(d["ports"]) else {}
                pc = _merge_dc(base, src if isinstance(src, dict) else {})
                pc.number = i + 1
                if pc.color_order not in COLOR_ORDERS:
                    pc.color_order = "RGB"
                ports.append(pc)
            c.ports = ports
        if not c.web.pin:
            c.web.pin = f"{secrets.randbelow(10**6):06d}"
        if not c.web.secret:
            c.web.secret = secrets.token_urlsafe(32)
        c.sanitize()
        return c

    def sanitize(self) -> None:
        self.wall.matrix_rows = int(min(512, max(8, self.wall.matrix_rows)))
        for p in self.profiles:
            p.port = int(min(4, max(1, p.port)))
            p.pixels = int(min(1024, max(1, p.pixels)))
            p.skip_pixels = int(min(256, max(0, p.skip_pixels)))
            p.chain_pos = int(max(0, p.chain_pos))
            p.brightness = float(min(1.0, max(0.0, p.brightness)))
            for k in ("gain_r", "gain_g", "gain_b"):
                setattr(p, k, float(min(1.0, max(0.0, getattr(p, k)))))
            if p.view is not None and (not isinstance(p.view, list) or len(p.view) != 4):
                p.view = None
        for pc in self.ports:
            pc.universe = int(min(32767, max(0, pc.universe)))
            pc.start_channel = int(min(512, max(1, pc.start_channel)))
            pc.pixels_per_universe = int(min(170, max(1, pc.pixels_per_universe)))
        o = self.output
        o.max_brightness = float(min(1.0, max(0.05, o.max_brightness)))
        o.gamma = float(min(3.0, max(1.0, o.gamma)))
        n = self.network
        n.target_fps = int(min(60, max(5, n.target_fps)))
        n.universes_per_port = int(min(16, max(0, n.universes_per_port)))
        self.app.sim_fps = int(min(120, max(20, self.app.sim_fps)))
        self.audio.block_size = int(min(2048, max(128, self.audio.block_size)))

    def copy(self) -> "Config":
        return copy.deepcopy(self)


def default_ports() -> list[PortConfig]:
    """Contiguous allocation: each port starts on a fresh universe.

    With 3 x 84 = 252 pixels per port a port needs two universes, so ports start at
    0, 2, 4, 6.  This MUST match the universe settings in the BanlanX app (or the
    values reported by ArtPollReply) - see the Network page."""
    return [PortConfig(number=i + 1, universe=i * 2) for i in range(4)]


def profile_x_positions(w: WallConfig) -> list[float]:
    """Centre x (cm) of the 12 profiles, symmetric around the wall centre."""
    centre = w.wall_width_cm / 2.0
    half_gap = w.fireplace_gap_cm / 2.0
    xs = []
    for i in range(6):  # left group, profile 6 is closest to the fireplace
        xs.append(centre - half_gap - (5 - i) * w.profile_spacing_cm)
    for i in range(6):
        xs.append(centre + half_gap + i * w.profile_spacing_cm)
    return xs


def _merge_dc(obj: Any, data: dict[str, Any]) -> Any:
    obj = copy.deepcopy(obj)
    names = {f.name: f for f in fields(obj)}
    for k, v in data.items():
        if k not in names:
            continue
        cur = getattr(obj, k)
        try:
            if isinstance(cur, bool):
                v = bool(v)
            elif isinstance(cur, int) and not isinstance(cur, bool):
                v = int(v)
            elif isinstance(cur, float):
                v = float(v)
            elif isinstance(cur, str):
                v = str(v)
        except (TypeError, ValueError):
            continue
        setattr(obj, k, v)
    return obj


# --------------------------------------------------------------------------------------
# JSON store helpers
# --------------------------------------------------------------------------------------
_io_lock = threading.Lock()


def load_json(path: Path, default: Any) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return default
    except (OSError, ValueError):
        # keep a copy of a corrupt file so the user does not silently lose it
        try:
            path.replace(path.with_suffix(path.suffix + ".corrupt"))
        except OSError:
            pass
        return default


def save_json(path: Path, data: Any) -> None:
    with _io_lock:
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
        os.replace(tmp, path)


def load_config(path: Path | None = None) -> Config:
    path = path or app_data_dir() / "config.json"
    data = load_json(path, None)
    if not data:
        return Config.default()
    return Config.from_dict(data)


def save_config(cfg: Config, path: Path | None = None) -> None:
    path = path or app_data_dir() / "config.json"
    save_json(path, cfg.to_dict())
