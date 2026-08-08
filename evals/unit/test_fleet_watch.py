"""Pins `dotfiles/scripts/fleet-watch` — the fleet board in a spare terminal.

This is the one host-side fleet script a *person* runs, and that inverts the
rule `fleet-viewed.sh` follows. That one is a tmux hook and silent on every
failure path, because tmux puts a hook's stderr in your terminal; here the
output goes to someone who is looking at it, so an unresolvable workspace has to
say so rather than draw an empty board forever.

Most of this file runs the script off a tty, where it draws once and exits —
which is both a real path (`fleet-watch > board.txt`) and what makes the
before-the-first-redraw assertions cheap:

* it resolves the workspace from the environment first, then the marker;
* it fails **loudly** and non-zero when it cannot;
* it hands the renderer the window's own size, not a fixed line count;
* off a terminal it draws once and leaves, rather than spinning;
* it refreshes the tmux pane map before each draw, through the same
  `fleet-panes.sh` the launcher calls — and **silently**, which is the one
  deliberate exception to the rule above.

That last one is what makes tab labels track reality at the board's resolution
rather than at launch resolution: rename a tab and the next frame follows, and a
container that was already running when the board started acquires a label
instead of being stuck with its container name for the life of the session. The
renderer is not involved and must not be — it is pinned stdlib-only *and*
subprocess-free by `test_fleet_render.py`, so the tmux call cannot live there.

That last one is not hypothetical: waiting on a keypress needs a tty, and
without one the wait returns instantly — a busy loop redrawing forever at full
speed instead of a board.

**The loop is tested too, on a real pty** (`TestOnARealTerminal`). An earlier
version of this file argued it did not need to be — "a redraw timer around
`read -t` has nothing in it to break" — and review then found two things broken
in exactly those four lines: `read` without `-n 1` waited for a newline, so the
documented *any key quits* took Enter; and `fleet-watch 0` passed the
digits-only guard into a `read -t 0` that does not wait, redrawing at full speed
forever. Neither is observable off a tty, because both live in the branch the
other tests skip. Owning a pty is the price of covering them, and `pty.fork`
makes it about fifteen lines.
"""

import fcntl
import os
import pty
import select
import shutil
import signal
import struct
import subprocess
import termios
import time
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

