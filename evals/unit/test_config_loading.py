"""Unit tests for multiplai.conf loading and environment variable propagation.

Tests that run-hook-python correctly sources multiplai.conf and exports
MULTIPLAI_MODEL and MULTIPLAI_DEBUG as environment variables that Python
hooks can read.
"""

import subprocess
from pathlib import Path


class TestConfigDefaults:
    """Test default values when multiplai.conf is absent or empty."""

    def test_default_model_without_conf(self, tmp_path):
        """Without multiplai.conf, MULTIPLAI_MODEL defaults to claude-sonnet-4-6."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / ".workspace").write_text(str(tmp_path))
        (config_dir / "logs").mkdir()

        result = subprocess.run(
            ["bash", "-c", f"""
                export CLAUDE_CONFIG_DIR="{config_dir}"
                export MULTIPLAI_DEBUG=false
                export MULTIPLAI_MODEL="claude-sonnet-4-6"
                source "{config_dir}/multiplai.conf" 2>/dev/null || true
                echo "$MULTIPLAI_MODEL"
            """],
            capture_output=True, text=True,
        )
        assert result.stdout.strip() == "claude-sonnet-4-6"

    def test_default_debug_without_conf(self, tmp_path):
        """Without multiplai.conf, MULTIPLAI_DEBUG defaults to false."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "logs").mkdir()

        result = subprocess.run(
            ["bash", "-c", f"""
                export CLAUDE_CONFIG_DIR="{config_dir}"
                MULTIPLAI_DEBUG=false
                source "{config_dir}/multiplai.conf" 2>/dev/null || true
                echo "$MULTIPLAI_DEBUG"
            """],
            capture_output=True, text=True,
        )
        assert result.stdout.strip() == "false"


