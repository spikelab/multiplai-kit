"""Pins the launcher's half of the tmux pane map.

The map itself — what an entry means, what bounds the file, how two tmux servers
share it — lives in `dotfiles/scripts/fleet-panes.sh` and is pinned by
`test_fleet_panes.py`. It was extracted from `claude.sh` because `fleet-watch`
needs the same reading before every redraw, and two copies of a join is how the
two drift.

What is left here is the part only the launcher can do, and it is a short list:

* **stamp the pane.** `tmux set-option -p @cc "$CONTAINER_NAME"` is the fact
  everything downstream reads, and this is the only process that ever holds
  `$TMUX_PANE` and the container name at the same moment. The stamp is what
  makes the map self-healing: it is on the pane rather than on its name, so a
  renamed tab keeps its identity, and a reader can enumerate the whole fleet
  without having been present at any of the launches;
* **call the map at the roster's two points.** Pre-run, so the SessionStart
  seconds later reads a map with no daemon and no timer, and post-exit, so a
  closed tab stops labelling a session that has ended;
* **pass the container name pre-run and nothing post-exit.** At the pre-run
  call the container is not in `docker ps` — it does not exist yet — so naming
  it is the only thing that records it. Post-exit it is gone from `docker ps`
  again, and passing nothing is what lets the same rule retire it;
* **never let any of that cost a session.** No tmux, no `$TMUX_PANE`, a missing
  script, a failing tmux: all silent, none of them touching the exit status.

The launcher also **mints the container name**, which changed shape with this
work: `cc-p-08015414`, not `claude-personal-08015414`. Nothing anywhere parses
that string — every consumer in the kit and in the multiplai-context plugin
compares it whole — so it is free to be chosen for the places a person reads it,
and 11 characters of "claude-personal" were the reason the fleet board's label
column had to be 24 wide. The profile survives as its initial because the board
has no other field carrying which identity a session is running as. Pinned in
`test_claude_sh_tmux.py`, which owns the naming.
"""

import json
import shutil
import subprocess

import pytest

from test_claude_sh_env import kit  # noqa: F401 — `kit` is a fixture

from conftest import KIT_ROOT
PANES_SCRIPT = KIT_ROOT / "dotfiles" / "scripts" / "fleet-panes.sh"

# Two jobs. It records every call so the stamp can be asserted on, and it
# answers `list-panes -a` with a canned fleet so the real `fleet-panes.sh` —
# which the launcher shells out to — has something to read. The record format
# matches the one the script's own `-F` asks for:
#
#     pane | @cc | automatic-rename | window | session
#
# `%12` is this launch's pane, and it is deliberately staged *unstamped*: a stub
# cannot make `set-option -p` real, so what the launcher's own entry exercises
# here is the `$TMUX_PANE` fallback. That the stamp itself round-trips through
# `#{@cc}` is pinned against a real tmux in `test_fleet_panes.py`.
PANE_TMUX_STUB = """\
#!/bin/bash
printf '%s\\n' "$*" >> "$TMUX_LOG"
[ -n "${TMUX_FAIL_STUB:-}" ] && exit 1
case "$1" in
    display-message)
        case "$*" in
            *socket_path*)  printf '%s\\n' "${TMUX_SERVER_STUB-/private/tmp/tmux-501/default}" ;;
            *pane_id*)      printf '%s\\n' "${TMUX_PANEID_STUB-%12}" ;;
            *window_name*)  printf '%s\\n' "${TMUX_NAME_STUB-pi-eval}" ;;
            *session_name*) printf '%s\\n' "${TMUX_SESSION_STUB-work}" ;;
        esac
        ;;
    list-panes)
        printf '%s\\n' "${TMUX_PANES_STUB-%12||off||work}"
        ;;
    show-options|show-window-options)
        # tmux option scope — see the twin of this stub in
        # `test_claude_sh_tmux.py` for the full reasoning. In short: `-v` is
        # window-local (empty when only the global was set), `-gv` is the
        # global set (blind to a local override), and `-Av` is the resolved
        # value the launcher actually wants. Verified against tmux 3.4.
        _global=on
        _local=
        [ "${TMUX_AUTO_SCOPE-window}" = "global" ] && _global="${TMUX_AUTO_STUB-on}"
        [ "${TMUX_AUTO_SCOPE-window}" = "window" ] && _local="${TMUX_AUTO_STUB-on}"
        [ -n "${TMUX_AUTO_LOCAL-}" ] && _local="$TMUX_AUTO_LOCAL"
        case "$*" in
            *-Av*) printf '%s\\n' "${_local:-$_global}" ;;
            *-gv*) printf '%s\\n' "$_global" ;;
            *)     [ -n "$_local" ] && printf '%s\\n' "$_local" ;;
        esac
        ;;
esac
exit 0
"""

