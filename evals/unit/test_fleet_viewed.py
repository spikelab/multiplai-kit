"""Pins `dotfiles/scripts/fleet-viewed.sh` — the "you looked at this tab" marker.

The fleet view's seen/unseen axis rests on one fact the container cannot
observe: when Spike last looked at a pane. tmux runs on the Mac, the session
runs in a container with no tmux socket, so this script is the only thing that
can write it. It is bound to `after-select-pane`, `after-select-window`,
`client-focus-in` and `after-rename-window` (see `docs/TMUX-FLEET-BOARD.md`),
which means it runs on *every* pane switch — the tests below exist to keep it
cheap and, above all, quiet.

Three invariants, each of which is a real way this feature could become worse
than not having it:

* **It never prints.** tmux paints a hook's stderr into the terminal, so a
  script that complains about a missing directory would put a line of noise on
  screen every time Spike changes pane. Every failure path exits 0 in silence —
  no workspace, no data dir, no tmux, a pane id that is not a pane id.
* **It writes exactly the three-line marker the reader parses**, in order:
  timestamp, window name, tmux server. The server line is load-bearing — tmux
  recycles pane ids per server, so a reader that trusted a pane id without it
  would credit one tab's attention to an unrelated session.
* **It prunes.** Pane ids climb for the life of a tmux server; without a bound
  the directory grows forever. Seven days is the plan's number and is pinned
  here, because the whole question a marker answers is about the last few
  minutes.

It is also *not* allowed to interpret anything. There is deliberately no
notion here of which session owns a pane — that map is the launcher's, and the
join happens at render time in the `multiplai-context` plugin.
"""

import os
import subprocess
import time

import pytest

from _kitpaths import KIT_ROOT
SCRIPT = KIT_ROOT / "dotfiles" / "scripts" / "fleet-viewed.sh"
WS_LIB = KIT_ROOT / "dotfiles" / "scripts" / "lib" / "resolve-workspace.sh"

# Answers the one query the script makes: window name and socket path, in a
# single `display-message`. TMUX_FAIL_STUB is "tmux is on PATH but refuses",
# which is what a hook run against a dead server looks like.
#
# It resolves the window name **against `-t`**, the way real tmux does, and
# falls back to a distinctive `current-pane` when no target was given. A stub
# that answered the same regardless of target could not tell a targeted read
# from an untargeted one — which is the whole bug this pins.
TMUX_STUB = """\
#!/bin/bash
[ -n "${TMUX_FAIL_STUB:-}" ] && exit 1
target=""
prev=""
for a in "$@"; do
    [ "$prev" = "-t" ] && target="$a"
    prev="$a"
done
if [ -n "$target" ]; then
    printf '%s\\n' "${TMUX_WINDOW_STUB-pi-eval}${TMUX_NAME_PER_PANE:+-$target}"
else
    printf '%s\\n' "current-pane"
fi
printf '%s\\n' "${TMUX_SERVER_STUB-/tmp/tmux-501/default}"
exit 0
"""


class Run:
    """One invocation of the script, plus the workspace it wrote into."""

    def __init__(self, proc, workspace):
        self.proc = proc
        self.workspace = workspace

    @property
    def viewed_dir(self):
        return self.workspace / ".multiplai" / "data" / "tmux" / "viewed"

    def marker(self, name):
        return (self.viewed_dir / name).read_text().splitlines()


