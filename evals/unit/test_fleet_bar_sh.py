"""Pins `dotfiles/scripts/fleet-bar` — the bash entry point tmux calls.

tmux invokes this once per status line per tick, in every attached client:
four lines at `status-interval 5` is a handful of processes every five seconds,
for as long as the terminal is open. Everything here follows from that.

Three invariants, each a real way the board could become worse than absent:

* **It never writes a diagnostic.** Its stdout *is* the status bar, so an error
  message would replace the board with itself, and tmux would repaint it every
  five seconds. Every failure path prints one empty line and exits 0.
* **Exactly one caller regenerates.** Five simultaneous invocations must not
  become five renders. The lock is an atomic `mkdir` — the kernel picks the
  winner, and the losers print the cache that is already there, one tick stale,
  which at five seconds is invisible.
* **A crashed render cannot freeze the board.** A lock left behind would pin
  the bar to whatever it last showed, forever, with no error anywhere.

The tmux wiring itself is documentation (`docs/TMUX-FLEET-BOARD.md`), not code,
and is deliberately not tested here — there is nothing in it to break.
"""

import json
import os
import subprocess
import time
from pathlib import Path

import pytest

KIT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = KIT_ROOT / "dotfiles" / "scripts" / "fleet-bar"

# Answers the two queries the script makes when it decides to regenerate.
TMUX_STUB = """\
#!/bin/bash
case "$1" in
    show-options)     printf '%s\\n' "${TMUX_STATUS_STUB-4}" ;;
    display-message)  printf '%s\\n' "${TMUX_WIDTH_STUB-100}" ;;
esac
exit 0
"""

# Records every invocation, so a test can count renders across concurrent
# callers. Writes a cache so the caller has something to print.
RENDER_STUB = """\
#!/usr/bin/env python3
import os, sys, time
args = dict(zip(sys.argv[1::2], sys.argv[2::2]))
with open(os.environ["RENDER_LOG"], "a") as fh:
    fh.write(f"{args.get('--lines')} {args.get('--width')}\\n")
time.sleep(float(os.environ.get("RENDER_DELAY", "0")))
out = args.get("--out")
if out:
    with open(out, "w") as fh:
        fh.write("line one\\nline two\\nline three\\n")
"""


class Bar:
    def __init__(self, tmp_path):
        self.workspace = tmp_path / "ws"
        self.data = self.workspace / ".multiplai" / "data"
        (self.data / "tmux").mkdir(parents=True)
        self.log = tmp_path / "render.log"
        self.log.write_text("")

        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        (self.bin / "tmux").write_text(TMUX_STUB)
        (self.bin / "tmux").chmod(0o755)

        # The script resolves the renderer next to itself, so the stub has to
        # live in a copy of the script's directory rather than on PATH.
        self.scripts = tmp_path / "scripts"
        self.scripts.mkdir()
        self.script = self.scripts / "fleet-bar"
        self.script.write_text(SCRIPT.read_text(encoding="utf-8"))
        self.script.chmod(0o755)
        (self.scripts / "fleet-bar-render.py").write_text(RENDER_STUB)
        (self.scripts / "fleet-bar-render.py").chmod(0o755)

        self.tmp_path = tmp_path

    @property
    def cache(self):
        return self.data / "tmux" / "bar.txt"

    def write_cache(self, *lines, age=0.0):
        self.cache.write_text("\n".join(lines) + "\n", encoding="utf-8")
        if age:
            old = time.time() - age
            os.utime(self.cache, (old, old))

    def run(self, line="1", *, ws=True, popen=False, **extra):
        env = {
            "PATH": f"{self.bin}:/usr/bin:/bin:/usr/local/bin",
            "HOME": str(self.tmp_path / "home"),
            "RENDER_LOG": str(self.log),
        }
        if ws:
            env["WORKSPACE"] = str(self.workspace)
        env.update(extra)
        cmd = [str(self.script), line]
        if popen:
            return subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True)
        return subprocess.run(cmd, env=env, capture_output=True, text=True,
                              timeout=60)

    @property
    def renders(self):
        return [ln for ln in self.log.read_text().splitlines() if ln]


