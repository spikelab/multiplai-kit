"""Tests for validate-syntax.sh — the PostToolUse Write|Edit|NotebookEdit hook.

The hook's contract with the harness is narrow and easy to break silently:
feedback reaches the model ONLY via exit code 2 with the message on stderr.
Exit 1, or exit 2 with an empty stderr, and the model is never told the file
it just wrote is broken — the hook still "runs", green, doing nothing.

That silent mode shipped once already: under `set -euo pipefail`, the message
probe's `ERROR=$(...)` assignment died whenever the probe raised anything but
the *expected* exception class (demonstrated with a non-UTF-8 `.json` file —
UnicodeDecodeError, not JSONDecodeError), so the hook exited 1 with no output
at all. The non-UTF-8 cases below pin the fix; the rest pins the contract
around it.

The hook resolves its Python from `$CLAUDE_MULTIPLAI_HOME/.venv/bin/python`;
the fixture points that at the interpreter running this suite (which has
pyyaml), so the YAML branch is genuinely exercised rather than silently
skipped.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

KIT_ROOT = Path(__file__).resolve().parents[2]
HOOK = KIT_ROOT / "dotfiles" / "hooks" / "validate-syntax.sh"


@pytest.fixture
def home(tmp_path):
    """A fake CLAUDE_MULTIPLAI_HOME whose venv python is this interpreter.

    An exec wrapper, not a symlink: CPython resolves a symlink before looking
    for pyvenv.cfg, so a symlinked venv python silently loses its venv (and
    with it pyyaml) — the YAML branch would skip and the tests would pass
    vacuously.
    """
    venv_bin = tmp_path / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    wrapper = venv_bin / "python"
    wrapper.write_text(f'#!/bin/bash\nexec "{sys.executable}" "$@"\n')
    wrapper.chmod(0o755)
    return tmp_path


def run_hook(home, payload, **extra_env):
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(home),
        "CLAUDE_MULTIPLAI_HOME": str(home),
        "CLAUDE_CONFIG_DIR": str(home / "dotfiles"),
    }
    env.update(extra_env)
    return subprocess.run(
        ["bash", str(HOOK)],
        input=json.dumps(payload) if isinstance(payload, dict) else payload,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def write_payload(path):
    return {
        "hook_event_name": "PostToolUse",
        "tool_name": "Write",
        "tool_input": {"file_path": str(path)},
    }


class TestValidFilesPass:
    def test_valid_json(self, home, tmp_path):
        f = tmp_path / "ok.json"
        f.write_text('{"a": [1, 2], "b": null}\n')
        result = run_hook(home, write_payload(f))
        assert result.returncode == 0
        assert result.stderr == ""

    def test_valid_yaml(self, home, tmp_path):
        f = tmp_path / "ok.yaml"
        f.write_text("a: 1\nb:\n  - x\n  - y\n")
        result = run_hook(home, write_payload(f))
        assert result.returncode == 0
        assert result.stderr == ""

    def test_other_extensions_are_not_validated(self, home, tmp_path):
        f = tmp_path / "notes.md"
        f.write_text("{not json, not yaml: [\n")
        result = run_hook(home, write_payload(f))
        assert result.returncode == 0


class TestBrokenFilesBlock:
    """Exit 2 + a message on stderr is the ONE shape the harness feeds back."""

    def test_broken_json(self, home, tmp_path):
        f = tmp_path / "broken.json"
        f.write_text('{"a": 1,}\n')  # trailing comma
        result = run_hook(home, write_payload(f))
        assert result.returncode == 2, result.stderr
        assert "JSON syntax error" in result.stderr
        assert str(f) in result.stderr

    def test_broken_yaml(self, home, tmp_path):
        f = tmp_path / "broken.yaml"
        f.write_text("a: [1, 2\nb: :\n")
        result = run_hook(home, write_payload(f))
        assert result.returncode == 2, result.stderr
        assert "YAML syntax error" in result.stderr

    @pytest.mark.parametrize("ext", ["json", "yaml"])
    def test_non_utf8_file_blocks_with_a_message(self, home, tmp_path, ext):
        """The previously-silent case: UnicodeDecodeError is not the expected
        parse-error class, and under `set -e` the old probe died before
        emit_error — exit 1, empty stderr, model never told."""
        f = tmp_path / f"binary.{ext}"
        f.write_bytes(b"\xff\xfe\x00garbage")
        result = run_hook(home, write_payload(f))
        assert result.returncode == 2, (result.returncode, result.stderr)
        assert result.stderr.strip(), "a blocked file must carry a diagnosis"
        assert str(f) in result.stderr


class TestNotebookEdit:
    """NotebookEdit carries notebook_path, and a notebook is JSON."""

    def test_broken_notebook_blocks(self, home, tmp_path):
        f = tmp_path / "nb.ipynb"
        f.write_text('{"cells": [,]}')
        payload = {
            "hook_event_name": "PostToolUse",
            "tool_name": "NotebookEdit",
            "tool_input": {"notebook_path": str(f)},
        }
        result = run_hook(home, payload)
        assert result.returncode == 2, result.stderr
        assert "JSON syntax error" in result.stderr

    def test_valid_notebook_passes(self, home, tmp_path):
        f = tmp_path / "nb.ipynb"
        f.write_text('{"cells": [], "nbformat": 4, "nbformat_minor": 5}')
        payload = {
            "hook_event_name": "PostToolUse",
            "tool_name": "NotebookEdit",
            "tool_input": {"notebook_path": str(f)},
        }
        result = run_hook(home, payload)
        assert result.returncode == 0, result.stderr


class TestNeverWedgesTheSession:
    def test_missing_file_exits_zero(self, home, tmp_path):
        result = run_hook(home, write_payload(tmp_path / "never-written.json"))
        assert result.returncode == 0

    def test_missing_file_path_exits_zero(self, home):
        result = run_hook(home, {
            "hook_event_name": "PostToolUse",
            "tool_name": "Write",
            "tool_input": {},
        })
        assert result.returncode == 0

    def test_malformed_stdin_exits_zero(self, home):
        result = run_hook(home, "not json")
        assert result.returncode == 0

    def test_child_session_guard_short_circuits(self, home, tmp_path):
        """SDK-spawned sessions (multiplai-core sets _HOOK_CHILD_SESSION) must
        pay nothing — not even for a genuinely broken file."""
        f = tmp_path / "broken.json"
        f.write_text('{"a": 1,}')
        result = run_hook(home, write_payload(f), _HOOK_CHILD_SESSION="1")
        assert result.returncode == 0
        assert result.stderr == ""