# `docker ps` is counter-indexed so the pre-run and post-exit observations can
# be told apart — the point of the second write is that it sees a world the
# first one did not.
PANE_DOCKER_STUB = """\
#!/bin/bash
case "$1" in
    image) exit 0 ;;
    ps)
        n=0
        [ -f "$PS_COUNT" ] && n=$(cat "$PS_COUNT")
        echo $((n + 1)) > "$PS_COUNT"
        val=""
        i=$n
        while [ "$i" -ge 0 ]; do
            eval "isset=\\${PS_NAMES_$i+yes}"
            if [ -n "$isset" ]; then eval "val=\\$PS_NAMES_$i"; break; fi
            i=$((i - 1))
        done
        printf '%s\\n' "$val"
        exit "${PS_STATUS:-0}"
        ;;
    run)
        for a in "$@"; do
            if [ "$a" = "--entrypoint" ]; then exit 0; fi
        done
        # The session is "running" at this instant, so this is the only moment
        # the pre-run map can be read before the post-exit write replaces it.
        [ -f "$PANES_SRC" ] && cp "$PANES_SRC" "$PANES_SNAPSHOT"
        printf '%s\\n' "$@" > "$DOCKER_ARGV_OUT"
        env > "$DOCKER_ENV_OUT"
        exit "${MAIN_RUN_STATUS:-0}"
        ;;
esac
exit 0
"""


@pytest.fixture
def panekit(kit, tmp_path):  # noqa: F811
    """`kit` inside tmux, with a ps-aware docker and a data dir to write into.

    The real `fleet-panes.sh` is copied into the scratch kit's `dotfiles/scripts`
    rather than stubbed, so these cases run the launcher's actual call path —
    `$DOTFILES_DIR/scripts/fleet-panes.sh` — end to end. A launcher that
    resolved the wrong path, or stopped calling it, fails here rather than in
    production.
    """
    (kit.stub_dir / "tmux").write_text(PANE_TMUX_STUB)
    (kit.stub_dir / "tmux").chmod(0o755)
    (kit.stub_dir / "docker").write_text(PANE_DOCKER_STUB)
    (kit.stub_dir / "docker").chmod(0o755)
    scripts = kit.root / "dotfiles" / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    shutil.copy(PANES_SCRIPT, scripts / "fleet-panes.sh")
    kit.tmux_log = tmp_path / "tmux.log"
    kit.tmux_log.write_text("")
    kit.data_dir = kit.workspace / ".multiplai" / "data"
    kit.data_dir.mkdir(parents=True)
    kit.ps_count = tmp_path / "ps_count.txt"
    kit.panes = kit.data_dir / "tmux" / "panes.json"
    kit.snapshot = tmp_path / "panes-at-run.json"
    return kit


def _launch(kit, *names_per_call, pane="%12", inside=True, **extra):  # noqa: F811
    env = {
        "TMUX_LOG": str(kit.tmux_log),
        "PS_COUNT": str(kit.ps_count),
        "PANES_SRC": str(kit.panes),
        "PANES_SNAPSHOT": str(kit.snapshot),
    }
    if inside:
        env["TMUX"] = "/tmp/tmux-501/default,1234,0"
        env["TMUX_PANE"] = pane
    for i, names in enumerate(names_per_call):
        env[f"PS_NAMES_{i}"] = names
    env.update(extra)
    return kit.launch("--shell", "-c", "true", **env)


def _map(kit):  # noqa: F811
    """The map as it stands after the launch — i.e. the post-exit write."""
    return json.loads(kit.panes.read_text())


def _at_run(kit):  # noqa: F811
    """The map as it stood while the session was running — the pre-run write.

    The two writes see different worlds on purpose, and only this one can show
    the entry for the session itself: by the second, `--rm` has reaped the
    container and it is gone from `docker ps`.
    """
    return json.loads(kit.snapshot.read_text())


def _tmux_calls(kit):  # noqa: F811
    return kit.tmux_log.read_text().splitlines()


def _launched_name(kit):  # noqa: F811
    """The container name this launch minted, read back out of the map."""
    return next(k for k in _at_run(kit)["panes"] if k.startswith("cc-"))


# --- the stamp ----------------------------------------------------------------

def test_the_launch_stamps_its_container_name_onto_its_pane(panekit):
    """The load-bearing one, and the whole reason the map can be a live query.

    This is the only process that ever holds `$TMUX_PANE` and `$CONTAINER_NAME`
    together. Writing that pairing into a *file* made it a launch record — an
    entry could be preserved by later launches but never acquired, so a
    container already running when the file was created could never appear.
    Writing it onto the pane makes it a property of the thing itself, which any
    reader can enumerate at any time.
    """
    _launch(panekit, "", "")

    stamps = [c for c in _tmux_calls(panekit) if c.startswith("set-option -p")]

    assert len(stamps) == 1
    assert stamps[0].startswith("set-option -p -t %12 @cc cc-")


