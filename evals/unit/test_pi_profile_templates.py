"""Pins the `default` pi profile template against the two it was merged from.

`dotfiles/pi-profiles/default/` is one pi config holding every provider: the
`deepseek` and `openrouter` provider entries side by side in one `models.json`,
with pi's built-in `openai` (Sign in with ChatGPT) needing no entry at all. The
model spec (`pi:<model>@<provider>`) picks the provider at run time, so the
merge must not drift from its sources: a hand-edited copy that lost a compat
field would break thinking-mode tool calls on one provider and nowhere else.

The `deepseek/` and `openrouter/` templates stay as they are, for
`--pi-profile deepseek` and `--pi-profile openrouter`.
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


def test_deepseek_provider_is_copied_unchanged():
    merged = _json(DEFAULT / "agent" / "models.json")["providers"]["deepseek"]
    source = _json(PROFILES / "deepseek" / "agent" / "models.json")["providers"]["deepseek"]
    assert merged == source


def test_openrouter_provider_is_its_source_plus_glm():
    merged = _json(DEFAULT / "agent" / "models.json")["providers"]["openrouter"]
    source = _json(PROFILES / "openrouter" / "agent" / "models.json")["providers"]["openrouter"]

    without_models = {k: v for k, v in merged.items() if k != "models"}
    assert without_models == {k: v for k, v in source.items() if k != "models"}

    ids = [m["id"] for m in merged["models"]]
    assert ids == [m["id"] for m in source["models"]] + [GLM]
    assert merged["models"][: len(source["models"])] == source["models"]


def test_glm_carries_the_catalog_reasoning_fields():
    """Copied from pi-ai 1.2.0's built-in OpenRouter catalog entry for z-ai/glm-5.3."""
    models = _json(DEFAULT / "agent" / "models.json")["providers"]["openrouter"]["models"]
    glm = next(m for m in models if m["id"] == GLM)
    assert glm["reasoning"] is True
    assert glm["compat"]["thinkingFormat"] == "openrouter"
    assert glm["contextWindow"] > 0 and glm["maxTokens"] > 0
    # Provider-level keys from the catalog row do not belong on a model entry.
    for key in ("type", "api", "baseUrl", "provider"):
        assert key not in glm, key


def test_settings_merge_with_deepseek_winning():
    merged = _json(DEFAULT / "agent" / "settings.json")
    deepseek = _json(PROFILES / "deepseek" / "agent" / "settings.json")
    openrouter = _json(PROFILES / "openrouter" / "agent" / "settings.json")
    assert merged == {**openrouter, **deepseek}


def test_required_env_lists_both_keys():
    assert sorted(_listed(DEFAULT / "required-env.txt")) == [
        "DEEPSEEK_API_KEY",
        "OPENROUTER_API_KEY",
    ]


def test_packages_match_shared():
    """The default profile installs exactly the shared list and nothing of its own.

    The bootstrap installs `_shared/packages.txt` and then the profile's list, so
    an empty profile list is what makes the result match `_shared`.
    """
    assert _listed(DEFAULT / "packages.txt") == []
    assert _listed(PROFILES / "_shared" / "packages.txt"), "shared list is empty"


def test_source_templates_are_kept():
    for name in ("deepseek", "openrouter"):
        assert (PROFILES / name / "agent" / "models.json").is_file(), name
