"""Shared test infrastructure for the kit eval suite.

Scope: these tests cover the kit's *own* live code — the model-ceiling
resolver, `multiplai.conf` loading, and `sync_skill_config.py`. The memory /
context / learning system now lives in the `multiplai-context` plugin
(`PROJECTS/multiplai-plugin/`), which has its own `tests/`.
"""

import os
import sys
from pathlib import Path

EVALS_DIR = Path(__file__).parent
HOOKS_DIR = EVALS_DIR.parent / "dotfiles" / "hooks"

# Add hooks dir to sys.path so tests can import live hook modules (model_resolver).
if str(HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(HOOKS_DIR))

# Never hit a real Claude endpoint from a unit test.
os.environ.setdefault("MULTIPLAI_DISABLE_LLM", "1")