def test_the_stamp_is_set_before_the_map_is_written():
    """Order matters, because the map reads the stamp back. A map written first
    would miss the pane it was launched from on every first launch in a pane."""
    src = (KIT_ROOT / "claude.sh").read_text()
    body = src.split("\n    write_container_roster || true\n", 1)[1] \
              .split("docker run", 1)[0]

    assert body.index('tmux_stamp_pane "$CONTAINER_NAME"') \
        < body.index('write_pane_map "$CONTAINER_NAME"')


def test_the_stamp_is_pane_scoped(panekit):
    """`-p`, not `-w` and not `-g`. A window option would be shared by every
    pane in a split, and a global one by the whole server — either would tell
    the reader that half the terminals on the machine are the same container."""
    _launch(panekit, "", "")

    stamp = next(c for c in _tmux_calls(panekit) if c.startswith("set-option"))

    assert " -p " in f" {stamp} "
    assert " -g " not in f" {stamp} "
    assert " -w " not in f" {stamp} "


def test_outside_tmux_nothing_is_stamped(panekit):
    """The vanilla case for anyone who does not use tmux."""
    launch = _launch(panekit, "", "", inside=False)

    assert not any(c.startswith("set-option") for c in _tmux_calls(panekit))
    assert launch.status == 0


def test_a_tmux_that_cannot_stamp_never_reaches_the_user(panekit):
    """`set-option -p` needs tmux 3.0. An older one, or any other failure, must
    not print, must not trip `set -e`, and must not change the exit status —
    the reader falls back to `$TMUX_PANE` for this launch, which is exactly the
    behaviour that existed before the stamp did."""
    launch = _launch(panekit, "", "", TMUX_FAIL_STUB="1")

    assert launch.status == 0
    assert "tmux" not in launch.output.lower()


# --- the map, through the launcher's own call path ----------------------------

def test_a_launch_records_its_own_pane(panekit):
    """End to end: the launcher resolves `fleet-panes.sh` beside its dotfiles,
    runs it, and this launch is in the map the session is about to read.

    The stub cannot make the stamp real, so the entry here comes through the
    `$TMUX_PANE` fallback — which is the same path an old tmux takes, and the
    reason this test would still pass on one.
    """
    _launch(panekit, "", "")

    entry = _at_run(panekit)["panes"][_launched_name(panekit)]

    assert entry["pane"] == "%12"
    assert entry["session"] == "work"
    assert entry["at"].endswith("Z")


def test_the_key_is_the_name_docker_was_actually_given(panekit):
    """`/clear` mints a fresh session id — one container in the plugin's
    registry carries nine session UUIDs — so the container name is the only
    stable join key between this file, `live_containers.json`, and the
    registry's `hostname`. It is only a join key while it is the *same string*
    on both sides, which is what this compares."""
    launch = _launch(panekit, "", "")

    argv = launch.argv
    given = argv[argv.index("--name") + 1]

    assert _launched_name(panekit) == given
    assert argv[argv.index("--hostname") + 1] == given, \
        "the hostname is what the plugin records; it must be the same string"


def test_another_tab_survives_this_tab_launching(panekit):
    """The file is a map of the whole fleet. A launch that overwrote it would
    leave the board able to label exactly one session — the one you just
    started, which is the one you least need labelled."""
    _launch(panekit, "cc-other-01", "cc-other-01",
            TMUX_PANES_STUB="%3|cc-other-01|off|kit|work\n%12||off||work")

    at_run = _at_run(panekit)["panes"]

    assert at_run["cc-other-01"]["pane"] == "%3"
    assert at_run["cc-other-01"]["window"] == "kit"
    assert len(at_run) == 2
    # And it is still there after this tab's own entry has been retired.
    assert list(_map(panekit)["panes"]) == ["cc-other-01"]


def test_this_launchs_own_entry_is_retired_on_the_way_out(panekit):
    """Two calls, and only the first passes a name. By the second, `--rm` has
    reaped the container, so the same absent-from-`docker ps` rule that drops
    everyone else's dead tab drops this one."""
    _launch(panekit, "", "")

    assert _map(panekit)["panes"] == {}


