"""Pins the tmux window naming in `claude.sh`.

A wall of tabs called "bash" tells you nothing about which session is which.
The launcher renames the tmux window to the container name — the *same* string
the multiplai-context fleet view prints (``workspace claude-personal-05212125``),
so a tab and a fleet row match by eye with no lookup step in between.

The invariants this file breaks if a future edit does:

* the name is the **container** name, not the Claude session id. ``/clear``
  mints a fresh session (one container in the real registry carries nine
  session UUIDs), so a session-named tab would rename itself mid-work and would
  need a host-side watcher polling the registry for the whole run;
* it is renamed **inside** the run loop, because a hub take-back relaunch
  computes a new container name and the tab must follow the container it shows;
* it targets ``$TMUX_PANE``, never the active window — on a take-back relaunch
  the window the user is looking at is frequently not this one;
* a tab the **user has named is never touched** — ``rename-window`` is what
  turns ``automatic-rename`` off, so ``off`` is the signal that a human claimed
  this window, and the launcher neither renames it nor hands it back to
  ``automatic-rename`` on the way out;
* the original name is **restored on every exit path** the launcher did rename,
  and restoring means re-enabling ``automatic-rename`` (it was on, or the
  rename would not have happened), not re-pinning the captured string (which
  would freeze the tab on the shell's name at launch time);
* it never runs on a path that ``exec``s away (``--local``, in-container bare,
  driver) — the EXIT trap could not fire there and the tab would keep a dead
  session's name forever;
* and it is best-effort everywhere: no tmux, no ``$TMUX``, no ``$TMUX_PANE``,
  or a tmux that errors are all silent no-ops that never touch the exit status.

A tab name is cosmetic. It must never cost a session.
"""

import re
import pytest

from test_claude_sh_env import kit  # noqa: F401 — `kit` is a fixture

# Logs every invocation and answers the two queries the launcher makes.
# TMUX_NAME_STUB / TMUX_AUTO_STUB let a test say what the window looked like
# before the launcher touched it; TMUX_FAIL_STUB makes every call fail, which
# is the "tmux is there but refuses" path.
TMUX_STUB = """\
#!/bin/bash
printf '%s\\n' "$*" >> "$TMUX_LOG"
[ -n "${TMUX_FAIL_STUB:-}" ] && exit 1
case "$1" in
    display-message)      printf '%s\\n' "${TMUX_NAME_STUB-bash}" ;;
    show-window-options)
        # tmux scope, which is the whole point: `-v` reads the WINDOW-local
        # value and prints nothing when the option was only ever set globally;
        # `-gv` falls back to the global one. A stub that answered both the
        # same way could not tell the two apart, which is how the launcher
        # shipped reading `-v` against a global `set -g automatic-rename off`
        # and getting "" forever.
        case "$*" in
            *-gv*) printf '%s\\n' "${TMUX_AUTO_STUB-on}" ;;
            *) [ "${TMUX_AUTO_SCOPE-window}" = "window" ] \\
                   && printf '%s\\n' "${TMUX_AUTO_STUB-on}" ;;
        esac
        ;;
esac
exit 0
"""

# The launcher builds this from `date +%d%H%M%S`, so a test can only pin the
# shape — which is the part that matters: it is the container name, and it is
# the string the fleet view prints.
CONTAINER_NAME_RE = re.compile(r"^claude(-[a-z]+)?-\d{8}$")

# As the base stub, plus an exit status the caller can choose — the tab name
# must not be able to change what the launcher reports about the session.
DOCKER_STUB_WITH_STATUS = """\
#!/bin/bash
case "$1" in
    image) exit 0 ;;
    run)
        for a in "$@"; do
            if [ "$a" = "--entrypoint" ]; then exit 0; fi
        done
        printf '%s\\n' "$@" > "$DOCKER_ARGV_OUT"
        env > "$DOCKER_ENV_OUT"
        exit "${MAIN_RUN_STATUS:-0}"
        ;;
esac
exit 0
"""