@pytest.fixture
def run(tmp_path):
    """Invoke the script the way a tmux hook does: bare, with a pane id."""
    workspace = tmp_path / "ws"
    workspace.mkdir()

    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    (stub_dir / "tmux").write_text(TMUX_STUB)
    (stub_dir / "tmux").chmod(0o755)

    def _run(pane="%12", *, ws=workspace, tmux=True, **extra):
        env = {
            "PATH": f"{stub_dir}:/usr/bin:/bin" if tmux else "/usr/bin:/bin",
            "HOME": str(tmp_path / "home"),
        }
        if ws is not None:
            env["WORKSPACE"] = str(ws)
        env.update(extra)
        proc = subprocess.run(
            [str(SCRIPT), pane],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return Run(proc, workspace)

    return _run


def _assert_silent(r):
    assert r.proc.returncode == 0, f"exited {r.proc.returncode}"
    assert r.proc.stdout == "", f"wrote to stdout: {r.proc.stdout!r}"
    assert r.proc.stderr == "", f"wrote to stderr: {r.proc.stderr!r}"


# --- the marker ---------------------------------------------------------------

def test_it_writes_the_three_line_marker(run):
    r = run("%12")
    _assert_silent(r)

    lines = r.marker("12")
    assert len(lines) == 3, f"expected 3 lines, got {lines}"
    assert lines[1] == "pi-eval"
    assert lines[2] == "/tmp/tmux-501/default"


def test_the_first_line_is_a_utc_timestamp(run):
    """The reader compares it against an agent's `last_event`, which is UTC and
    `Z`-suffixed. A local-time or offset-bearing stamp would compare wrong by
    hours in one direction — i.e. it would silently mark busy agents as seen."""
    r = run()
    stamp = r.marker("12")[0]
    parsed = time.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ")
    assert abs(time.time() - time.mktime(parsed) + time.timezone) < 300


def test_the_filename_is_the_pane_id_without_the_percent(run):
    r = run("%12")
    assert (r.viewed_dir / "12").exists()
    assert not (r.viewed_dir / "%12").exists()


def test_the_server_is_recorded_so_a_reader_can_refuse_a_recycled_pane_id(run):
    """Pane ids are per-server. Without line 3 a reader has no way to tell
    `%12` on this server from `%12` on another, and would attribute one tab's
    attention to a different session."""
    r = run("%3", TMUX_SERVER_STUB="/private/tmp/tmux-501/other")
    assert r.marker("3")[2] == "/private/tmp/tmux-501/other"


def test_the_window_name_is_recorded_fresh_each_time(run):
    """`after-rename-window` is one of the bound hooks precisely so a tab
    renamed mid-session updates the label the fleet view shows for it."""
    r = run("%4", TMUX_WINDOW_STUB="before")
    assert r.marker("4")[1] == "before"

    r = run("%4", TMUX_WINDOW_STUB="after")
    assert r.marker("4")[1] == "after"


def test_the_window_name_is_read_from_the_pane_the_hook_names(run):
    """Not from whatever the client's current pane happens to be. These hooks
    fire at the moments that is in flux — `after-select-window` hands the new
    pane in `#{hook_pane}` while the client may still consider the old one
    current — so an untargeted `display-message` writes the window you just
    left into the marker for the window you just arrived at. The marker's
    entire job is to say what is on screen now."""
    r = run("%7", TMUX_NAME_PER_PANE="1")

    assert r.marker("7")[1] == "pi-eval-%7"


def test_a_second_view_overwrites_rather_than_appends(run):
    """One file per pane, three lines. An append would grow without bound and
    hand the reader a stale first line."""
    run("%5")
    r = run("%5")
    assert len(r.marker("5")) == 3


# --- where it writes ----------------------------------------------------------

def test_the_workspace_falls_back_to_the_dotfile(run, tmp_path):
    """A tmux hook inherits the *tmux server's* environment, which was started
    long before any launcher exported `WORKSPACE`.

    This `$CLAUDE_CONFIG_DIR` form is kept for the container, where the
    launcher does export it. It is **not** the path that fires on the host —
    see the test below, which is.
    """
    config = tmp_path / "cfg"
    config.mkdir()
    ws = tmp_path / "ws"
    (config / ".workspace").write_text(f"{ws}\n")

    r = run("%9", ws=None, CLAUDE_CONFIG_DIR=str(config))
    _assert_silent(r)
    assert (r.viewed_dir / "9").exists()


def test_the_marker_beside_the_script_resolves_the_workspace(tmp_path):
    """The host case, and the one that was broken.

    This script runs from a tmux hook on the Mac, where `$WORKSPACE` is unset
    and `$CLAUDE_CONFIG_DIR` is *never* set — the launcher exports that one
    into the container. `setup.sh` writes `dotfiles/.workspace` one level above
    this script, so the `$0`-relative read is the only resolution available
    with an empty environment. Without it every hook exited silently and no
    marker was ever written, which reads identically to "you have not looked
    at anything".
    """
    dotfiles = tmp_path / "dotfiles"
    scripts = dotfiles / "scripts"
    (scripts / "lib").mkdir(parents=True)
    script = scripts / "fleet-viewed.sh"
    script.write_text(SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    script.chmod(0o755)
    # The workspace-resolution lib travels beside the script, like the
    # `.workspace` marker it reads.
    lib = scripts / "lib" / "resolve-workspace.sh"
    lib.write_text(WS_LIB.read_text(encoding="utf-8"), encoding="utf-8")

    ws = tmp_path / "ws"
    ws.mkdir()
    (dotfiles / ".workspace").write_text(f"{ws}\n", encoding="utf-8")

    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    (stub_dir / "tmux").write_text(TMUX_STUB)
    (stub_dir / "tmux").chmod(0o755)

    proc = subprocess.run(
        [str(script), "%7"],
        env={"PATH": f"{stub_dir}:/usr/bin:/bin", "HOME": str(tmp_path / "home")},
        capture_output=True, text=True, timeout=30,
    )

    assert proc.returncode == 0
    assert proc.stdout == "" and proc.stderr == ""
    assert (ws / ".multiplai" / "data" / "tmux" / "viewed" / "7").exists()


def test_it_creates_the_marker_directory(run):
    """A fresh workspace has no `.multiplai/data/tmux/viewed/`, and the script
    fires long before anything else would create it."""
    r = run()
    assert r.viewed_dir.is_dir()


# --- silence on every failure path --------------------------------------------

def test_no_workspace_at_all_is_silent(run):
    r = run("%12", ws=None)
    _assert_silent(r)


def test_a_non_numeric_pane_id_writes_nothing(run):
    """Anything that is not `%` plus digits was not issued by tmux. Exiting
    keeps a hook misconfiguration from writing arbitrary filenames."""
    for pane in ("bogus", "%1a", "%", "", "../escape", "%-1"):
        r = run(pane)
        _assert_silent(r)
        assert not r.viewed_dir.exists() or not any(r.viewed_dir.iterdir()), (
            f"pane id {pane!r} produced a marker"
        )


def test_no_tmux_on_path_is_silent(run):
    r = run("%12", tmux=False)
    _assert_silent(r)
    assert not (r.viewed_dir / "12").exists()


def test_a_tmux_that_errors_is_silent(run):
    """A hook can fire against a server that is going away."""
    r = run("%12", TMUX_FAIL_STUB="1")
    _assert_silent(r)
    assert not (r.viewed_dir / "12").exists()


def test_an_unwritable_data_dir_is_silent(run, tmp_path):
    if os.geteuid() == 0:
        pytest.skip("root ignores the mode bits this test relies on")

    ws = tmp_path / "ro"
    (ws / ".multiplai" / "data" / "tmux").mkdir(parents=True)
    (ws / ".multiplai" / "data" / "tmux").chmod(0o500)
    try:
        r = run("%12", ws=ws)
        _assert_silent(r)
    finally:
        (ws / ".multiplai" / "data" / "tmux").chmod(0o700)


# --- pruning ------------------------------------------------------------------

def test_a_marker_older_than_seven_days_is_removed(run):
    r = run("%1")
    stale = r.viewed_dir / "99"
    stale.write_text("old\n")
    old = time.time() - 8 * 86400
    os.utime(stale, (old, old))

    r = run("%1")
    assert not stale.exists(), "a marker older than 7 days survived the prune"


def test_a_recent_marker_survives_the_prune(run):
    r = run("%1")
    fresh = r.viewed_dir / "98"
    fresh.write_text("recent\n")
    recent = time.time() - 2 * 86400
    os.utime(fresh, (recent, recent))

    r = run("%1")
    assert fresh.exists(), "the prune ate a marker that is still meaningful"
