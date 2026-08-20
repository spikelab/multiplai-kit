"""Shared test infrastructure for the kit eval suite.

Scope: these tests cover the kit's *own* live code — the model-ceiling
resolver and `multiplai.conf` loading. The memory /
context / learning system now lives in the `multiplai-context` plugin
(published in the `multiplai-cc-mktplace` repo), which has its own `tests/`.

Paths the suite imports (`_kitpaths`, `_platform_stubs`, the hook modules) are
put on `sys.path` by `unit/conftest.py`, not here — see the note there.
"""