@pytest.fixture
def tmuxkit(kit, tmp_path):  # noqa: F811
    """`kit` with a tmux stub and a log of what the launcher asked it to do."""
    (kit.stub_dir / "tmux").write_text(TMUX_STUB)
    (kit.stub_dir / "tmux").chmod(0o755)
    (kit.stub_dir / "docker").write_text(DOCKER_STUB_WITH_STATUS)
    (kit.stub_dir / "docker").chmod(0o755)
    kit.tmux_log = tmp_path / "tmux.log"
    kit.tmux_log.write_text("")
    return kit


def _launch(kit, *args, pane="%7", inside=True, **extra):  # noqa: F811
    env = {"TMUX_LOG": str(kit.tmux_log)}
    if inside:
        env["TMUX"] = "/tmp/tmux-501/default,1234,0"
        env["TMUX_PANE"] = pane
    env.update(extra)
    return kit.launch(*(args or ("--shell", "-c", "true")), **env)


def _calls(kit, verb=""):  # noqa: F811
    lines = [ln for ln in kit.tmux_log.read_text().splitlines() if ln]
    return [ln for ln in lines if ln.startswith(verb)] if verb else lines


# --- what the tab gets called -------------------------------------------------

def test_a_launch_renames_the_window_to_the_container_name(tmuxkit):
    _launch(tmuxkit)

    renames = _calls(tmuxkit, "rename-window")
    assert renames, "the window was never renamed"
    assert CONTAINER_NAME_RE.match(renames[0].split()[-1])


def test_the_name_is_the_one_the_fleet_view_prints(tmuxkit):
    """The whole point of choosing the container name over the session id: the
    tab and the `AGENTS.md` row are the same string, so matching them is
    reading, not lookup. `--profile` is part of that string in both places."""
    tmuxkit.write_profile("personal", "GIT_AUTHOR_NAME='P'\n")
    _launch(tmuxkit, "--profile", "personal", "--shell", "-c", "true")

    name = _calls(tmuxkit, "rename-window")[0].split()[-1]
    assert name.startswith("claude-personal-")


def test_the_name_is_not_a_session_id(tmuxkit):
    """`/clear` mints a new session id — one container carries many. A tab
    named after the session would rename itself under the user mid-work."""
    _launch(tmuxkit)

    name = _calls(tmuxkit, "rename-window")[0].split()[-1]
    assert not re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-", name)


def test_the_rename_targets_this_pane_not_the_active_window(tmuxkit):
    """`rename-window` with no target hits whatever window the user is looking
    at when the launch lands, which on a take-back relaunch is often not this
    one."""
    _launch(tmuxkit, pane="%42")

    assert "-t %42" in _calls(tmuxkit, "rename-window")[0]


# --- putting it back ----------------------------------------------------------

def test_an_automatic_name_is_handed_back_to_tmux(tmuxkit):
    """`rename-window` silently turns `automatic-rename` off. Restoring the
    captured string would pin the shell's name from launch time forever; the
    window has to be given back to tmux instead."""
    _launch(tmuxkit, TMUX_AUTO_STUB="on")

    assert any("automatic-rename on" in c for c in _calls(tmuxkit, "set-window-option"))


def test_a_pinned_name_is_never_taken_in_the_first_place(tmuxkit):
    """The user had named this window themselves, and `rename-window` is what
    sets `automatic-rename` to `off` — so `off` *is* the signal that a human
    claimed this tab.

    The launcher used to rename over it and put the string back on exit, which
    was correct but pointless churn: the tab read `claude-personal-06175625`
    for the whole session, which is exactly the name the user had rejected by
    typing their own. Now it is left alone. The board reads the real name back
    out of the pane map, so a pinned name is better input than the container
    name ever was."""
    _launch(tmuxkit, TMUX_AUTO_STUB="off", TMUX_NAME_STUB="notes")

    assert _calls(tmuxkit, "rename-window") == []