# Stands in for `fleet-panes.sh`. Records the workspace it was handed, and
# prints on both streams — so a `fleet-watch` that stopped redirecting either
# one shows up as a corrupted frame rather than as nothing at all.
PANES_STUB = """\
#!/bin/bash
printf '%s\\n' "$WORKSPACE" >> "$PANES_LOG"
echo "PANES-STDOUT"
echo "PANES-STDERR" >&2
exit 0
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

        render = self.scripts / "fleet-render.py"
        render.write_text(RENDER_STUB)
        os.chmod(render, 0o755)

        self.panes_script = self.scripts / "fleet-panes.sh"
        self.panes_script.write_text(PANES_STUB)
        os.chmod(self.panes_script, 0o755)

        self.log = tmp_path / "render.log"
        self.log.write_text("")
        self.panes_log = tmp_path / "panes.log"
        self.panes_log.write_text("")
        self.marker = tmp_path / "dotfiles" / ".workspace"

    def run(self, *args, env=None, cols=200, lines=50):
        environ = dict(os.environ)
        environ.pop("WORKSPACE", None)
        environ["RENDER_LOG"] = str(self.log)
        environ["PANES_LOG"] = str(self.panes_log)
        environ["COLUMNS"] = str(cols)
        environ["LINES"] = str(lines)
        # `tput` reads `LINES`/`COLUMNS` before asking the terminal, which is
        # what makes the size assertions possible off a tty — but only with a
        # `TERM` it can look up. Pinned rather than inherited so the size tests
        # mean the same thing on a machine (or a CI runner) with no `TERM`,
        # where `tput` fails and the script's own fallback answers instead.
        environ["TERM"] = "xterm"
        environ.update(env or {})
        # Captured stdout is a pipe, not a terminal, so the script takes its
        # one-shot path: draw once, exit. That is the same branch a test needs
        # and a `> board.txt` redirect wants.
        return subprocess.run(
            ["bash", str(self.scripts / "fleet-watch"), *args],
            capture_output=True, text=True, env=environ, stdin=subprocess.DEVNULL,
            timeout=20,
        )

    def _environ(self, env=None, cols=200, lines=50):
        environ = dict(os.environ)
        environ.pop("WORKSPACE", None)
        environ["RENDER_LOG"] = str(self.log)
        environ["PANES_LOG"] = str(self.panes_log)
        environ["COLUMNS"] = str(cols)
        environ["LINES"] = str(lines)
        environ["TERM"] = "xterm"
        environ.update(env or {})
        return environ

    def spawn_on_a_tty(self, *args, env=None, winsize=None):
        """The script with a real controlling terminal, so it takes the loop.

        `pty.fork` rather than a pipe because the script asks two separate
        questions — `[ -t 1 ]` and whether `/dev/tty` is readable — and only a
        *controlling* terminal answers the second. A plain `openpty` handed to
        `subprocess` gives the child a tty on fd 1 but no `/dev/tty`, so it
        would take the one-shot branch and pin nothing.

        Returns `(pid, master_fd)`. The caller owns both; `_drain` and
        `_reap` below are the two things it ever needs to do with them.

        `winsize=(rows, cols)` gives the pty a real window size **and drops
        `LINES`/`COLUMNS` from the environment**, which is the only way to
        test how the script measures a terminal. The size is stamped in the
        child before `exec`, not on the master afterwards, because afterwards
        is a race the script can win.
        """
        environ = self._environ(env=env)
        if winsize is not None:
            environ.pop("LINES", None)
            environ.pop("COLUMNS", None)
        pid, fd = pty.fork()
        if pid == 0:                                    # pragma: no cover
            try:
                if winsize is not None:
                    fcntl.ioctl(1, termios.TIOCSWINSZ,
                                struct.pack("HHHH", winsize[0], winsize[1], 0, 0))
                os.execve("/bin/bash",
                          ["bash", str(self.scripts / "fleet-watch"), *args],
                          environ)
            except BaseException:
                pass
            os._exit(127)
        return pid, fd

    def renders(self):
        return [ln.split() for ln in self.log.read_text().splitlines()]

    def refreshes(self):
        """One entry per pane-map refresh: the workspace it was handed."""
        return self.panes_log.read_text().splitlines()


@pytest.fixture
def watch(tmp_path):
    return Watch(tmp_path)


def test_the_environment_resolves_the_workspace(watch, tmp_path):
    ws = tmp_path / "ws"
    (ws / ".multiplai" / "data").mkdir(parents=True)

    result = watch.run(env={"WORKSPACE": str(ws)})

    assert result.returncode == 0, result.stderr
    assert watch.renders()[0][0] == str(ws / ".multiplai" / "data")


# --- the pane map, refreshed per frame ----------------------------------------

def test_every_draw_refreshes_the_pane_map_first(watch, tmp_path):
    """The change that makes a tab rename visible without a relaunch.

    The map used to be written only by `claude.sh`, at launch — so the board
    re-read a file that could not move between sessions, and a container already
    running when the map was created could never acquire an entry at all. One
    refresh per frame makes it a five-second reading instead.
    """
    ws = tmp_path / "ws"

    result = watch.run(env={"WORKSPACE": str(ws)})

    assert result.returncode == 0, result.stderr
    assert watch.refreshes() == [str(ws)]
    assert len(watch.renders()) == 1


def test_the_refresh_is_handed_the_workspace_the_board_resolved(watch, tmp_path):
    """Both resolve it the same way, so this is belt and braces — but they must
    not be free to disagree: a board drawing one workspace's data while writing
    another's map is worse than either failing."""
    ws = tmp_path / "ws"
    watch.marker.write_text(f"{ws}\n")

    watch.run()

    assert watch.refreshes() == [str(ws)]