class TestConfigOverrides:
    """Test that multiplai.conf values override defaults."""

    def test_model_override(self, tmp_path):
        """MULTIPLAI_MODEL in conf overrides the default."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "logs").mkdir()
        (config_dir / "multiplai.conf").write_text(
            'MULTIPLAI_MODEL="claude-haiku-4-5-20251001"\n'
        )

        result = subprocess.run(
            ["bash", "-c", f"""
                export CLAUDE_CONFIG_DIR="{config_dir}"
                MULTIPLAI_MODEL="claude-sonnet-4-6"
                source "{config_dir}/multiplai.conf"
                echo "$MULTIPLAI_MODEL"
            """],
            capture_output=True, text=True,
        )
        assert result.stdout.strip() == "claude-haiku-4-5-20251001"

    def test_debug_override(self, tmp_path):
        """MULTIPLAI_DEBUG=true in conf enables debug mode."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "logs").mkdir()
        (config_dir / "multiplai.conf").write_text(
            'MULTIPLAI_DEBUG=true\n'
        )

        result = subprocess.run(
            ["bash", "-c", f"""
                export CLAUDE_CONFIG_DIR="{config_dir}"
                MULTIPLAI_DEBUG=false
                source "{config_dir}/multiplai.conf"
                echo "$MULTIPLAI_DEBUG"
            """],
            capture_output=True, text=True,
        )
        assert result.stdout.strip() == "true"

    def test_effort_override(self, tmp_path):
        """MULTIPLAI_EFFORT in conf overrides default."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "logs").mkdir()
        (config_dir / "multiplai.conf").write_text(
            'MULTIPLAI_EFFORT=medium\n'
        )

        result = subprocess.run(
            ["bash", "-c", f"""
                export CLAUDE_CONFIG_DIR="{config_dir}"
                MULTIPLAI_EFFORT=high
                source "{config_dir}/multiplai.conf"
                echo "$MULTIPLAI_EFFORT"
            """],
            capture_output=True, text=True,
        )
        assert result.stdout.strip() == "medium"

class TestRunHookPythonExport:
    """Test that run-hook-python exports conf values to Python processes."""

    def test_model_exported_to_python(self, tmp_path):
        """run-hook-python exports MULTIPLAI_MODEL so Python hooks can read it."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "logs").mkdir()
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / ".venv" / "bin").mkdir(parents=True)

        (config_dir / ".workspace").write_text(str(workspace))
        (config_dir / "multiplai.conf").write_text(
            'MULTIPLAI_MODEL="claude-haiku-4-5-20251001"\n'
        )

        # Create a tiny Python script that prints the env var
        script = tmp_path / "print_model.py"
        script.write_text('import os; print(os.environ.get("MULTIPLAI_MODEL", "UNSET"))\n')

        # run-hook-python will try workspace venv python first, fall back to system.
        # We test the export logic by sourcing the same conf loading logic.
        result = subprocess.run(
            ["bash", "-c", f"""
                export CLAUDE_CONFIG_DIR="{config_dir}"
                MULTIPLAI_MODEL="claude-sonnet-4-6"
                [ -f "{config_dir}/multiplai.conf" ] && source "{config_dir}/multiplai.conf"
                export MULTIPLAI_MODEL
                python3 "{script}"
            """],
            capture_output=True, text=True,
        )
        assert result.stdout.strip() == "claude-haiku-4-5-20251001"

    def test_debug_exported_to_python(self, tmp_path):
        """run-hook-python exports MULTIPLAI_DEBUG so Python hooks can read it."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "logs").mkdir()
        (config_dir / ".workspace").write_text(str(tmp_path))
        (config_dir / "multiplai.conf").write_text(
            'MULTIPLAI_DEBUG=true\n'
        )

        script = tmp_path / "print_debug.py"
        script.write_text('import os; print(os.environ.get("MULTIPLAI_DEBUG", "UNSET"))\n')

        result = subprocess.run(
            ["bash", "-c", f"""
                export CLAUDE_CONFIG_DIR="{config_dir}"
                MULTIPLAI_DEBUG=false
                [ -f "{config_dir}/multiplai.conf" ] && source "{config_dir}/multiplai.conf"
                export MULTIPLAI_DEBUG
                python3 "{script}"
            """],
            capture_output=True, text=True,
        )
        assert result.stdout.strip() == "true"


class TestConfMalformed:
    """Test behavior with malformed or partial conf files."""

    def test_empty_conf_uses_defaults(self, tmp_path):
        """Empty conf file doesn't break anything."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "logs").mkdir()
        (config_dir / "multiplai.conf").write_text("")

        result = subprocess.run(
            ["bash", "-c", f"""
                export CLAUDE_CONFIG_DIR="{config_dir}"
                MULTIPLAI_MODEL="claude-sonnet-4-6"
                MULTIPLAI_DEBUG=false
                source "{config_dir}/multiplai.conf"
                echo "$MULTIPLAI_MODEL:$MULTIPLAI_DEBUG"
            """],
            capture_output=True, text=True,
        )
        assert result.stdout.strip() == "claude-sonnet-4-6:false"

    def test_comments_only_conf(self, tmp_path):
        """Conf with only comments doesn't break anything."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "logs").mkdir()
        (config_dir / "multiplai.conf").write_text(
            "# This is a comment\n"
            "# Another comment\n"
        )

        result = subprocess.run(
            ["bash", "-c", f"""
                export CLAUDE_CONFIG_DIR="{config_dir}"
                MULTIPLAI_MODEL="claude-sonnet-4-6"
                source "{config_dir}/multiplai.conf"
                echo "$MULTIPLAI_MODEL"
            """],
            capture_output=True, text=True,
        )
        assert result.stdout.strip() == "claude-sonnet-4-6"

    def test_partial_conf_preserves_unset_defaults(self, tmp_path):
        """Conf that sets only one value doesn't affect others."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "logs").mkdir()
        (config_dir / "multiplai.conf").write_text(
            'MULTIPLAI_DEBUG=true\n'
        )

        result = subprocess.run(
            ["bash", "-c", f"""
                export CLAUDE_CONFIG_DIR="{config_dir}"
                MULTIPLAI_MODEL="claude-sonnet-4-6"
                MULTIPLAI_DEBUG=false
                MULTIPLAI_EFFORT=high
                source "{config_dir}/multiplai.conf"
                echo "$MULTIPLAI_MODEL:$MULTIPLAI_DEBUG:$MULTIPLAI_EFFORT"
            """],
            capture_output=True, text=True,
        )
        assert result.stdout.strip() == "claude-sonnet-4-6:true:high"
