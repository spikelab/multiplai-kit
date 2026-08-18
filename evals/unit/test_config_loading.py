"""Unit tests for multiplai.conf loading via the real run-hook-python.

These invoke the actual `dotfiles/hooks/run-hook-python` wrapper — not an
inline re-implementation — so a regression in its (eval-free) conf parser or
its env-export list is actually caught. run-hook-python reads the conf from
`$CLAUDE_MULTIPLAI_HOME/multiplai.conf`, parses KEY=value without eval, and
exports MULTIPLAI_{DEBUG,MODEL,EFFORT,LOG_LEVEL} to the invoked Python process.
"""

import subprocess
from pathlib import Path

from conftest import KIT_ROOT

RUN_HOOK_PYTHON = KIT_ROOT / "dotfiles" / "hooks" / "run-hook-python"


def _run(home: Path, conf: str | None, var: str) -> str:
    """Write `conf` (if given) to $home/multiplai.conf, then invoke the real
    run-hook-python on a script that prints os.environ[var]. Returns stdout."""
    if conf is not None:
        (home / "multiplai.conf").write_text(conf)
    script = home / "print_env.py"
    script.write_text(f'import os; print(os.environ.get("{var}", "UNSET"))\n')
    result = subprocess.run(
        ["bash", str(RUN_HOOK_PYTHON), str(script)],
        capture_output=True, text=True,
        env={
            "PATH": "/usr/bin:/bin:/usr/local/bin",
            "CLAUDE_MULTIPLAI_HOME": str(home),
            "CLAUDE_CONFIG_DIR": str(home / "config"),
        },
    )
    return result.stdout.strip()


class TestConfigDefaults:
    def test_default_model_without_conf(self, tmp_path):
        assert _run(tmp_path, None, "MULTIPLAI_MODEL") == "claude-sonnet-4-6"

    def test_default_debug_without_conf(self, tmp_path):
        assert _run(tmp_path, None, "MULTIPLAI_DEBUG") == "false"

    def test_default_effort_without_conf(self, tmp_path):
        assert _run(tmp_path, None, "MULTIPLAI_EFFORT") == "high"


class TestConfigOverrides:
    def test_model_override(self, tmp_path):
        out = _run(tmp_path, 'MULTIPLAI_MODEL="claude-haiku-4-5-20251001"\n',
                   "MULTIPLAI_MODEL")
        assert out == "claude-haiku-4-5-20251001"

    def test_debug_override(self, tmp_path):
        assert _run(tmp_path, "MULTIPLAI_DEBUG=true\n", "MULTIPLAI_DEBUG") == "true"

    def test_effort_override(self, tmp_path):
        assert _run(tmp_path, "MULTIPLAI_EFFORT=medium\n", "MULTIPLAI_EFFORT") == "medium"

    def test_log_level_is_exported(self, tmp_path):
        # Regression: MULTIPLAI_LOG_LEVEL was set in conf but not exported, so
        # the log-level knob silently did nothing for hook-invoked scripts.
        assert _run(tmp_path, "MULTIPLAI_LOG_LEVEL=DEBUG\n", "MULTIPLAI_LOG_LEVEL") == "DEBUG"


class TestConfMalformed:
    def test_empty_conf_uses_defaults(self, tmp_path):
        assert _run(tmp_path, "", "MULTIPLAI_MODEL") == "claude-sonnet-4-6"

    def test_comments_only_conf(self, tmp_path):
        assert _run(tmp_path, "# a comment\n# another\n", "MULTIPLAI_MODEL") == "claude-sonnet-4-6"

    def test_inline_comment_stripped(self, tmp_path):
        out = _run(tmp_path, "MULTIPLAI_EFFORT=medium  # trailing note\n", "MULTIPLAI_EFFORT")
        assert out == "medium"


class TestConfSecurity:
    """The parser must never execute values or subscripts from the conf
    (CWE-78): a committed/tampered conf is untrusted input."""

    def test_value_is_not_executed(self, tmp_path):
        # A command-substitution in a value must arrive as literal data.
        (tmp_path / "canary").unlink(missing_ok=True)
        out = _run(
            tmp_path,
            f'MULTIPLAI_MODEL=$(touch {tmp_path}/canary)\n',
            "MULTIPLAI_MODEL",
        )
        assert not (tmp_path / "canary").exists(), "conf value was executed"
        # The literal text is fine; execution is not.
        assert "canary" in out or out == f"$(touch {tmp_path}/canary)"

    def test_array_subscript_key_is_not_executed(self, tmp_path):
        # A key like MULTIPLAI_A[$(...)] must be rejected, not fed to printf -v
        # (which would command-substitute the subscript).
        (tmp_path / "canary2").unlink(missing_ok=True)
        _run(
            tmp_path,
            f'MULTIPLAI_A[$(touch {tmp_path}/canary2)]=x\n',
            "MULTIPLAI_MODEL",
        )
        assert not (tmp_path / "canary2").exists(), "conf key subscript was executed"

    def test_debug_value_is_not_run_as_command(self, tmp_path):
        # _debug must compare MULTIPLAI_DEBUG as data, never run it.
        (tmp_path / "canary3").unlink(missing_ok=True)
        _run(
            tmp_path,
            f'MULTIPLAI_DEBUG=touch {tmp_path}/canary3\n',
            "MULTIPLAI_DEBUG",
        )
        assert not (tmp_path / "canary3").exists(), "MULTIPLAI_DEBUG was executed"
