"""Snapshot + revert, and the CLI wiring.

plan-cli itself is mocked everywhere — these tests never touch tasks.db.
"""

import json
from pathlib import Path

import pytest

from prioritize_session import __main__ as cli
from prioritize_session import plan_cli, render, session


def task(**overrides):
    base = {
        "id": 1,
        "title": "Something",
        "type": "sales",
        "importance": "medium",
        "due": None,
        "duration": None,
        "rank": 1,
        "status": "backlog",
        "captured": "2026-07-20",
        "done_when": None,
        "notes": None,
        "start": None,
    }
    base.update(overrides)
    return base


@pytest.fixture
def snapshot_home(tmp_path, monkeypatch):
    """Redirect snapshots into the test's tmp dir."""
    monkeypatch.setenv("CLAUDE_MULTIPLAI_HOME", str(tmp_path))
    return tmp_path / "runtime" / "prioritize"


class TestSnapshots:
    def test_save_and_load_round_trip(self, snapshot_home):
        backlog = {"active": None, "tasks": [task(id=1), task(id=2)]}
        path = session.save_snapshot(backlog, "abc12345")
        assert path.parent == snapshot_home
        assert "abc12345" in path.name
        assert session.load_snapshot(path) == backlog

    def test_latest_snapshot_picks_the_newest(self, snapshot_home):
        snapshot_home.mkdir(parents=True, exist_ok=True)
        (snapshot_home / "backlog-20260101T000000Z.json").write_text("{}")
        (snapshot_home / "backlog-20260722T120000Z.json").write_text("{}")
        assert session.latest_snapshot().name == "backlog-20260722T120000Z.json"

    def test_latest_snapshot_is_none_when_empty(self, snapshot_home):
        assert session.latest_snapshot() is None


class TestRevertChangeset:
    def test_restores_order_importance_and_focus(self):
        snapshot = {
            "active": task(id=9, importance="high"),
            "tasks": [
                task(id=1, importance="low", rank=3),
                task(id=2, importance="high", rank=1),
            ],
        }
        changeset, unrestorable = session.revert_changeset(snapshot)
        assert changeset["now"] == 9
        # Focus first, then importance-then-rank — plan-cli's own render order.
        assert changeset["order"] == [9, 2, 1]
        assert changeset["updates"]["1"]["importance"] == "low"
        assert changeset["updates"]["2"]["importance"] == "high"
        assert unrestorable == []

    def test_clears_a_due_the_session_added(self):
        # The snapshot had no due; restating it as null is what clears it.
        changeset, _ = session.revert_changeset({"active": None, "tasks": [task(id=1, due=None)]})
        assert changeset["updates"]["1"]["due"] is None

    def test_revert_changeset_renders_cleanly(self):
        snapshot = {"active": task(id=9, importance="high", type=None),
                    "tasks": [task(id=1, importance="low", type=None)]}
        changeset, _ = session.revert_changeset(snapshot)
        markdown = render.render_backlog(snapshot, changeset)
        assert "[9] [high] [now]" in markdown
        assert "## Low" in markdown

    def test_no_active_task_reverts_to_no_focus(self):
        changeset, _ = session.revert_changeset({"active": None, "tasks": [task(id=1)]})
        assert changeset["now"] is None

    def test_tasks_completed_during_the_session_are_dropped_not_fatal(self):
        # The whole point of the safety net is that it still works after a
        # session that actually finished something.
        snapshot = {"active": None, "tasks": [task(id=1), task(id=2)]}
        changeset, unrestorable = session.revert_changeset(snapshot, present_ids={1})
        assert unrestorable == [2]
        assert changeset["order"] == [1]
        assert "2" not in changeset["updates"]

    def test_a_completed_focus_task_is_dropped_and_focus_cleared(self):
        snapshot = {"active": task(id=9), "tasks": [task(id=1)]}
        changeset, unrestorable = session.revert_changeset(snapshot, present_ids={1})
        assert unrestorable == [9]
        assert changeset["now"] is None