@pytest.fixture
def barsh(tmp_path):
    return Bar(tmp_path)


def _assert_one_clean_line(proc):
    assert proc.returncode == 0, f"exited {proc.returncode}"
    assert proc.stderr == "", f"wrote to stderr: {proc.stderr!r}"
    assert proc.stdout.count("\n") == 1, f"not one line: {proc.stdout!r}"


# --- printing -----------------------------------------------------------------

def test_it_prints_the_requested_line(barsh):
    barsh.write_cache("first", "second", "third")

    assert barsh.run("2").stdout == "second\n"


def test_each_line_number_gets_its_own_row(barsh):
    barsh.write_cache("a", "b", "c")

    assert [barsh.run(str(n)).stdout for n in (1, 2, 3)] == ["a\n", "b\n", "c\n"]


def test_a_line_past_the_end_is_blank_not_an_error(barsh):
    barsh.write_cache("a")

    _assert_one_clean_line(barsh.run("9"))
    assert barsh.run("9").stdout == "\n"


# --- silence on every failure path --------------------------------------------

def test_a_missing_cache_prints_an_empty_line(barsh):
    """The renderer stub is present, so this is the genuinely-cacheless first
    tick: regenerate, then print. Either way, one line, no noise."""
    proc = barsh.run("1")

    _assert_one_clean_line(proc)


def test_no_workspace_prints_an_empty_line(barsh):
    proc = barsh.run("1", ws=False, CLAUDE_CONFIG_DIR=str(barsh.tmp_path / "nope"))

    _assert_one_clean_line(proc)
    assert proc.stdout == "\n"


def test_the_marker_beside_the_script_resolves_the_workspace(barsh):
    """The host has no `$WORKSPACE` and no `$CLAUDE_CONFIG_DIR`.

    tmux runs `#()` through the *server's* environment, which predates any
    launcher, so neither variable is set — and `$CLAUDE_CONFIG_DIR` is set by
    the launcher for the *container*, so on the host it never fires at all.
    `setup.sh` writes `dotfiles/.workspace`, one level up from this script;
    resolving it relative to `$0` is the only form that works with an empty
    environment. Without it the documented tmux wiring renders a permanently
    empty board, which is indistinguishable from "no agents".
    """
    (barsh.scripts.parent / ".workspace").write_text(
        str(barsh.workspace) + "\n", encoding="utf-8")
    barsh.write_cache("board line one")

    proc = barsh.run("1", ws=False)

    _assert_one_clean_line(proc)
    assert proc.stdout == "board line one\n"


def test_the_environment_still_wins_over_the_marker(barsh):
    """A launcher-set `$WORKSPACE` must beat the file, or a session pointed at
    a second workspace would silently read the first one's board."""
    (barsh.scripts.parent / ".workspace").write_text(
        str(barsh.tmp_path / "other-ws") + "\n", encoding="utf-8")
    barsh.write_cache("from the env workspace")

    assert barsh.run("1").stdout == "from the env workspace\n"


def test_a_missing_renderer_prints_an_empty_line(barsh):
    (barsh.scripts / "fleet-bar-render.py").unlink()

    proc = barsh.run("1")

    _assert_one_clean_line(proc)
    assert proc.stdout == "\n"


def test_a_renderer_that_fails_prints_an_empty_line(barsh):
    (barsh.scripts / "fleet-bar-render.py").write_text(
        "#!/bin/bash\necho boom >&2\nexit 3\n")
    (barsh.scripts / "fleet-bar-render.py").chmod(0o755)

    proc = barsh.run("1")

    _assert_one_clean_line(proc)
    assert proc.stdout == "\n"


@pytest.mark.parametrize("line", ["", "x", "-1", "1;id", "../etc"])
def test_a_bad_line_number_prints_an_empty_line(barsh, line):
    barsh.write_cache("a", "b")

    proc = barsh.run(line)

    _assert_one_clean_line(proc)
    assert proc.stdout == "\n"
    assert barsh.renders == [], "a bad argument must not trigger a render"


