"""Tests for guard_destructive.py — the PreToolUse destructive-command guard.

The guard's value depends entirely on its calibration. Too loose and it is
theatre; too tight and it blocks the ordinary work of a session, which trains
whoever hits it to disable the hook. Both directions are tested here.
"""

import io
import json

import pytest

from guard_destructive import check, main


def _denied(command: str) -> bool:
    return check(command) is not None


class TestDeniesUnrecoverableCommands:
    @pytest.mark.parametrize("command", [
        "rm -rf /home",
        "rm -rf /Users/spike/Documents",
        "rm -rf ~/Library",
        "rm -rf $HOME/projects",
        "sudo rm -rf /etc/nginx",
    ])
    def test_recursive_delete_outside_workspace(self, command):
        assert _denied(command), command

    def test_deleting_multiplai_state(self):
        assert _denied("rm -rf .multiplai/memory")
        assert _denied("rm .multiplai/learnings/2026-07-25.md")

    @pytest.mark.parametrize("command", [
        "git push --force origin main",
        "git push -f origin main",
        "git push origin main --force",
        "git push --force upstream master",
    ])
    def test_force_push_to_protected_branch(self, command):
        assert _denied(command), command

    def test_hard_reset_to_remote(self):
        assert _denied("git reset --hard origin/main")

    @pytest.mark.parametrize("command", [
        "docker system prune -af",
        "docker volume prune",
        "docker volume rm multiplai-data",
    ])
    def test_docker_prune(self, command):
        assert _denied(command), command

    @pytest.mark.parametrize("command", [
        'psql -c "DROP TABLE users"',
        'sqlite3 app.db "DROP DATABASE prod"',
        'mysql -e "TRUNCATE TABLE orders"',
        'psql -c "DELETE FROM sessions;"',
    ])
    def test_destructive_sql(self, command):
        assert _denied(command), command

    def test_github_deletions(self):
        assert _denied("gh repo delete spikelab/multiplai-kit")
        assert _denied("gh release delete v0.4")

    def test_history_rewrite(self):
        assert _denied("git filter-repo --path secrets --invert-paths")

    def test_disk_overwrite(self):
        assert _denied("dd if=/dev/zero of=/dev/disk2 bs=1m")
        assert _denied("mkfs.ext4 of=/dev/sda1")


class TestAllowsOrdinaryWork:
    """A guard that blocks normal work gets disabled, and then protects
    nothing. These are the commands a session runs constantly."""

    @pytest.mark.parametrize("command", [
        "git status",
        "git push origin feat/my-branch",
        "git push --force-with-lease origin feat/my-branch",
        "git commit -m 'fix: thing'",
        "rm -rf /tmp/claude-501/scratch",
        "rm build/output.txt",
        "rm -rf node_modules",
        "pytest tests/ -q",
        "docker stop mycontainer",
        "git worktree remove .worktrees/feature",
        'psql -c "DELETE FROM sessions WHERE id = 3"',
        "gh pr create --title x",
        "gh issue close 12",
    ])
    def test_not_denied(self, command):
        assert not _denied(command), command

    def test_workspace_scoped_recursive_delete(self, monkeypatch):
        """Cleaning up inside the workspace is the agent's own job."""
        monkeypatch.setenv("WORKSPACE", "/Users/spike/Documents/knowhere")
        assert not _denied("rm -rf /Users/spike/Documents/knowhere/build")

    def test_delete_with_where_clause_is_fine(self):
        assert not _denied('psql -c "DELETE FROM logs WHERE ts < now()"')

    def test_empty_command(self):
        assert not _denied("")
        assert not _denied("   ")


class TestHookProtocol:
    def _run(self, payload, monkeypatch, capsys):
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
        rc = main()
        return rc, capsys.readouterr().out

    def test_denial_emits_the_documented_shape(self, monkeypatch, capsys):
        rc, out = self._run(
            {"tool_name": "Bash", "tool_input": {"command": "rm -rf /home"}},
            monkeypatch, capsys)
        assert rc == 0
        decision = json.loads(out)["hookSpecificOutput"]
        assert decision["hookEventName"] == "PreToolUse"
        assert decision["permissionDecision"] == "deny"
        assert "ask" in decision["permissionDecisionReason"].lower()

    def test_allowed_command_emits_nothing(self, monkeypatch, capsys):
        rc, out = self._run(
            {"tool_name": "Bash", "tool_input": {"command": "ls -la"}},
            monkeypatch, capsys)
        assert rc == 0
        assert out == ""

    def test_non_bash_tools_pass_through(self, monkeypatch, capsys):
        """The guard reads shell commands; a Write call has no command to
        inspect and must not be second-guessed here."""
        rc, out = self._run(
            {"tool_name": "Write", "tool_input": {"file_path": "/etc/passwd"}},
            monkeypatch, capsys)
        assert rc == 0 and out == ""

    def test_malformed_stdin_never_wedges_the_session(self, monkeypatch, capsys):
        monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
        assert main() == 0
        assert capsys.readouterr().out == ""

    def test_missing_command_key(self, monkeypatch, capsys):
        rc, out = self._run({"tool_name": "Bash", "tool_input": {}},
                            monkeypatch, capsys)
        assert rc == 0 and out == ""


class TestDenialMessage:
    def test_names_the_rule_and_tells_the_agent_to_ask(self):
        name, why = check("rm -rf /home")
        assert name == "recursive-delete-outside-workspace"
        assert why  # non-empty explanation shown to the agent
