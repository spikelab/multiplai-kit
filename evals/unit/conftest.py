"""The import paths the eval modules need, in every pytest import mode.

This lives beside the tests rather than one level up on purpose. Running
``cd evals/unit && pytest .`` makes *this* directory the rootdir, and pytest
then never loads ``evals/conftest.py`` at all — so a path insert placed there
would silently not happen, which is how that invocation ended up failing
collection on 22 modules.

Three directories, and each has a reason:

  * ``unit/`` — ``_platform_stubs`` and the handful of modules that import a
    helper from a sibling test module.
  * ``evals/`` — ``_kitpaths``, which carries ``KIT_ROOT``. It is a plain
    module and not this conftest because importing names *from* a conftest
    only resolves under pytest's legacy ``prepend`` import mode.
  * ``dotfiles/hooks/`` — the live hook modules under test (``model_resolver``).
"""

import sys
from pathlib import Path

UNIT_DIR = Path(__file__).resolve().parent
EVALS_DIR = UNIT_DIR.parent
HOOKS_DIR = EVALS_DIR.parent / "dotfiles" / "hooks"

for _directory in (UNIT_DIR, EVALS_DIR, HOOKS_DIR):
    if str(_directory) not in sys.path:
        sys.path.insert(0, str(_directory))
