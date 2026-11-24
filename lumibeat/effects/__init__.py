"""Effect library. Importing this package registers every effect."""
from . import ambient, music, special  # noqa: F401  (registration side effects)
from .ambient import AMBIENT_ORDER
from .base import CATEGORY_LABELS, REGISTRY, Ctx, Effect, effect_info
from .custom import LayeredEffect, default_spec, normalize_spec
from .palettes import PALETTE_ORDER, PALETTES, Palette


def music_effect_ids() -> list[str]:
    return [k for k, v in REGISTRY.items() if v.category in ("music", "special")]


def ambient_effect_ids() -> list[str]:
    return [k for k in AMBIENT_ORDER if k in REGISTRY]


__all__ = [
    "REGISTRY", "Ctx", "Effect", "effect_info", "LayeredEffect", "default_spec", "normalize_spec",
    "PALETTES", "PALETTE_ORDER", "Palette", "CATEGORY_LABELS", "music_effect_ids", "ambient_effect_ids",
]