def test_no_tmux_on_path_still_renders(barsh):
    """tmux is only consulted for the line count and width, both of which have
    defaults. Losing it must not lose the board."""
    (barsh.bin / "tmux").unlink()

    proc = barsh.run("1")

    _assert_one_clean_line(proc)
    assert barsh.renders == ["3 120"], "the documented fallbacks"


# --- regeneration -------------------------------------------------------------

def test_a_fresh_cache_is_not_regenerated(barsh):
    barsh.write_cache("cached")

    barsh.run("1")

    assert barsh.renders == []


def test_a_stale_cache_is_regenerated(barsh):
    barsh.write_cache("cached", age=600)

    barsh.run("1")

    assert len(barsh.renders) == 1


def test_the_line_count_comes_from_tmux_minus_your_own_status_line(barsh):
    """Line 0 stays the user's. `status 4` means the board owns 1, 2 and 3."""
    barsh.run("1", TMUX_STATUS_STUB="4")

    assert barsh.renders == ["3 100"]


def test_an_on_off_status_falls_back_rather_than_computing_nonsense(barsh):
    barsh.run("1", TMUX_STATUS_STUB="on")

    assert barsh.renders == ["3 100"]


def test_concurrent_callers_regenerate_at_most_once(barsh):
    """Five lines fire per tick. Five renders per tick is the bug this lock
    exists to prevent — and a loser printing one-tick-old content is invisible
    at a five-second interval."""
    barsh.write_cache("cached", age=600)

    procs = [barsh.run(str(n), popen=True, RENDER_DELAY="0.5") for n in range(1, 6)]
    for proc in procs:
        proc.wait(timeout=60)

    assert len(barsh.renders) == 1, barsh.renders
    for proc in procs:
        assert proc.returncode == 0
        assert proc.stderr.read() == ""


def test_a_stale_lock_does_not_freeze_the_board(barsh):
    """A lock left by a killed renderer would pin the bar to whatever it last
    showed, forever, with nothing reporting it anywhere."""
    barsh.write_cache("cached", age=600)
    lock = barsh.data / "tmux" / "bar.lock"
    lock.mkdir()
    old = time.time() - 600
    os.utime(lock, (old, old))

    barsh.run("1")

    assert len(barsh.renders) == 1


def test_a_recent_lock_is_respected(barsh):
    barsh.write_cache("cached", age=600)
    (barsh.data / "tmux" / "bar.lock").mkdir()

    proc = barsh.run("1")

    assert barsh.renders == []
    _assert_one_clean_line(proc)
    assert proc.stdout == "cached\n"


def test_the_lock_is_released_after_a_render(barsh):
    barsh.write_cache("cached", age=600)

    barsh.run("1")

    assert not (barsh.data / "tmux" / "bar.lock").exists()


# --- end to end ---------------------------------------------------------------

def test_the_real_renderer_produces_a_printable_bar(tmp_path):
    """The shipped pair, wired together: a `fleet.json` in, a status line out.
    Everything above stubs the renderer, so this is the one check that the two
    halves agree on their interface."""
    bar = Bar(tmp_path)
    (bar.scripts / "fleet-bar-render.py").write_text(
        (KIT_ROOT / "dotfiles" / "scripts" / "fleet-bar-render.py").read_text(
            encoding="utf-8"))
    (bar.scripts / "fleet-bar-render.py").chmod(0o755)
    (bar.data / "fleet.json").write_text(json.dumps({
        "version": 1,
        "generated_at": "2026-08-07T12:00:00+00:00",
        "counts": {"fronts": 2, "needs_you": 1, "collisions": 0},
        "agents": [{"session_id": "s1", "project": "kit", "hostname": "c-01",
                    "tmux_window": "pi-eval", "group": "Needs you",
                    "seen": False, "age_seconds": 60,
                    "next_action": "approve the edit"}],
        "collisions": [], "prs": None, "collected_at": {},
    }))

    first = bar.run("1")
    second = bar.run("2")

    assert first.stderr == "" and second.stderr == ""
    assert first.stdout.startswith("FLEET")
    assert "pi-eval" in second.stdout
