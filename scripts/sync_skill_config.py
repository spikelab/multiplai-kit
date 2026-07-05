#!/usr/bin/env python3
"""Sync skill frontmatter (model, effort) from multiplai.conf.

Reads global ceiling and per-skill overrides from multiplai.conf,
then patches each SKILL.md so the orchestrator model/effort matches.

Usage:
    python scripts/sync_skill_config.py              # patch all skills
    python scripts/sync_skill_config.py --dry-run     # preview changes
    python scripts/sync_skill_config.py --verbose      # show unchanged skills too
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

# --- Location detection ---

_SCRIPT_DIR = Path(__file__).resolve().parent
# Default = <kit-root>/dotfiles (this script lives in <kit-root>/scripts/).
_CONFIG_DIR = Path(
    os.environ.get("CLAUDE_CONFIG_DIR", str(_SCRIPT_DIR.parent / "dotfiles"))
)
_MULTIPLAI_HOME = Path(os.environ.get("CLAUDE_MULTIPLAI_HOME", str(_CONFIG_DIR.parent)))
CONF_PATH = _MULTIPLAI_HOME / "multiplai.conf"
SKILLS_DIR = _CONFIG_DIR / "skills"

# --- Tier rankings ---

_MODEL_TIERS = {"haiku": 1, "sonnet": 2, "opus": 3}
_EFFORT_TIERS = {"low": 1, "medium": 2, "high": 3, "max": 4}

# Full model ID → frontmatter short name
_MODEL_SHORT = {
    "claude-opus-4-6": "opus",
    "claude-opus-4-5": "opus",
    "claude-sonnet-4-6": "sonnet",
    "claude-sonnet-4-5": "sonnet",
    "claude-haiku-4-5": "haiku",
    "claude-haiku-4-5-20251001": "haiku",
}


def model_short_name(model_id: str) -> str:
    """Convert 'claude-opus-4-6' → 'opus'. Pass through if already short."""
    if model_id in _MODEL_SHORT:
        return _MODEL_SHORT[model_id]
    for tier in ("opus", "sonnet", "haiku"):
        if tier in model_id.lower():
            return tier
    return model_id  # already short or unknown


def _model_tier(name: str) -> int:
    name_lower = name.lower()
    for tier, rank in _MODEL_TIERS.items():
        if tier in name_lower:
            return rank
    return 2


def _effort_tier(name: str) -> int:
    return _EFFORT_TIERS.get(name.lower(), 3)


# --- Config loading ---


def load_conf(path: Path) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    """Parse multiplai.conf. Returns (globals, sections)."""
    if not path.exists():
        return {}, {}

    globals_: dict[str, str] = {}
    sections: dict[str, dict[str, str]] = {}
    current_section: str | None = None

    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        section_match = re.match(r"^\[([a-zA-Z0-9_-]+)\]\s*$", line)
        if section_match:
            current_section = section_match.group(1)
            sections.setdefault(current_section, {})
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if current_section:
                sections[current_section][key] = value
            else:
                globals_[key] = value

    return globals_, sections


# --- Resolution ---


def resolve_for_skill(
    skill_name: str,
    frontmatter_model: str,
    frontmatter_effort: str,
    global_model: str,
    global_effort: str,
    sections: dict[str, dict[str, str]],
) -> tuple[str, str, str]:
    """Determine final (model, effort, reason) for a skill.

    With section: use section values (exact override).
    Without section: cap frontmatter to global ceiling.
    Returns (model, effort, reason_string).
    """
    section = sections.get(skill_name)

    if section:
        final_model = section.get("MODEL", frontmatter_model)
        final_effort = section.get("EFFORT", frontmatter_effort)
        # For partial sections: cap missing keys to global ceiling
        if "MODEL" not in section:
            if _model_tier(frontmatter_model) > _model_tier(global_model):
                final_model = global_model
        if "EFFORT" not in section:
            if _effort_tier(frontmatter_effort) > _effort_tier(global_effort):
                final_effort = global_effort
        return final_model, final_effort, "section"
    else:
        final_model = frontmatter_model
        if _model_tier(frontmatter_model) > _model_tier(global_model):
            final_model = global_model
        final_effort = frontmatter_effort
        if _effort_tier(frontmatter_effort) > _effort_tier(global_effort):
            final_effort = global_effort
        return final_model, final_effort, "ceiling"


# --- Frontmatter patching ---


def parse_frontmatter(content: str) -> tuple[str, str] | None:
    """Extract current model and effort from YAML frontmatter. Returns None if missing."""
    lines = content.split("\n")
    if not lines or lines[0].strip() != "---":
        return None

    model = effort = ""
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            break
        if lines[i].startswith("model:"):
            model = lines[i].split(":", 1)[1].strip()
        elif lines[i].startswith("effort:"):
            effort = lines[i].split(":", 1)[1].strip()

    if not model:
        return None
    return model, effort


def patch_frontmatter(content: str, new_model: str, new_effort: str) -> str | None:
    """Patch model and effort in frontmatter. Returns None if no change needed."""
    lines = content.split("\n")
    if not lines or lines[0].strip() != "---":
        return None

    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return None

    changed = False
    for i in range(1, end_idx):
        if lines[i].startswith("model:"):
            old_val = lines[i].split(":", 1)[1].strip()
            if old_val != new_model:
                lines[i] = f"model: {new_model}"
                changed = True
        elif lines[i].startswith("effort:"):
            old_val = lines[i].split(":", 1)[1].strip()
            if old_val != new_effort:
                lines[i] = f"effort: {new_effort}"
                changed = True

    if not changed:
        return None
    return "\n".join(lines)


# --- Main ---


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sync skill frontmatter from multiplai.conf"
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument("--verbose", action="store_true", help="Show unchanged skills")
    args = parser.parse_args()

    if not CONF_PATH.exists():
        print(f"No multiplai.conf at {CONF_PATH}", file=sys.stderr)
        return 1

    if not SKILLS_DIR.is_dir():
        print(f"No skills directory at {SKILLS_DIR}", file=sys.stderr)
        return 1

    globals_, sections = load_conf(CONF_PATH)
    global_model = model_short_name(globals_.get("MULTIPLAI_MODEL", "claude-sonnet-4-6"))
    global_effort = globals_.get("MULTIPLAI_EFFORT", "high")

    print(f"Syncing skill config from {CONF_PATH.name}...")
    print(f"  Global ceiling: model={global_model}, effort={global_effort}")
    if sections:
        print(f"  Sections: {', '.join(sections.keys())}")
    print()

    patched = 0
    overridden = 0
    unchanged = 0
    total = 0

    for skill_dir in sorted(SKILLS_DIR.iterdir()):
        if not skill_dir.is_dir():
            continue
        # Check both SKILL.md and instructions.md (some skills use either)
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            skill_md = skill_dir / "instructions.md"
        if not skill_md.exists():
            continue

        total += 1
        skill_name = skill_dir.name
        content = skill_md.read_text()

        current = parse_frontmatter(content)
        if current is None:
            if args.verbose:
                print(f"  {skill_name}: no frontmatter, skipping")
            continue

        current_model, current_effort = current
        final_model, final_effort, reason = resolve_for_skill(
            skill_name, current_model, current_effort,
            global_model, global_effort, sections,
        )

        if final_model == current_model and final_effort == current_effort:
            unchanged += 1
            if args.verbose:
                print(f"  {skill_name}: no change")
            continue

        changes = []
        if final_model != current_model:
            changes.append(f"model {current_model}\u2192{final_model}")
        if final_effort != current_effort:
            changes.append(f"effort {current_effort}\u2192{final_effort}")
        reason_label = "section" if reason == "section" else "ceiling"

        if reason == "section":
            overridden += 1

        new_content = patch_frontmatter(content, final_model, final_effort)
        if new_content is None:
            unchanged += 1
            continue

        if args.dry_run:
            print(f"  {skill_name}: {', '.join(changes)} ({reason_label}) [dry-run]")
        else:
            skill_md.write_text(new_content)
            print(f"  {skill_name}: {', '.join(changes)} ({reason_label})")
        patched += 1

    print()
    action = "Would patch" if args.dry_run else "Patched"
    print(f"{action} {patched}/{total} skills. {overridden} overridden, {unchanged} unchanged.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
