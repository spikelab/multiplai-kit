"""Test wiring: put the skill package and the kit's shared `log_utils` on sys.path.

The skill normally gets `log_utils` from `PYTHONPATH=$CLAUDE_CONFIG_DIR/hooks`
(set in SKILL.md). Tests shouldn't depend on that being exported, so resolve it
from this file's location instead — scripts/tests/ → skills/prioritize/ →
skills/ → dotfiles/ → hooks/.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
DOTFILES_DIR = SCRIPTS_DIR.parents[2]
HOOKS_DIR = DOTFILES_DIR / "hooks"

for path in (SCRIPTS_DIR, HOOKS_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

# Keep log output inside the test run rather than the user's runtime dir.
os.environ.setdefault("CLAUDE_CONFIG_DIR", str(DOTFILES_DIR))
