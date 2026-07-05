"""Tests for scripts/sync_skill_config.py — config sync functions."""

import sys
from pathlib import Path

import pytest

# Add scripts dir so we can import the module
_SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from sync_skill_config import (
    model_short_name,
    resolve_for_skill,
    parse_frontmatter,
    patch_frontmatter,
    load_conf,
)


class TestModelShortName:
    """Test model_short_name() full-ID-to-short conversion."""

    def test_opus(self):
        assert model_short_name("claude-opus-4-6") == "opus"

    def test_sonnet(self):
        assert model_short_name("claude-sonnet-4-6") == "sonnet"

    def test_haiku(self):
        assert model_short_name("claude-haiku-4-5") == "haiku"

    def test_already_short(self):
        assert model_short_name("opus") == "opus"

    def test_haiku_with_date_suffix(self):
        assert model_short_name("claude-haiku-4-5-20251001") == "haiku"

    def test_unknown_passthrough(self):
        assert model_short_name("gpt-4") == "gpt-4"


class TestLoadConf:
    """Test load_conf() INI-style parsing."""

    def test_globals_and_sections(self, tmp_path):
        conf = tmp_path / "test.conf"
        conf.write_text(
            'MULTIPLAI_MODEL="claude-sonnet-4-6"\n'
            "MULTIPLAI_EFFORT=high\n"
            "\n"
            "[deep-research]\n"
            "MODEL=opus\n"
            "EFFORT=max\n"
        )
        globals_, sections = load_conf(conf)
        assert globals_["MULTIPLAI_MODEL"] == "claude-sonnet-4-6"
        assert globals_["MULTIPLAI_EFFORT"] == "high"
        assert sections["deep-research"]["MODEL"] == "opus"
        assert sections["deep-research"]["EFFORT"] == "max"

    def test_missing_file(self, tmp_path):
        globals_, sections = load_conf(tmp_path / "nonexistent.conf")
        assert globals_ == {}
        assert sections == {}

    def test_comments_and_blanks(self, tmp_path):
        conf = tmp_path / "test.conf"
        conf.write_text(
            "# comment\n"
            "\n"
            "KEY=value\n"
            "# another comment\n"
        )
        globals_, sections = load_conf(conf)
        assert globals_ == {"KEY": "value"}
        assert sections == {}


class TestResolveForSkill:
    """Test resolve_for_skill() ceiling and section logic."""

    def test_no_section_applies_ceiling(self):
        """Without a section, frontmatter model/effort are capped to global ceiling."""
        model, effort, reason = resolve_for_skill(
            skill_name="some-skill",
            frontmatter_model="opus",
            frontmatter_effort="high",
            global_model="sonnet",
            global_effort="medium",
            sections={},
        )
        assert model == "sonnet"
        assert effort == "medium"
        assert reason == "ceiling"

    def test_section_overrides_ceiling(self):
        """A section MODEL=opus overrides the global ceiling."""
        model, effort, reason = resolve_for_skill(
            skill_name="deep-research",
            frontmatter_model="opus",
            frontmatter_effort="max",
            global_model="sonnet",
            global_effort="medium",
            sections={"deep-research": {"MODEL": "opus", "EFFORT": "max"}},
        )
        assert model == "opus"
        assert effort == "max"
        assert reason == "section"

    def test_section_partial_model_only(self):
        """Section with MODEL but not EFFORT: effort falls back to ceiling."""
        model, effort, reason = resolve_for_skill(
            skill_name="deep-research",
            frontmatter_model="opus",
            frontmatter_effort="max",
            global_model="sonnet",
            global_effort="medium",
            sections={"deep-research": {"MODEL": "opus"}},
        )
        assert model == "opus"
        assert effort == "medium"  # capped to global ceiling
        assert reason == "section"

    def test_below_ceiling_unchanged(self):
        """Frontmatter below ceiling passes through unchanged."""
        model, effort, reason = resolve_for_skill(
            skill_name="kanban",
            frontmatter_model="haiku",
            frontmatter_effort="low",
            global_model="sonnet",
            global_effort="medium",
            sections={},
        )
        assert model == "haiku"
        assert effort == "low"
        assert reason == "ceiling"

    def test_section_partial_effort_only(self):
        """Section with EFFORT but not MODEL: model falls back to ceiling."""
        model, effort, reason = resolve_for_skill(
            skill_name="buildme",
            frontmatter_model="opus",
            frontmatter_effort="max",
            global_model="sonnet",
            global_effort="medium",
            sections={"buildme": {"EFFORT": "max"}},
        )
        assert model == "sonnet"  # capped to global ceiling
        assert effort == "max"
        assert reason == "section"


class TestParseFrontmatter:
    """Test parse_frontmatter() YAML extraction."""

    def test_basic(self):
        content = "---\nmodel: opus\neffort: high\n---\nBody text here.\n"
        result = parse_frontmatter(content)
        assert result == ("opus", "high")

    def test_no_frontmatter(self):
        content = "Just some text without frontmatter.\n"
        assert parse_frontmatter(content) is None

    def test_model_only(self):
        content = "---\nmodel: opus\ndescription: some skill\n---\nBody.\n"
        result = parse_frontmatter(content)
        assert result == ("opus", "")

    def test_extra_fields_ignored(self):
        content = (
            "---\n"
            "model: sonnet\n"
            "effort: medium\n"
            "description: A skill\n"
            "triggers:\n"
            "  - foo\n"
            "---\n"
            "Body.\n"
        )
        result = parse_frontmatter(content)
        assert result == ("sonnet", "medium")

    def test_no_model_returns_none(self):
        """Frontmatter with effort but no model returns None."""
        content = "---\neffort: high\n---\nBody.\n"
        assert parse_frontmatter(content) is None


class TestPatchFrontmatter:
    """Test patch_frontmatter() content rewriting."""

    def test_patches_model(self):
        content = "---\nmodel: opus\neffort: high\n---\nBody text.\n"
        result = patch_frontmatter(content, "sonnet", "high")
        assert result is not None
        assert "model: sonnet" in result
        assert "Body text." in result

    def test_patches_effort(self):
        content = "---\nmodel: opus\neffort: high\n---\nBody text.\n"
        result = patch_frontmatter(content, "opus", "medium")
        assert result is not None
        assert "effort: medium" in result
        assert "model: opus" in result

    def test_no_change_returns_none(self):
        content = "---\nmodel: opus\neffort: high\n---\nBody text.\n"
        result = patch_frontmatter(content, "opus", "high")
        assert result is None

    def test_preserves_other_fields(self):
        content = (
            "---\n"
            "model: opus\n"
            "effort: high\n"
            "description: My awesome skill\n"
            "triggers:\n"
            "  - do the thing\n"
            "---\n"
            "# Skill Instructions\n"
            "Do stuff.\n"
        )
        result = patch_frontmatter(content, "sonnet", "medium")
        assert result is not None
        assert "description: My awesome skill" in result
        assert "triggers:" in result
        assert "  - do the thing" in result
        assert "# Skill Instructions" in result
        assert "Do stuff." in result

    def test_no_frontmatter_returns_none(self):
        content = "Just plain text, no frontmatter.\n"
        result = patch_frontmatter(content, "sonnet", "high")
        assert result is None

    def test_patches_both(self):
        content = "---\nmodel: opus\neffort: max\n---\nBody.\n"
        result = patch_frontmatter(content, "sonnet", "medium")
        assert result is not None
        assert "model: sonnet" in result
        assert "effort: medium" in result
