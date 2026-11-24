"""Virtual matrix geometry.

The show is rendered into a virtual matrix of 12 columns (one per profile) and
``rows`` pixels per column, row 0 being the *physical bottom* of the profile.
The mapping layer later resamples every column to the real pixel count and
compensates the DATA direction, so effects never care about wiring.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .config import Config, NUM_PROFILES


@dataclass
class Geometry:
    cols: int
    rows: int
    X: np.ndarray        # (cols, rows) 0..1 left -> right (physical positions)
    Y: np.ndarray        # (cols, rows) 0..1 bottom -> top (physical heights)
    D: np.ndarray        # (cols, rows) 0 at the profiles nearest the fireplace .. 1 outermost
    R: np.ndarray        # (cols, rows) radial distance from the fireplace centre, 0..1
    A: np.ndarray        # (cols, rows) angle around the fireplace centre (radians)
    side: np.ndarray     # (cols,) -1 left, +1 right
    inner: np.ndarray    # (cols,) 0 nearest fireplace .. 5 outermost (per side)
    col_x: np.ndarray    # (cols,) 0..1
    centre_x: float      # fireplace centre in X units
    centre_y: float      # fireplace centre in Y units
    mirror: np.ndarray   # (cols,) index of the mirrored column
    aspect: float        # physical width / height of the profile field

    @property
    def shape(self) -> tuple[int, int, int]:
        return (self.cols, self.rows, 3)

    def zeros(self) -> np.ndarray:
        return np.zeros(self.shape, dtype=np.float32)


def build_geometry(cfg: Config, rows: int | None = None) -> Geometry:
    rows = int(rows or cfg.wall.matrix_rows)
    profs = cfg.profiles[:NUM_PROFILES]
    xs = np.array([p.x_cm for p in profs], dtype=np.float64)
    bottoms = np.array([p.bottom_cm for p in profs], dtype=np.float64)
    lengths = np.array([max(1.0, p.length_cm) for p in profs], dtype=np.float64)
    tops = bottoms + lengths

    x_min, x_max = float(xs.min()), float(xs.max())
    y_min, y_max = float(bottoms.min()), float(tops.max())
    width = max(1.0, x_max - x_min)
    height = max(1.0, y_max - y_min)

    t = (np.arange(rows) + 0.5) / rows                      # 0..1 along each profile
    y_cm = bottoms[:, None] + t[None, :] * lengths[:, None]   # (cols, rows)
    X = np.repeat(((xs - x_min) / width)[:, None], rows, axis=1)
    Y = (y_cm - y_min) / height

    centre_cm = cfg.wall.wall_width_cm / 2.0
    # if the user moved profiles, centre the effect field on the profile gap instead
    left = xs[xs < centre_cm]
    right = xs[xs >= centre_cm]
    if len(left) and len(right):
        centre_cm = (left.max() + right.min()) / 2.0
    side = np.where(xs < centre_cm, -1, 1).astype(np.int32)
    dist = np.abs(xs - centre_cm)
    inner = np.zeros(NUM_PROFILES, dtype=np.int32)
    for s in (-1, 1):
        idx = np.where(side == s)[0]
        order = idx[np.argsort(dist[idx])]
        for rank, i in enumerate(order):
            inner[i] = rank
    dmin, dmax = float(dist.min()), float(dist.max())
    D = np.repeat(((dist - dmin) / max(1e-6, dmax - dmin))[:, None], rows, axis=1)

    fy_cm = cfg.wall.fireplace_bottom_cm + cfg.wall.fireplace_height_cm / 2.0
    cx = (centre_cm - x_min) / width
    cy = (fy_cm - y_min) / height
    dx_cm = xs[:, None] - centre_cm
    dy_cm = y_cm - fy_cm
    rr = np.sqrt(dx_cm ** 2 + dy_cm ** 2)
    R = rr / max(1e-6, rr.max())
    A = np.arctan2(dy_cm, dx_cm)

    order = np.argsort(xs)
    mirror = np.zeros(NUM_PROFILES, dtype=np.int32)
    for k, i in enumerate(order):
        mirror[i] = order[NUM_PROFILES - 1 - k]

    return Geometry(
        cols=NUM_PROFILES,
        rows=rows,
        X=X.astype(np.float32),
        Y=Y.astype(np.float32),
        D=D.astype(np.float32),
        R=R.astype(np.float32),
        A=A.astype(np.float32),
        side=side,
        inner=inner,
        col_x=((xs - x_min) / width).astype(np.float32),
        centre_x=float(cx),
        centre_y=float(cy),
        mirror=mirror,
        aspect=float(width / height),
    )


def default_view(cfg: Config, index: int) -> list[float]:
    """Default position of a profile over the wall image (normalised, y down)."""
    p = cfg.profiles[index]
    w = cfg.wall
    x = p.x_cm / w.wall_width_cm
    yb = 1.0 - p.bottom_cm / w.wall_height_cm
    yt = 1.0 - (p.bottom_cm + p.length_cm) / w.wall_height_cm
    return [x, yb, x, yt]


def profile_view(cfg: Config, index: int) -> list[float]:
    v = cfg.profiles[index].view
    return list(v) if v else default_view(cfg, index)


def fireplace_rect(cfg: Config) -> tuple[float, float, float, float]:
    """Fireplace opening in normalised wall-image coordinates (x, y, w, h), y down."""
    w = cfg.wall
    fw = w.fireplace_width_cm / w.wall_width_cm
    fh = w.fireplace_height_cm / w.wall_height_cm
    x = 0.5 - fw / 2
    y = 1.0 - (w.fireplace_bottom_cm + w.fireplace_height_cm) / w.wall_height_cm
    return (x, y, fw, fh)
