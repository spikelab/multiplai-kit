"""Pins `dotfiles/scripts/fleet-watch` — the fleet board in a spare terminal.

This is the one host-side fleet script a *person* runs, and that inverts the
rule the other two follow. `fleet-bar` and `fleet-viewed.sh` are silent on every
failure path because their output goes into a status bar or a hook; here the
output goes to someone who is looking at it, so an unresolvable workspace has to
say so rather than draw an empty board forever.

The loop itself is not tested — a redraw timer around `read -t` has nothing in
it to break, and driving it would mean owning a pty. What is pinned is
everything that happens before the first redraw:

* it resolves the workspace the same way `fleet-bar` does, environment first;
* it fails **loudly** and non-zero when it cannot;
* it hands the renderer the window's own size, not a status bar's three lines;
* off a terminal it draws once and leaves, rather than spinning.

That last one is not hypothetical: waiting on a keypress needs a tty, and
without one the wait returns instantly — a busy loop redrawing forever at full
speed instead of a board. Every test here runs down that branch, so it is also
what makes the rest of the file possible.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

KIT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = KIT_ROOT / "dotfiles" / "scripts" / "fleet-watch"

# Records the arguments it was handed, then exits — one redraw, no loop, because
# the script quits as soon as `read` sees EOF on /dev/tty.
RENDER_STUB = """\
#!/usr/bin/env python3
import os, sys
args = dict(zip(sys.argv[1::2], sys.argv[2::2]))
with open(os.environ["RENDER_LOG"], "a") as fh:
    fh.write(f"{args.get('--data-dir')} {args.get('--lines')} {args.get('--width')}\\n")
print("FLEET 0 fronts")
"""


class Watch:
    """A copy of the script with a stub renderer beside it.

    Copied rather than run in place because the marker it reads is
    `../.workspace` *relative to the script* — the whole point of the fallback
    is that it travels with the install, so a test that pointed at the real
    checkout would be testing this machine instead.
    """

    def __init__(self, tmp_path):
        self.scripts = tmp_path / "dotfiles" / "scripts"
        self.scripts.mkdir(parents=True)
        shutil.copy(SCRIPT, self.scripts / "fleet-watch")
        os.chmod(self.scripts / "fleet-watch", 0o755)

        render = self.scripts / "fleet-bar-render.py"
        render.write_text(RENDER_STUB)
        os.chmod(render, 0o755)

        self.log = tmp_path / "render.log"
        self.log.write_text("")
        self.marker = tmp_path / "dotfiles" / ".workspace"

    def run(self, *args, env=None, cols=200, lines=50):
        environ = dict(os.environ)
        environ.pop("WORKSPACE", None)
        environ["RENDER_LOG"] = str(self.log)
        environ["COLUMNS"] = str(cols)
        environ["LINES"] = str(lines)
        environ.update(env or {})
        # Captured stdout is a pipe, not a terminal, so the script takes its
        # one-shot path: draw once, exit. That is the same branch a test needs
        # and a `> board.txt` redirect wants.
        return subprocess.run(
            ["bash", str(self.scripts / "fleet-watch"), *args],
            capture_output=True, text=True, env=environ, stdin=subprocess.DEVNULL,
            timeout=20,
        )

    def renders(self):
        return [ln.split() for ln in self.log.read_text().splitlines()]


@pytest.fixture
def watch(tmp_path):
    return Watch(tmp_path)


def test_the_environment_resolves_the_workspace(watch, tmp_path):
    ws = tmp_path / "ws"
    (ws / ".multiplai" / "data").mkdir(parents=True)

    result = watch.run(env={"WORKSPACE": str(ws)})

    assert result.returncode == 0, result.stderr
    assert watch.renders()[0][0] == str(ws / ".multiplai" / "data")


def test_the_marker_beside_the_script_resolves_the_workspace(watch, tmp_path):
    """The install has no `WORKSPACE`: a terminal is not a claude session."""
    ws = tmp_path / "ws"
    (ws / ".multiplai" / "data").mkdir(parents=True)
    watch.marker.write_text(f"{ws}\n")

    result = watch.run()

    assert result.returncode == 0, result.stderr
    assert watch.renders()[0][0] == str(ws / ".multiplai" / "data")


def test_the_environment_still_wins_over_the_marker(watch, tmp_path):
    watch.marker.write_text(f"{tmp_path / 'stale'}\n")
    ws = tmp_path / "ws"

    watch.run(env={"WORKSPACE": str(ws)})

    assert watch.renders()[0][0] == str(ws / ".multiplai" / "data")


def test_an_unresolvable_workspace_is_an_error_not_a_blank_board(watch):
    """The inversion: this one is read by a person, so it must complain.

    Silence here would look exactly like an idle fleet — the failure that cost
    an afternoon when the status bar did it.
    """
    result = watch.run()

    assert result.returncode != 0
    assert "workspace" in result.stderr.lower()
    assert watch.renders() == []


def test_a_missing_renderer_is_an_error(watch):
    (watch.scripts / "fleet-bar-render.py").unlink()

    result = watch.run(env={"WORKSPACE": "/nowhere"})

    assert result.returncode != 0
    assert "fleet-bar-render.py" in result.stderr


def test_the_renderer_gets_the_whole_window(watch, tmp_path):
    """Not three status lines. One row is reserved so the draw cannot scroll."""
    result = watch.run(env={"WORKSPACE": str(tmp_path / "ws")}, cols=200, lines=50)

    assert result.returncode == 0, result.stderr
    data_dir, rows, cols = watch.renders()[0]
    assert int(rows) > 3
    assert int(cols) > 80


def test_off_a_terminal_it_draws_once_and_leaves(watch, tmp_path):
    """A pipe cannot be waited on, and the board is worth printing anyway."""
    result = watch.run(env={"WORKSPACE": str(tmp_path / "ws")})

    assert result.returncode == 0, result.stderr
    assert len(watch.renders()) == 1
    assert "FLEET" in result.stdout
    assert "\033[2J" not in result.stdout   # no screen-clear into a pipe


@pytest.mark.parametrize("given", ["", "abc", "-1", "5s"])
def test_a_junk_interval_falls_back_rather_than_failing(watch, tmp_path, given):
    """`read -t abc` is a bash error every tick — cheaper to reject the input."""
    result = watch.run(given, env={"WORKSPACE": str(tmp_path / "ws")})

    assert result.returncode == 0, result.stderr
    assert len(watch.renders()) == 1


def test_it_never_resolves_plugin_code(watch):
    """The host boundary `test_fleet_bar.py` asserts for the renderer.

    The plugin's manifest and cache are container-writable, so a host process
    that resolved plugin code would run whatever a container could write. This
    script may call exactly one thing: the stdlib-only renderer beside it.
    """
    body = SCRIPT.read_text()

    for forbidden in ("uv ", "fleet_status", "multiplai-context", "plugins/"):
        assert forbidden not in body, forbidden
