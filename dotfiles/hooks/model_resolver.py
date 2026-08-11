"""
Resolve model names respecting the MULTIPLAI_MODEL ceiling.

MULTIPLAI_MODEL sets the maximum model tier. If a hook requests a model
above the ceiling, it gets downgraded. Models below the ceiling stay as-is.

Tier order: haiku < sonnet < opus

Examples (ceiling = sonnet):
  resolve("claude-opus-4-6")  → "claude-sonnet-4-6"  (downgraded)
  resolve("claude-sonnet-4-5") → "claude-sonnet-4-5"  (kept)
  resolve("claude-haiku-4-5")  → "claude-haiku-4-5"   (kept)

Examples (ceiling = opus):
  resolve("claude-opus-4-6")  → "claude-opus-4-6"    (kept)
"""

import os
import sys

# Tier ranking: higher number = more capable
_TIERS = {"haiku": 1, "sonnet": 2, "opus": 3}
_EFFORT_TIERS = {"low": 1, "medium": 2, "high": 3, "max": 4}

# Fallbacks when the configured ceiling is unrecognizable. A downgrade can
# *return* the ceiling string verbatim, so a typo'd ceiling must never be
# handed back — it would reach the API as a model id and 404.
_DEFAULT_MODEL_CEILING = "claude-sonnet-4-6"
_DEFAULT_EFFORT_CEILING = "high"


def _tier(model: str) -> int:
    """Extract tier from a model string like 'claude-sonnet-4-6'."""
    model_lower = model.lower()
    for name, rank in _TIERS.items():
        if name in model_lower:
            return rank
    return 2  # default to sonnet tier if unrecognized


def _effort_tier(effort: str) -> int:
    """Map effort string to numeric tier."""
    return _EFFORT_TIERS.get(effort.lower(), 3)  # default to high


def resolve_model(requested: str) -> str:
    """Return the requested model, or the ceiling model if requested is above it.

    The ceiling comes from MULTIPLAI_MODEL, which run-hook-python exports from
    multiplai.conf (shipped default: claude-opus-4-6 = no ceiling). The
    hardcoded fallback here is a *conservative* sonnet ceiling for direct
    importers that run without the conf loaded — it is intentionally stricter
    than the shipped conf, not a mismatch.

    A ceiling naming no known tier (a typo in multiplai.conf) falls back to
    the default ceiling with a stderr note: returning it verbatim would send
    the typo to the API as a model id (404), the worst place to learn about a
    config error.
    """
    ceiling = os.environ.get("MULTIPLAI_MODEL", _DEFAULT_MODEL_CEILING)
    if not any(name in ceiling.lower() for name in _TIERS):
        print(
            f"model_resolver: MULTIPLAI_MODEL={ceiling!r} names no known tier "
            f"({'/'.join(_TIERS)}); using {_DEFAULT_MODEL_CEILING}",
            file=sys.stderr,
        )
        ceiling = _DEFAULT_MODEL_CEILING
    ceiling_tier = _tier(ceiling)
    requested_tier = _tier(requested)

    if requested_tier > ceiling_tier:
        return ceiling
    return requested


def resolve_effort(requested: str | None) -> str:
    """Return the requested effort, or the ceiling effort if requested is above it.

    Same ceiling validation as resolve_model — a typo'd MULTIPLAI_EFFORT must
    not be returned verbatim. A missing request (None/empty) resolves to the
    default effort, capped by the ceiling as usual.
    """
    ceiling = os.environ.get("MULTIPLAI_EFFORT", _DEFAULT_EFFORT_CEILING)
    if ceiling.lower() not in _EFFORT_TIERS:
        print(
            f"model_resolver: MULTIPLAI_EFFORT={ceiling!r} is not one of "
            f"{'/'.join(_EFFORT_TIERS)}; using {_DEFAULT_EFFORT_CEILING}",
            file=sys.stderr,
        )
        ceiling = _DEFAULT_EFFORT_CEILING
    if not requested:
        requested = _DEFAULT_EFFORT_CEILING
    if _effort_tier(requested) > _effort_tier(ceiling):
        return ceiling
    return requested