def test_it_is_written_at_both_of_the_roster_s_call_points():
    """Pre-run so the SessionStart seconds later reads a fresh map with no
    daemon and no timer; post-exit so a closed tab does not label a session
    that has ended."""
    src = (KIT_ROOT / "claude.sh").read_text()

    # The pre-run call names this launch's container; the post-exit call names
    # nothing, which is what lets the absent-from-`docker ps` rule retire it.
    assert 'write_pane_map "$CONTAINER_NAME" || true' in src
    assert "\nwrite_pane_map || true\n" in src

    # And both sit with the roster's own calls, so the two readings are always
    # of the same moment. A map observed at a different instant from the roster
    # would let the board label a container the roster has already retired.
    after_pre_roster = src.split("\n    write_container_roster || true\n", 1)[1]
    assert 'write_pane_map "$CONTAINER_NAME"' in after_pre_roster.split(
        "docker run", 1)[0]
    after_post_roster = src.split("\nwrite_container_roster || true\n")[-1]
    assert "write_pane_map || true" in after_post_roster.split("exit ", 1)[0]


def test_the_map_is_one_shared_script_and_not_a_second_copy():
    """`fleet-watch` runs the same join before every redraw. Two copies of it is
    how a launcher and a board come to disagree about which pane is which, so
    the launcher owns no part of the join beyond calling it."""
    src = (KIT_ROOT / "claude.sh").read_text()
    body = src.split("write_pane_map() {", 1)[1].split("\n}", 1)[0]

    assert "fleet-panes.sh" in body
    assert "list-panes" not in body
    assert "docker ps" not in body


# --- when it must not act -----------------------------------------------------

def test_outside_tmux_nothing_is_written(panekit):
    """No file at all, so a reader sees "no map" rather than an empty one it
    would have to interpret."""
    launch = _launch(panekit, "", "", inside=False)

    assert not panekit.panes.exists()
    assert launch.status == 0


def test_no_data_dir_means_no_map_and_no_complaint(kit, tmp_path):  # noqa: F811
    """No plugin, no registry, nothing to join a pane id to."""
    (kit.stub_dir / "tmux").write_text(PANE_TMUX_STUB)
    (kit.stub_dir / "tmux").chmod(0o755)
    scripts = kit.root / "dotfiles" / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    shutil.copy(PANES_SCRIPT, scripts / "fleet-panes.sh")
    launch = kit.launch("--shell", "-c", "true",
                        TMUX_LOG=str(tmp_path / "t.log"),
                        TMUX="/tmp/tmux-501/default,1234,0", TMUX_PANE="%12")

    assert not (kit.workspace / ".multiplai" / "data" / "tmux").exists()
    assert launch.status == 0


def test_a_missing_script_is_not_an_error(panekit):
    """A partial install, a `dotfiles/` that did not travel. The launcher
    resolves the path but must not depend on what is at the end of it."""
    (panekit.root / "dotfiles" / "scripts" / "fleet-panes.sh").unlink()

    launch = _launch(panekit, "", "")

    assert launch.status == 0
    assert "fleet-panes" not in launch.output


def test_the_map_never_changes_the_exit_status(panekit):
    """It is a label on a board. Failing to observe must cost accuracy, never a
    session's exit code."""
    launch = _launch(panekit, "cc-01", "cc-01", MAIN_RUN_STATUS="42")

    assert launch.status == 42


def test_the_launcher_does_not_depend_on_an_exec_bit(panekit):
    """`bash "$script"`, for the reason `fleet-watch` runs the renderer through
    `python3`: a mode bit is a property of a checkout, and a launch is not the
    place to discover that one did not survive."""
    (panekit.root / "dotfiles" / "scripts" / "fleet-panes.sh").chmod(0o644)

    _launch(panekit, "", "")

    assert _at_run(panekit)["panes"][_launched_name(panekit)]["pane"] == "%12"


def test_the_write_is_atomic():
    """A reader in another container must never see a half-written file. The
    behaviour lives in the shared script; asserted from here too because the
    launch path is where a truncated map would do the damage."""
    body = PANES_SCRIPT.read_text()

    assert "mv -f" in body
    assert '> "$tmp"' in body


def test_the_docker_guard_is_present_for_a_host_without_it(panekit):
    """Container mode refuses to start without docker, so a full launch cannot
    reach this — but the map also runs from the exit path, and a daemon can be
    uninstalled mid-session."""
    script = panekit.root / "dotfiles" / "scripts" / "fleet-panes.sh"
    proc = subprocess.run(
        ["/bin/bash", str(script), "cc-x"],
        env={"PATH": "/nonexistent", "WORKSPACE": str(panekit.workspace),
             "TMUX": "/tmp/tmux-501/default,1234,0", "TMUX_PANE": "%12"},
        capture_output=True, text=True,
    )

    assert proc.returncode == 0
    assert not panekit.panes.exists()
