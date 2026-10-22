"""Pins the `default` pi template, the one pi config every session mounts.

`dotfiles/pi-profiles/default/` holds every provider: the `deepseek` and
`openrouter` provider entries side by side in one `models.json`, with pi's
built-in `openai` (Sign in with ChatGPT) needing no entry at all. The model spec
(`pi:<model>@<provider>`) picks the provider at run time.

It was merged from the `deepseek/` and `openrouter/` templates, which are gone:
`default/` is the only one left, apart from `_shared/`.
"""

import json

from _kitpaths import KIT_ROOT

PROFILES = KIT_ROOT / "dotfiles" / "pi-profiles"
DEFAULT = PROFILES / "default"
GLM = "z-ai/glm-5.3"


def _json(path):
    return json.loads(path.read_text())


def _listed(path):
    """Non-comment, non-blank lines, as the bootstrap reads them."""
    out = []
    for line in path.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            out.append(line)
    return out


def test_default_models_hold_both_providers():
    models = _json(DEFAULT / "agent" / "models.json")
    assert sorted(models["providers"]) == ["deepseek", "openrouter"]


def test_glm_carries_the_catalog_reasoning_fields():
    """Copied from pi-ai 1.2.0's built-in OpenRouter catalog entry for z-ai/glm-5.3."""
    models = _json(DEFAULT / "agent" / "models.json")["providers"]["openrouter"][
        "models"
    ]
    glm = next(m for m in models if m["id"] == GLM)
    assert glm["reasoning"] is True
    assert glm["compat"]["thinkingFormat"] == "openrouter"
    assert glm["contextWindow"] > 0 and glm["maxTokens"] > 0
    # Provider-level keys from the catalog row do not belong on a model entry.
    for key in ("type", "api", "baseUrl", "provider"):
        assert key not in glm, key


def test_required_env_lists_both_keys():
    assert sorted(_listed(DEFAULT / "required-env.txt")) == [
        "DEEPSEEK_API_KEY",
        "OPENROUTER_API_KEY",
    ]


def test_packages_add_the_deepseek_cache_to_shared():
    """The bootstrap installs `_shared/packages.txt`, then this list."""
    assert _listed(DEFAULT / "packages.txt") == [
        "npm:@rohaquinlop/pi-deepseek-cache@0.5.1"
    ]
    assert _listed(PROFILES / "_shared" / "packages.txt"), "shared list is empty"


def test_default_is_the_only_template():
    templates = sorted(d.name for d in PROFILES.iterdir() if d.is_dir())
    assert templates == ["_shared", "default"]
