"""Tests for model_resolver.py — the model ceiling logic."""

import os
import pytest
from model_resolver import resolve_model, _tier, resolve_effort, _effort_tier


class TestTierExtraction:
    def test_haiku(self):
        assert _tier("claude-haiku-4-5") == 1

    def test_sonnet(self):
        assert _tier("claude-sonnet-4-6") == 2

    def test_opus(self):
        assert _tier("claude-opus-4-6") == 3

    def test_unrecognized_defaults_to_sonnet(self):
        assert _tier("claude-mystery-9-9") == 2

    def test_case_insensitive(self):
        assert _tier("Claude-SONNET-4-6") == 2


class TestResolveCeiling:
    def test_sonnet_ceiling_caps_opus(self, monkeypatch):
        monkeypatch.setenv("MULTIPLAI_MODEL", "claude-sonnet-4-6")
        assert resolve_model("claude-opus-4-6") == "claude-sonnet-4-6"

    def test_sonnet_ceiling_keeps_sonnet(self, monkeypatch):
        monkeypatch.setenv("MULTIPLAI_MODEL", "claude-sonnet-4-6")
        assert resolve_model("claude-sonnet-4-5") == "claude-sonnet-4-5"

    def test_sonnet_ceiling_keeps_haiku(self, monkeypatch):
        monkeypatch.setenv("MULTIPLAI_MODEL", "claude-sonnet-4-6")
        assert resolve_model("claude-haiku-4-5") == "claude-haiku-4-5"

    def test_opus_ceiling_allows_everything(self, monkeypatch):
        monkeypatch.setenv("MULTIPLAI_MODEL", "claude-opus-4-6")
        assert resolve_model("claude-opus-4-6") == "claude-opus-4-6"
        assert resolve_model("claude-sonnet-4-6") == "claude-sonnet-4-6"
        assert resolve_model("claude-haiku-4-5") == "claude-haiku-4-5"

    def test_haiku_ceiling_caps_both(self, monkeypatch):
        monkeypatch.setenv("MULTIPLAI_MODEL", "claude-haiku-4-5")
        assert resolve_model("claude-opus-4-6") == "claude-haiku-4-5"
        assert resolve_model("claude-sonnet-4-6") == "claude-haiku-4-5"
        assert resolve_model("claude-haiku-4-5") == "claude-haiku-4-5"

    def test_default_ceiling_is_sonnet(self, monkeypatch):
        monkeypatch.delenv("MULTIPLAI_MODEL", raising=False)
        assert resolve_model("claude-opus-4-6") == "claude-sonnet-4-6"
        assert resolve_model("claude-haiku-4-5") == "claude-haiku-4-5"

    def test_same_tier_different_version_kept(self, monkeypatch):
        monkeypatch.setenv("MULTIPLAI_MODEL", "claude-sonnet-4-6")
        # Requesting older sonnet version — same tier, kept
        assert resolve_model("claude-sonnet-4-5") == "claude-sonnet-4-5"


class TestEffortTier:
    """Test _effort_tier mapping."""

    def test_low(self):
        assert _effort_tier("low") == 1

    def test_medium(self):
        assert _effort_tier("medium") == 2

    def test_high(self):
        assert _effort_tier("high") == 3

    def test_max(self):
        assert _effort_tier("max") == 4

    def test_unrecognized_defaults_to_high(self):
        assert _effort_tier("turbo") == 3

    def test_case_insensitive(self):
        assert _effort_tier("HIGH") == 3


class TestCeilingValidation:
    """A typo'd ceiling must never be returned verbatim — a downgrade hands the
    ceiling string to the API as a model id, and a typo there is a 404 at the
    worst possible distance from the config error that caused it."""

    def test_typoed_model_ceiling_falls_back_to_default(self, monkeypatch, capsys):
        monkeypatch.setenv("MULTIPLAI_MODEL", "claude-sonet-4-6")  # typo
        assert resolve_model("claude-opus-4-6") == "claude-sonnet-4-6"
        err = capsys.readouterr().err
        assert "claude-sonet-4-6" in err and "no known tier" in err

    def test_typoed_ceiling_keeps_a_valid_request_below_it(self, monkeypatch):
        monkeypatch.setenv("MULTIPLAI_MODEL", "claude-sonet-4-6")
        assert resolve_model("claude-haiku-4-5") == "claude-haiku-4-5"

    def test_typoed_effort_ceiling_falls_back_to_high(self, monkeypatch, capsys):
        monkeypatch.setenv("MULTIPLAI_EFFORT", "turbo")
        assert resolve_effort("max") == "high"
        assert "turbo" in capsys.readouterr().err

    def test_none_effort_returns_the_default(self, monkeypatch):
        """Callers pass a skill's frontmatter effort, which may be absent —
        that used to raise AttributeError on .lower()."""
        monkeypatch.delenv("MULTIPLAI_EFFORT", raising=False)
        assert resolve_effort(None) == "high"

    def test_none_effort_respects_the_ceiling(self, monkeypatch):
        monkeypatch.setenv("MULTIPLAI_EFFORT", "medium")
        assert resolve_effort(None) == "medium"


class TestResolveEffort:
    """Test resolve_effort ceiling logic."""

    def test_high_ceiling_caps_max(self, monkeypatch):
        monkeypatch.setenv("MULTIPLAI_EFFORT", "high")
        assert resolve_effort("max") == "high"

    def test_high_ceiling_keeps_medium(self, monkeypatch):
        monkeypatch.setenv("MULTIPLAI_EFFORT", "high")
        assert resolve_effort("medium") == "medium"

    def test_max_ceiling_allows_everything(self, monkeypatch):
        monkeypatch.setenv("MULTIPLAI_EFFORT", "max")
        assert resolve_effort("max") == "max"
        assert resolve_effort("low") == "low"

    def test_low_ceiling_caps_all(self, monkeypatch):
        monkeypatch.setenv("MULTIPLAI_EFFORT", "low")
        assert resolve_effort("high") == "low"
        assert resolve_effort("max") == "low"

    def test_default_ceiling_is_high(self, monkeypatch):
        monkeypatch.delenv("MULTIPLAI_EFFORT", raising=False)
        assert resolve_effort("max") == "high"
        assert resolve_effort("medium") == "medium"
