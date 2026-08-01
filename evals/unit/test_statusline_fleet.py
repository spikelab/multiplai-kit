"""The fleet segment in `statusline.sh`.

If you run several Claude Code tabs at once, the useful ambient fact is how
many other agents are up and whether any is waiting on you. The
multiplai-context plugin precomputes exactly that into one short line at
`$WORKSPACE/.multiplai/data/fleet.txt`; this segment displays it.

**The status line re-renders on every prompt**, which is what makes this
segment's cost the thing worth testing. It gets one read of one small
pre-computed file — the aggregation (140 registry entries, 183 checkpoint
directories) already happened elsewhere. A directory scan or a `python` call
here would tax every keystroke of every session, so those are asserted
absent from the source, not merely avoided today.

Everything else is degradation: absent file, empty file, no `WORKSPACE` at
all (vanilla Claude Code with no kit and no plugin). All three render nothing
and none of them may disturb the rest of the line.
"""

import re
import subprocess
from pathlib import Path

import pytest

STATUSLINE = Path(__file__).resolve().parents[2] / "dotfiles" / "scripts" / "statusline.sh"

READING = "6 fronts · 2 need you · oldest 3d · 1 collision"

# Strip ANSI SGR sequences so assertions read against what a human sees.
_ANSI = re.compile(r"\033\[[0-9;]*m")


def render(workspace=None, stdin="{}", **env):
    """Run the status line and return its plain-text output."""
    e = {"HOME": "/nonexistent-home", "PATH": "/usr/bin:/bin", **env}
    if workspace is not None:
        e["WORKSPACE"] = str(workspace)
    r = subprocess.run(
        ["bash", str(STATUSLINE)],
        input=stdin, capture_output=True, text=True, env=e, timeout=30,
    )
    assert r.returncode == 0, r.stderr
    return _ANSI.sub("", r.stdout)


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / ".multiplai" / "data").mkdir(parents=True)
    return tmp_path


def fleet_file(workspace):
    return workspace / ".multiplai" / "data" / "fleet.txt"


class TestRendering:

    def test_the_reading_is_rendered_as_a_segment(self, workspace):
        fleet_file(workspace).write_text(READING + "\n")

        out = render(workspace)

        assert READING in out
        assert out.count("|") >= 2, "the segment needs its own separator"

    def test_it_comes_last(self, workspace):
        """Ambient context belongs at the end — the model and cwd are what you
        look at deliberately."""
        fleet_file(workspace).write_text(READING + "\n")

        assert render(workspace).rstrip().endswith(READING)

    def test_only_the_first_line_is_used(self, workspace):
        """`fleet.txt` is contracted as one line. If a future writer ever emits
        more, the status line must not smear across the terminal."""
        fleet_file(workspace).write_text(READING + "\nand more\nand more\n")

        out = render(workspace)

        assert READING in out
        assert "and more" not in out
        assert "\n" not in out.strip()

    def test_a_file_with_no_trailing_newline_still_renders(self, workspace):
        fleet_file(workspace).write_text(READING)

        assert READING in render(workspace)


class TestDegradation:

    def test_an_absent_file_renders_nothing(self, workspace):
        """The plugin may not be installed, or may not have run yet."""
        out = render(workspace)

        assert "front" not in out
        assert out.count("|") == 1  # just the model/cwd separator

    def test_an_empty_file_renders_nothing(self, workspace):
        """`synthesize_agents.py` writes an empty file when no session is live,
        precisely so every tab does not carry a permanent `0 fronts`."""
        fleet_file(workspace).write_text("")

        assert render(workspace).count("|") == 1

    def test_a_whitespace_only_file_renders_nothing(self, workspace):
        fleet_file(workspace).write_text("\n")

        assert render(workspace).count("|") == 1

    def test_no_workspace_variable_renders_nothing(self):
        """Vanilla Claude Code: no kit, no container, no WORKSPACE. The
        degradation contract says work anyway, and say nothing about the kit."""
        out = render(workspace=None)

        assert "front" not in out
        assert "multiplai" not in out.lower()

    def test_an_unreadable_file_does_not_break_the_line(self, workspace):
        f = fleet_file(workspace)
        f.write_text(READING + "\n")
        f.chmod(0o000)
        try:
            out = render(workspace)
        finally:
            f.chmod(0o644)

        assert "?" in out  # the rest of the line still rendered

    def test_the_rest_of_the_line_is_unaffected(self, workspace):
        """Adding a segment must not perturb the ones already there."""
        blob = (
            '{"model":{"display_name":"Opus"},'
            '"workspace":{"current_dir":"/tmp/x"},'
            '"context_window":{"used_percentage":42},'
            '"cost":{"total_cost_usd":1.5}}'
        )
        without = render(workspace, stdin=blob)
        fleet_file(workspace).write_text(READING + "\n")
        with_fleet = render(workspace, stdin=blob)

        assert with_fleet.startswith(without)
        assert "Opus" in without and "42%" in without and "$1.50" in without


@pytest.fixture
def segment():
    """The fleet block's executable lines — comments stripped, since the
    assertions below are about what the shell does, not what it explains."""
    src = STATUSLINE.read_text()
    block = src.split("# Fleet reading", 1)[1].split("# Assemble", 1)[0]
    return "\n".join(
        ln for ln in block.splitlines() if ln.strip() and not ln.lstrip().startswith("#")
    )


class TestHotPathCost:
    """This runs on every prompt render. What it must NOT do is the test."""

    def test_no_python(self, segment):
        assert "python" not in segment

    def test_no_directory_scan_glob_or_loop(self, segment):
        for forbidden in ("ls ", "find ", "*.", "/*", "for ", "while "):
            assert forbidden not in segment, f"{forbidden!r} in the hot path"

    def test_it_touches_exactly_one_path(self, segment):
        """`fleet.txt` and nothing else — never the 140 registry entries or the
        183 checkpoint directories behind it."""
        assert segment.count("fleet_file") == 3  # assign, -s test, read redirect
        assert "checkpoints" not in segment
        assert "sessions" not in segment

    def test_it_uses_a_builtin_not_a_fork(self, segment):
        """`cat`, `head` or `jq` here would fork a process per prompt render."""
        assert "read -r fleet" in segment
        for forked in ("cat ", "head ", "tail ", "jq ", "awk ", "sed "):
            assert forked not in segment