def test_the_refresh_never_reaches_the_frame(watch, tmp_path):
    """`draw` runs inside `board=$(draw)`, so its stdout *is* the frame. And a
    diagnostic on stderr would print every five seconds forever — the one place
    this script is deliberately silent, because the map is an enrichment and the
    board is still a board without it."""
    result = watch.run(env={"WORKSPACE": str(tmp_path / "ws")})

    assert "PANES-STDOUT" not in result.stdout
    assert "PANES-STDERR" not in result.stdout
    assert "PANES-STDERR" not in result.stderr


def test_a_missing_pane_script_is_not_an_error(watch, tmp_path):
    """Unlike the renderer, which the board cannot do without. This one is an
    enrichment, and a partial install must still draw."""
    watch.panes_script.unlink()

    result = watch.run(env={"WORKSPACE": str(tmp_path / "ws")})

    assert result.returncode == 0, result.stderr
    assert len(watch.renders()) == 1


def test_a_failing_refresh_does_not_stop_the_board(watch, tmp_path):
    """A stale map is the behaviour that existed before this refresh did."""
    watch.panes_script.write_text("#!/bin/bash\nexit 9\n")

    result = watch.run(env={"WORKSPACE": str(tmp_path / "ws")})

    assert result.returncode == 0, result.stderr
    assert len(watch.renders()) == 1


