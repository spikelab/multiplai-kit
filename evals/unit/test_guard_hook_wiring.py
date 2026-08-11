"""Pins the wiring that decides whether the destructive-command guard runs.

The guard's *rules* are tested in `test_guard_destructive.py`. This file tests
the thing that turned out to matter just as much: whether the guard is reached
at all.

It exists because of kit #26. Every hook command in `settings.json` ended with
`2>>$CLAUDE_MULTIPLAI_HOME/runtime/logs/hook-errors.log`, and the shell opens
that redirect *before* exec'ing anything. `runtime/logs/` is created by
`setup.sh`, so in a fresh clone or worktree it does not exist, the redirect
failed with `Directory nonexistent`, and the hook never ran. A PreToolUse hook
that errors is reported once and then ignored — so every Bash call in that
session ran with the guard inert, behind a single line of stderr on the first
call and silence afterwards.

Three properties, all one-edit fragile:

  * **The guard's hook command carries no shell redirect.** This is the
    regression itself. Re-adding a `2>>` to that line restores the fail-open.
  * **`run-hook-python` creates its own log directory** rather than assuming
    setup.sh ran, so nothing downstream has to.
  * **The wrapper denies when the guard cannot run.** A guard that cannot
    reach a verdict must not let the command through — the issue is explicit
    that `|| true` on that line would be the wrong fix.

Driven by stubs: a fake `run-hook-python` in a fake config dir. No Python
resolution, no venv, no real hook involved.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

KIT_ROOT = Path(__file__).resolve().parents[2]
SETTINGS = KIT_ROOT / "dotfiles" / "settings.json"
HOOKS = KIT_ROOT / "dotfiles" / "hooks"
WRAPPER = HOOKS / "guard-destructive.sh"

BASH_PAYLOAD = json.dumps(
    {"tool_name": "Bash", "tool_input": {"command": "echo hello"}}
)


def _hook_commands(event: str, matcher: str | None = None) -> list[str]:
    settings = json.loads(SETTINGS.read_text())
    out = []
    for group in settings["hooks"][event]:
        if matcher is not None and group.get("matcher") != matcher:
            continue
        out += [h["command"] for h in group["hooks"]]
    return out


class TestSettingsWiring:
    def test_guard_command_has_no_shell_redirect(self):
        """The regression from kit #26, stated as a test.

        The guard is the only enforcement layer in bypass-permissions mode; it
        must not be reachable only when a log directory happens to exist.
        """
        guard = [c for c in _hook_commands("PreToolUse", "Bash") if "guard" in c]
        assert len(guard) == 1, guard
        assert "2>>" not in guard[0], (
            "the guard hook command must not redirect stderr in the shell — "
            "the redirect is what broke it in a fresh checkout"
        )

    def test_guard_command_is_not_swallowed(self):
        """`|| true` here would hide the failure instead of fixing it."""
        guard = [c for c in _hook_commands("PreToolUse", "Bash") if "guard" in c]
        assert "|| true" not in guard[0]

    @pytest.mark.parametrize(
        "event,matcher",
        [("SessionStart", None), ("PreToolUse", "Bash"),
         ("PostToolUse", "Write|Edit|NotebookEdit")],
    )
    def test_every_redirecting_command_creates_the_directory_first(self, event, matcher):
        """Any command that still redirects must make its own sink first.

        The guard is immune now, but a hook that dies on the redirect is a
        hook that silently stopped working — true for the syntax validator and
        the token-refresh hooks as much as for the guard.
        """
        for command in _hook_commands(event, matcher):
            if "2>>" not in command:
                continue
            assert command.startswith("mkdir -p $CLAUDE_MULTIPLAI_HOME/runtime/logs"), (
                f"{command!r} redirects into runtime/logs without creating it"
            )


class TestRunHookPythonOwnsItsLogDir:
    def test_creates_logs_dir_when_missing(self, tmp_path):
        """A fresh checkout has no runtime/logs; the wrapper makes one."""
        home = tmp_path / "kit"
        (home / "dotfiles").mkdir(parents=True)
        script = tmp_path / "noop.py"
        script.write_text("")

        assert not (home / "runtime" / "logs").exists()
        subprocess.run(
            ["bash", str(HOOKS / "run-hook-python"), str(script)],
            env={**os.environ, "CLAUDE_MULTIPLAI_HOME": str(home)},
            input="",
            capture_output=True,
            text=True,
            check=True,
        )
        assert (home / "runtime" / "logs").is_dir()


class TestWrapperFailsClosed:
    """A guard that cannot reach a verdict must deny, not wave the call through."""

    def _config_dir(self, tmp_path: Path, run_hook_body: str) -> Path:
        config = tmp_path / "dotfiles"
        (config / "hooks").mkdir(parents=True)
        (config / "hooks" / "run-hook-python").write_text(run_hook_body)
        (config / "hooks" / "guard_destructive.py").write_text("")
        return config

    def _run(self, config: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(WRAPPER)],
            env={**os.environ, "CLAUDE_CONFIG_DIR": str(config)},
            input=BASH_PAYLOAD,
            capture_output=True,
            text=True,
        )

    def test_denies_when_the_guard_cannot_run(self, tmp_path):
        config = self._config_dir(tmp_path, "#!/bin/bash\nexit 127\n")
        result = self._run(config)

        assert result.returncode == 0, "the wrapper itself must never error"
        decision = json.loads(result.stdout)["hookSpecificOutput"]
        assert decision["permissionDecision"] == "deny"
        assert "127" in decision["permissionDecisionReason"]

    def test_silent_when_the_guard_allows(self, tmp_path):
        """No verdict on stdout is how PreToolUse says 'carry on'."""
        config = self._config_dir(tmp_path, "#!/bin/bash\nexit 0\n")
        result = self._run(config)

        assert result.returncode == 0
        assert result.stdout.strip() == ""

    def test_passes_the_guards_deny_through_unchanged(self, tmp_path):
        """The wrapper must not reformat or re-wrap a real verdict."""
        verdict = json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": "docker-prune",
                }
            }
        )
        config = self._config_dir(
            tmp_path, f"#!/bin/bash\ncat >/dev/null\nprintf '%s' '{verdict}'\nexit 0\n"
        )
        result = self._run(config)

        assert json.loads(result.stdout) == json.loads(verdict)

    def test_forwards_stdin_to_the_guard(self, tmp_path):
        """The guard reads the command off stdin — a wrapper that eats it
        would turn every call into a no-op verdict."""
        seen = tmp_path / "seen.json"
        config = self._config_dir(
            tmp_path, f"#!/bin/bash\ncat > {seen}\nexit 0\n"
        )
        self._run(config)

        assert json.loads(seen.read_text()) == json.loads(BASH_PAYLOAD)
