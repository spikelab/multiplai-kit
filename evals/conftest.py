"""Shared test infrastructure for the kit eval suite.

Scope: these tests cover the kit's *own* live code — the model-ceiling
resolver and `multiplai.conf` loading. The memory /
context / learning system now lives in the `multiplai-context` plugin
(published in the `multiplai-cc-mktplace` repo), which has its own `tests/`.
"""

import sys
from pathlib import Path

EVALS_DIR = Path(__file__).resolve().parent
# One definition of the repo root for the whole suite — test modules import it
# (`from conftest import KIT_ROOT`) instead of each computing their own.
KIT_ROOT = EVALS_DIR.parent
HOOKS_DIR = KIT_ROOT / "dotfiles" / "hooks"

# Add hooks dir to sys.path so tests can import live hook modules (model_resolver).
if str(HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(HOOKS_DIR))