def test_the_board_does_not_reimplement_the_join():
    """`claude.sh` calls the same script. Two copies of this join is how a
    launcher and a board come to disagree about which pane is which.

    Comment lines are dropped before looking: this file explains at length what
    `fleet-panes.sh` does and why, and prose about a `tmux list-panes` is not a
    `tmux list-panes`.
    """
    code = "\n".join(ln for ln in SCRIPT.read_text().splitlines()
                     if not ln.lstrip().startswith("#"))

    assert "fleet-panes.sh" in code
    assert "list-panes" not in code
    assert "docker" not in code


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
    an afternoon when the status bar did exactly this.
    """
    result = watch.run()

    assert result.returncode != 0
    assert "workspace" in result.stderr.lower()
    assert watch.renders() == []


def test_a_missing_renderer_is_an_error(watch):
    (watch.scripts / "fleet-render.py").unlink()

    result = watch.run(env={"WORKSPACE": "/nowhere"})

    assert result.returncode != 0
    assert "fleet-render.py" in result.stderr


def test_the_renderer_gets_the_whole_window(watch, tmp_path):
    """The whole window. One row is reserved so the draw cannot scroll.

    Asserted as the exact numbers, not as `> 3` and `> 80`: the script falls
    back to a hardcoded 24×120 when it cannot measure, and both of those
    satisfy a loose bound — so the loose version of this test passed whether
    the window was measured or not, which is the one thing it exists to tell
    us. See the test below for the fallback itself.
    """
    result = watch.run(env={"WORKSPACE": str(tmp_path / "ws")}, cols=200, lines=50)

    assert result.returncode == 0, result.stderr
    _data_dir, rows, cols = watch.renders()[0]
    assert (int(rows), int(cols)) == (49, 200)


def test_an_unmeasurable_window_falls_back_rather_than_failing(watch, tmp_path):
    """`tput` needs a `TERM` it can look up, and a bare `cron`/`systemd`
    environment has none. The board is still worth drawing at a guess."""
    result = watch.run(env={"WORKSPACE": str(tmp_path / "ws"), "TERM": ""})

    assert result.returncode == 0, result.stderr
    _data_dir, rows, cols = watch.renders()[0]
    assert (int(rows), int(cols)) == (23, 120)


def test_off_a_terminal_it_draws_once_and_leaves(watch, tmp_path):
    """A pipe cannot be waited on, and the board is worth printing anyway."""
    result = watch.run(env={"WORKSPACE": str(tmp_path / "ws")})

    assert result.returncode == 0, result.stderr
    assert len(watch.renders()) == 1
    assert "FLEET" in result.stdout
    assert "\033[2J" not in result.stdout   # no screen-clear into a pipe


@pytest.mark.parametrize("given", ["", "abc", "-1", "5s", "0"])
def test_a_junk_interval_falls_back_rather_than_failing(watch, tmp_path, given):
    """`read -t abc` is a bash error every tick — cheaper to reject the input.

    `"0"` is the one that is not obviously junk: it passes a digits-only test,
    and `read -t 0` is legal bash. It just does not *wait* — it returns at once,
    non-zero unless a keystroke is already buffered — so the loop would neither
    break nor pause, redrawing at full speed and forking `python3` every
    iteration. Measured before the guard: ~3000 iterations in under a second.
    """
    result = watch.run(given, env={"WORKSPACE": str(tmp_path / "ws")})

    assert result.returncode == 0, result.stderr
    assert len(watch.renders()) == 1


def test_a_failing_renderer_stops_rather_than_painting_the_error(watch, tmp_path):
    """The board must not become its own error message.

    Folding stderr into the frame would put a traceback on screen and then
    clear it a few seconds later, forever — the reader sees a flicker and no
    diagnostic. A renderer that exits non-zero ends the run instead, with its
    own output left on the terminal.

    Exercised down the one-shot branch, which is the only one reachable without
    a pty; both branches call the same `draw`, so what is actually pinned here
    is that it does not merge the two streams and does not swallow the status.
    """
    (watch.scripts / "fleet-render.py").write_text(
        "#!/usr/bin/env python3\n"
        "import sys; print('boom', file=sys.stderr); sys.exit(3)\n"
    )

    result = watch.run(env={"WORKSPACE": str(tmp_path / "ws")})

    assert result.returncode != 0
    assert "boom" in result.stderr
    assert "boom" not in result.stdout


def _drain(fd, seconds, until=None):
    """Read the pty for *seconds*, returning what came out.

    Draining is not optional: a pty buffer that fills blocks the writer, so a
    test that ignored the output would hang the very loop it is timing. Stops
    early once *until* appears, which is how a test waits for the first frame
    without also deciding how fast a frame must arrive.
    """
    out = b""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if until is not None and until in out:
            break
        ready, _, _ = select.select([fd], [], [], 0.05)
        if not ready:
            continue
        try:
            chunk = os.read(fd, 65536)
        except OSError:                 # the child exited; the pty is gone
            break
        if not chunk:
            break
        out += chunk
    return out


def _reap(pid, fd, seconds=5):
    """Wait for the child, killing it if it will not go. Returns its status."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        done, status = os.waitpid(pid, os.WNOHANG)
        if done:
            os.close(fd)
            return status
        select.select([fd], [], [], 0.05)
        try:
            os.read(fd, 65536)
        except OSError:
            pass
    os.kill(pid, signal.SIGKILL)
    os.waitpid(pid, 0)
    os.close(fd)
    return None


