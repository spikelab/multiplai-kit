"""Where the repo is, for the eval suite.

One definition of the repo root, in a plain module rather than in
``conftest.py``. Importing names *from* a conftest only resolves under pytest's
legacy ``prepend`` import mode: ``pytest evals/ --import-mode=importlib`` and
``cd evals/unit && pytest .`` both failed collection on every module that did
it — 19 and 22 errors respectively, the whole suite. ``conftest.py`` puts this
directory on ``sys.path``, which it can do under any import mode because pytest
imports conftest files itself.
"""

from pathlib import Path

EVALS_DIR = Path(__file__).resolve().parent
KIT_ROOT = EVALS_DIR.parent
HOOKS_DIR = KIT_ROOT / "dotfiles" / "hooks"