def test_a_pinned_name_is_not_handed_back_to_automatic_rename_either(tmuxkit):
    """The other half, and the one a partial fix would miss. `TMUX_RENAMED`
    stays 0 when the rename is skipped, so the restore path must be inert —
    setting `automatic-rename on` here would un-pin a name the launcher never
    touched, and the tab would drift to a shell-derived name after exit."""
    _launch(tmuxkit, TMUX_AUTO_STUB="off", TMUX_NAME_STUB="notes")

    assert _calls(tmuxkit, "set-window-option") == []


def test_a_globally_pinned_name_is_left_alone_too(tmuxkit):
    """The regression. `set -g automatic-rename off` in `~/.tmux.conf` is the
    ordinary way to claim your tab names, and it claims *every* tab — but the
    launcher read the option with `show-window-options -v`, which returns the
    window-local value and prints **nothing** when only the global was ever
    set. So the guard compared "" against "off", concluded nobody had claimed
    anything, and renamed every tab it was launched from.

    Reproduced on tmux 3.4: with a global `off`, `-v` returns empty and `-gv`
    returns `off`.
    """
    _launch(tmuxkit, TMUX_AUTO_STUB="off", TMUX_AUTO_SCOPE="global",
            TMUX_NAME_STUB="notes")

    assert _calls(tmuxkit, "rename-window") == []
    assert _calls(tmuxkit, "set-window-option") == []


def test_the_option_is_read_with_global_fallback(tmuxkit):
    """Stated as the mechanism, not the symptom, so a revert to `-v` fails here
    with a readable reason rather than only through its two consequences."""
    _launch(tmuxkit)

    reads = _calls(tmuxkit, "show-window-options")
    assert reads, "the option was never read"
    assert all(" -gv " in f" {c} " for c in reads), reads


def test_the_original_is_read_before_the_first_rename(tmuxkit):
    """Capture has to precede the rename that destroys what it captures."""
    _launch(tmuxkit)

    calls = _calls(tmuxkit)
    assert calls.index(next(c for c in calls if c.startswith("display-message"))) < \
        calls.index(next(c for c in calls if c.startswith("rename-window")))


# --- when it must not act -----------------------------------------------------

def test_outside_tmux_nothing_is_called(tmuxkit):
    launch = _launch(tmuxkit, inside=False)

    assert _calls(tmuxkit) == []
    assert launch.status == 0


def test_a_tmux_without_a_pane_is_not_guessed_at(tmuxkit):
    """`$TMUX` without `$TMUX_PANE` means we cannot say which window is ours.
    Renaming the active one would hit a bystander tab."""
    launch = tmuxkit.launch("--shell", "-c", "true",
                            TMUX="/tmp/tmux-501/default,1234,0",
                            TMUX_LOG=str(tmuxkit.tmux_log))

    assert _calls(tmuxkit) == []
    assert launch.status == 0


def test_local_mode_never_renames(tmuxkit):
    """`--local` `exec`s claude, replacing this process — the EXIT trap could
    never fire, so the tab would keep a dead session's name forever."""
    launch = _launch(tmuxkit, "--local")

    assert _calls(tmuxkit) == []
    assert launch.status == 0


# --- when it cannot act -------------------------------------------------------

def test_no_tmux_binary_is_a_silent_no_op(kit):  # noqa: F811
    """`$TMUX` is inherited by anything the pane spawns, so it can be set with
    no tmux on PATH — a container shell being the everyday case."""
    launch = kit.launch("--shell", "-c", "true",
                        TMUX="/tmp/tmux-501/default,1234,0", TMUX_PANE="%1")

    assert launch.status == 0


def test_a_failing_tmux_never_reaches_the_user(tmuxkit):
    """A tmux that answers every call with an error must not print, must not
    trip `set -e`, and must not leave a restore half-done."""
    launch = _launch(tmuxkit, TMUX_FAIL_STUB="1")

    assert launch.status == 0
    assert "tmux" not in launch.output.lower()


def test_the_tab_name_never_changes_the_exit_status(tmuxkit):
    """It is cosmetic. A rename must cost a tab name, never a session's exit
    code."""
    launch = _launch(tmuxkit, "--shell", "-c", "true", MAIN_RUN_STATUS="42")

    assert launch.status == 42