class TestCli:
    def test_brief_prints_json_and_can_snapshot(self, snapshot_home, monkeypatch, capsys):
        monkeypatch.setattr(
            plan_cli, "read_backlog", lambda: {"active": None, "tasks": [task(id=1)]}
        )
        assert cli.main(["--session-id", "s1", "brief", "--snapshot"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["counts"]["total"] == 1
        assert Path(payload["snapshot_path"]).is_file()

    def test_brief_without_snapshot_writes_nothing(self, snapshot_home, monkeypatch, capsys):
        monkeypatch.setattr(plan_cli, "read_backlog", lambda: {"active": None, "tasks": []})
        cli.main(["brief"])
        assert "snapshot_path" not in json.loads(capsys.readouterr().out)

    def test_detail_returns_the_bulky_fields_and_reports_misses(self, monkeypatch, capsys):
        monkeypatch.setattr(
            plan_cli,
            "read_backlog",
            lambda: {"active": None, "tasks": [task(id=1, notes="context", start=["a"])]},
        )
        cli.main(["detail", "--ids", "1,42"])
        payload = json.loads(capsys.readouterr().out)
        assert payload["tasks"][0]["notes"] == "context"
        assert payload["tasks"][0]["start"] == ["a"]
        assert payload["missing"] == [42]

    def test_dry_run_renders_without_calling_plan_cli(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(
            plan_cli, "read_backlog", lambda: {"active": None, "tasks": [task(id=1, type=None)]}
        )

        def explode(*_args, **_kwargs):
            raise AssertionError("dry run must not write")

        monkeypatch.setattr(plan_cli, "apply_backlog", explode)

        changes = tmp_path / "changes.json"
        changes.write_text(json.dumps({"updates": {"1": {"importance": "high"}}}))
        assert cli.main(["apply", "--changes", str(changes), "--dry-run"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["dry_run"] is True
        assert "## High" in payload["markdown"]
        assert "snapshot_path" not in payload

    def test_apply_snapshots_then_hands_the_file_to_plan_cli(
        self, snapshot_home, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.setattr(
            plan_cli, "read_backlog", lambda: {"active": None, "tasks": [task(id=1, type=None)]}
        )
        seen = {}

        def fake_apply(path: Path):
            seen["markdown"] = Path(path).read_text(encoding="utf-8")
            seen["path"] = Path(path)
            return "Updated 1 task"

        monkeypatch.setattr(plan_cli, "apply_backlog", fake_apply)

        changes = tmp_path / "changes.json"
        changes.write_text(json.dumps({"updates": {"1": {"importance": "high"}}}))
        assert cli.main(["--session-id", "s2", "apply", "--changes", str(changes)]) == 0

        payload = json.loads(capsys.readouterr().out)
        assert payload["applied"] is True
        assert payload["summary"] == "Updated 1 task"
        assert Path(payload["snapshot_path"]).is_file()
        assert "## High" in seen["markdown"]
        # The temp file is cleaned up after plan-cli reads it.
        assert not seen["path"].exists()

    def test_bad_changeset_exits_nonzero_without_writing(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(
            plan_cli, "read_backlog", lambda: {"active": None, "tasks": [task(id=1)]}
        )

        def explode(*_args, **_kwargs):
            raise AssertionError("must not write on a bad changeset")

        monkeypatch.setattr(plan_cli, "apply_backlog", explode)

        changes = tmp_path / "changes.json"
        changes.write_text(json.dumps({"updates": {"99": {"importance": "high"}}}))
        assert cli.main(["apply", "--changes", str(changes)]) == 1
        assert "not in the current backlog" in capsys.readouterr().err

    def test_plan_cli_failure_surfaces_as_exit_1(self, monkeypatch, capsys):
        def explode():
            raise plan_cli.PlanCliError("plan-cli exited 1")

        monkeypatch.setattr(plan_cli, "read_backlog", explode)
        assert cli.main(["brief"]) == 1
        assert "plan-cli exited 1" in capsys.readouterr().err

    def test_revert_without_a_snapshot_exits_1(self, snapshot_home, capsys):
        assert cli.main(["revert"]) == 1
        assert "No snapshot" in capsys.readouterr().err

    def test_revert_replays_the_snapshot(self, snapshot_home, monkeypatch, capsys):
        original = {"active": None, "tasks": [task(id=1, importance="low", type=None)]}
        snapshot_path = session.save_snapshot(original, "s3")

        # The live backlog has drifted — 1 was promoted during the session.
        monkeypatch.setattr(
            plan_cli,
            "read_backlog",
            lambda: {"active": None, "tasks": [task(id=1, importance="high", type=None)]},
        )
        seen = {}
        monkeypatch.setattr(
            plan_cli,
            "apply_backlog",
            lambda path: seen.setdefault("markdown", Path(path).read_text(encoding="utf-8")) and "ok",
        )

        assert cli.main(["revert", "--snapshot", str(snapshot_path)]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["reverted_from"] == str(snapshot_path)
        assert payload["unrestorable"] == []
        # Back to Low, as the snapshot had it.
        assert "## Low" in seen["markdown"]
        assert "## High" not in seen["markdown"]

    def test_revert_reports_tasks_it_could_not_restore(self, snapshot_home, monkeypatch, capsys):
        original = {"active": None, "tasks": [task(id=1, type=None), task(id=2, type=None)]}
        snapshot_path = session.save_snapshot(original, "s4")

        # Task 2 was completed during the session.
        monkeypatch.setattr(
            plan_cli, "read_backlog", lambda: {"active": None, "tasks": [task(id=1, type=None)]}
        )
        monkeypatch.setattr(plan_cli, "apply_backlog", lambda _path: "ok")

        assert cli.main(["revert", "--snapshot", str(snapshot_path)]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["applied"] is True
        assert payload["unrestorable"] == [2]


class TestResolvePlanCli:
    def test_explicit_bin_wins(self, tmp_path, monkeypatch):
        binary = tmp_path / "plan"
        binary.write_text("#!/bin/sh\n")
        monkeypatch.setenv("PLAN_CLI_BIN", str(binary))
        assert plan_cli.resolve_plan_cli() == [str(binary)]

    def test_js_entry_point_runs_through_node(self, tmp_path, monkeypatch):
        entry = tmp_path / "bin" / "plan.js"
        entry.parent.mkdir()
        entry.write_text("// plan")
        monkeypatch.setenv("PLAN_CLI_BIN", str(entry))
        monkeypatch.setattr(plan_cli.shutil, "which", lambda name: "/usr/bin/node" if name == "node" else None)
        assert plan_cli.resolve_plan_cli() == ["/usr/bin/node", str(entry)]

    def test_workspace_fallback(self, tmp_path, monkeypatch):
        entry = tmp_path / "github" / "plan-cli" / "bin" / "plan.js"
        entry.parent.mkdir(parents=True)
        entry.write_text("// plan")
        monkeypatch.delenv("PLAN_CLI_BIN", raising=False)
        monkeypatch.delenv("PLAN_CLI_HOME", raising=False)
        monkeypatch.setenv("WORKSPACE", str(tmp_path))
        monkeypatch.setattr(plan_cli.shutil, "which", lambda name: "/usr/bin/node" if name == "node" else None)
        assert plan_cli.resolve_plan_cli() == ["/usr/bin/node", str(entry)]

    def test_missing_plan_cli_is_a_clear_error(self, tmp_path, monkeypatch):
        monkeypatch.delenv("PLAN_CLI_BIN", raising=False)
        monkeypatch.delenv("PLAN_CLI_HOME", raising=False)
        monkeypatch.setenv("WORKSPACE", str(tmp_path))
        monkeypatch.setattr(plan_cli.shutil, "which", lambda _name: None)
        with pytest.raises(plan_cli.PlanCliError, match="Could not find plan-cli"):
            plan_cli.resolve_plan_cli()


class TestPlanningDir:
    def test_env_override(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PLANNING_DIR", str(tmp_path))
        assert plan_cli.planning_dir() == tmp_path

    def test_defaults_to_home_planning(self, monkeypatch):
        monkeypatch.delenv("PLANNING_DIR", raising=False)
        assert plan_cli.planning_dir().name == "planning"