class TestOnARealTerminal:
    """The redraw loop, driven through a controlling tty.

    Two bugs lived here behind the claim that the loop had nothing in it to
    break, and neither is reachable from the one-shot branch every other test
    in this file uses.
    """

    def test_it_measures_the_terminal_when_tput_cannot_answer(self, watch, tmp_path):
        """The size comes from the tty, so the board fills the window.

        Every *other* size assertion in this file exports `LINES`/`COLUMNS`,
        which `tput` reads before asking anything — so none of them exercises
        the measurement at all, and all of them passed against the version that
        drew an 80×24 board into a 165×30 terminal. This one unsets both and
        gives the pty a real window.

        `TERM` is deliberately something no terminfo database has, because that
        is the failure mode this environment can actually produce: `tput` gives
        no answer, and only a reader that asks the terminal itself has one. It
        is **not** the route the reported bug took — there `tput` read terminfo
        fine and measured nothing, because `draw` runs inside `board=$(draw)`
        where stdout is a pipe. Linux ncurses falls back to `/dev/tty` in that
        case and returns the right size anyway, so the reported failure cannot
        be reproduced here; it was diagnosed from the numbers on screen, which
        were 80×24 — terminfo's defaults, and not the 120 this script falls
        back to on its own.

        Both routes end at the same line of code and the same fix, so this
        pins the fix. It does not pin the macOS reproduction, and no test in
        this container can.
        """
        pid, fd = watch.spawn_on_a_tty("30",
                                       env={"WORKSPACE": str(tmp_path / "ws"),
                                            "TERM": "no-such-terminal"},
                                       winsize=(30, 165))

        _drain(fd, seconds=5, until=b"FLEET")
        os.write(fd, b"q")
        _reap(pid, fd, seconds=5)

        assert watch.renders(), "the renderer was never called"
        _, lines, width = watch.renders()[0]
        assert (lines, width) == ("29", "165"), \
            "the board was sized from a fallback constant, not from the terminal"

    def test_a_single_keystroke_quits(self, watch, tmp_path):
        """The documented contract is *any key*, and a bare `read` does not
        honour it — it waits for a newline, so the board would sit there until
        you pressed Enter. `-n 1` is what makes the sentence true.

        Written as "one byte, no newline" on purpose: that is precisely the
        input a bare `read` ignores, so this fails against it by timing out.
        """
        pid, fd = watch.spawn_on_a_tty("30", env={"WORKSPACE": str(tmp_path / "ws")})

        _drain(fd, seconds=5, until=b"FLEET")
        os.write(fd, b"q")
        status = _reap(pid, fd, seconds=5)

        assert status is not None, "a keystroke did not quit — it waited for Enter"
        assert os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0

    def test_a_zero_interval_does_not_spin(self, watch, tmp_path):
        """`0` survives a digits-only guard, and `read -t 0` does not wait: it
        returns at once, non-zero unless a keystroke is already buffered. So
        the loop neither breaks nor pauses, and the board becomes a full-speed
        redraw forking `python3` every iteration.

        One second is a wide margin either way — the guard makes this one
        render, and without it the same second produced 478.
        """
        pid, fd = watch.spawn_on_a_tty("0", env={"WORKSPACE": str(tmp_path / "ws")})

        _drain(fd, seconds=1.0)
        _reap(pid, fd, seconds=2)

        assert len(watch.renders()) <= 2, (
            f"{len(watch.renders())} redraws in a second — `read -t 0` did not wait"
        )

    def test_the_cursor_is_restored_when_the_terminal_goes_away(self, watch, tmp_path):
        """`SIGHUP` is the closed window, and it is the case a trap on
        `INT`/`TERM` alone misses — the cursor stays hidden in whatever shell
        the user lands back in, with nothing on screen to explain it. The trap
        is on `EXIT` so every way out goes through one restore.
        """
        pid, fd = watch.spawn_on_a_tty("30", env={"WORKSPACE": str(tmp_path / "ws")})

        _drain(fd, seconds=5, until=b"FLEET")
        os.kill(pid, signal.SIGHUP)
        tail = _drain(fd, seconds=2)
        _reap(pid, fd, seconds=2)

        assert b"\033[?25h" in tail, "the cursor was left hidden"


def test_it_never_resolves_plugin_code(watch):
    """The host boundary `test_fleet_render.py` asserts for the renderer.

    The plugin's manifest and cache are container-writable, so a host process
    that resolved plugin code would run whatever a container could write. This
    script may call exactly one thing: the stdlib-only renderer beside it.
    """
    body = SCRIPT.read_text()

    for forbidden in ("uv ", "fleet_status", "multiplai-context", "plugins/"):
        assert forbidden not in body, forbidden
