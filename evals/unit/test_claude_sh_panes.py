"""Pins the tmux pane map in `claude.sh`.

The multiplai-context plugin can never observe which tmux pane a session is
sitting in. `record_event()` runs *inside* the container and tmux runs on the
Mac, so `$TMUX_PANE` there is not merely absent — it is unknowable. Every tmux
fact has to be written host-side and joined at render time, which is exactly
the shape `live_containers.json` already has.

So `write_pane_map` writes `$WORKSPACE/.multiplai/data/tmux/panes.json`, keyed
by **container name** — the registry's `hostname` field, and the only stable
join key here, because `/clear` mints a fresh session id while the container
name survives every one of them.

The invariants this file breaks if a future edit does:

* it **merges**. Other tabs' entries are the whole content of the file; a
  launch in one tab that blanked the other nine would leave the board
  unlabelled for everything except the tab you just started;
* an entry survives only while `docker ps` still lists its container, which is
  what bounds the file and retires a closed tab. The post-exit call passes no
  name, so this launch's own entry goes the same way;
* it carries ``version`` / ``observer`` / ``kind`` / ``server``. The first
  three for the reason the roster carries them — a reader must be able to
  refuse a payload it cannot interpret — and ``server`` because **pane ids are
  recycled per tmux server**, so `%12` means nothing without knowing which
  server issued it. A reader that ignored it could attribute one pane's
  attention to another session, which is the one failure the seen axis must
  not have;
* it is best-effort everywhere: no tmux, no `$TMUX_PANE`, no data dir, a
  failing tmux or a failing docker are all silent no-ops, and none of them may
  change the exit status.

Losing the map costs a label on a status bar. It must never cost a session.
"""

import json
import subprocess
from pathlib import Path

import pytest

from test_claude_sh_env import kit  # noqa: F401 — `kit` is a fixture

KIT_ROOT = Path(__file__).resolve().parents[2]

# Answers each `display-message` format separately — the pane map asks four
# distinct questions and a stub that answered them all the same would let a
# launcher that read the wrong variable pass.
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
    """`kit` inside tmux, with a ps-aware docker and a data dir to write into."""
    (kit.stub_dir / "tmux").write_text(PANE_TMUX_STUB)
    (kit.stub_dir / "tmux").chmod(0o755)
    (kit.stub_dir / "docker").write_text(PANE_DOCKER_STUB)
    (kit.stub_dir / "docker").chmod(0o755)
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


def _launched_name(kit):  # noqa: F811
    """The container name this launch minted, read back out of the map."""
    return next(k for k in _at_run(kit)["panes"] if k.startswith("claude-"))


def _seed(kit, *entries, server="/private/tmp/tmux-501/default"):  # noqa: F811
    """Pre-existing entries for other tabs, in the shape the launcher writes.

    One line per entry is not cosmetic: the merge re-reads this file with
    nothing but `grep`, because `jq` is optional on a Mac and this runs on the
    launch path.
    """
    kit.panes.parent.mkdir(parents=True, exist_ok=True)
    lines = ",\n".join(
        f'    "{name}": {{"pane": "{pane}", "server": "{server}", '
        f'"window": "{window}", '
        f'"session": "work", "at": "2026-08-06T21:00:00Z"}}'
        for name, pane, window in entries
    )
    kit.panes.write_text(
        '{\n  "version": 1,\n  "observed_at": "2026-08-06T21:00:00Z",\n'
        '  "observer": "host",\n  "kind": "tmux",\n'
        '  "server": "/private/tmp/tmux-501/default",\n'
        f'  "panes": {{\n{lines}\n  }}\n}}\n'
    )


# --- the shape of the file ----------------------------------------------------

def test_a_launch_records_its_own_pane(panekit):
    """The load-bearing one: the launcher is the only process that ever holds
    `$TMUX_PANE` and `$CONTAINER_NAME` at the same moment."""
    _launch(panekit, "", "")

    entry = _at_run(panekit)["panes"][_launched_name(panekit)]

    assert entry["pane"] == "%12"
    assert entry["session"] == "work"
    assert entry["at"].endswith("Z")


def test_an_auto_named_window_is_not_recorded_as_a_label(panekit):
    """With `automatic-rename` on — tmux's default, and what the launcher's own
    rename guard tests for — `#{window_name}` is whatever tmux derived from the
    running process: `bash` in a fresh window, `claude.sh` mid-launch. Recording
    it would put `project@bash` on the board. Empty is the honest answer, and it
    lets the reader fall back to the worktree/branch label it already builds."""
    _launch(panekit, "", "", TMUX_NAME_STUB="bash", TMUX_AUTO_STUB="on")

    assert _at_run(panekit)["panes"][_launched_name(panekit)]["window"] == ""


def test_a_window_the_user_pinned_is_recorded(panekit):
    """`automatic-rename off` is the one state that means a human typed this
    string, which is the only case the label is worth anything."""
    _launch(panekit, "", "", TMUX_NAME_STUB="kit-review", TMUX_AUTO_STUB="off")

    assert _at_run(panekit)["panes"][_launched_name(panekit)]["window"] == "kit-review"


def test_a_globally_pinned_window_is_recorded_too(panekit):
    """The other half of the same regression, in the opposite direction.

    `set -g automatic-rename off` claims every tab, but the launcher read the
    option with `show-window-options -v`, which returns the *window-local*
    value and prints nothing when only the global was set. The record guard
    tests `= "off"`, so it never fired and every entry carried `"window": ""`
    — which is why the board showed `claude-personal…` for every agent instead
    of the tab names their owner had chosen.

    Reproduced on tmux 3.4: with a global `off`, `-v` returns empty while both
    `-gv` and `-Av` return `off`.
    """
    _launch(panekit, "", "", TMUX_NAME_STUB="kit-review", TMUX_AUTO_STUB="off",
            TMUX_AUTO_SCOPE="global")

    assert _at_run(panekit)["panes"][_launched_name(panekit)]["window"] == "kit-review"


def test_a_window_that_opts_back_in_is_not_recorded(panekit):
    """The record direction of the `-gv` vs `-Av` difference.

    A window set back to `automatic-rename on` under a global `off` is naming
    itself, so whatever it is called right now is tmux's derived name and not a
    handle anyone chose — recording it would put `zsh` on the board with the
    same confidence as a real label. `-gv` cannot see the override and would
    record it; `-Av` resolves to the window's own `on` and correctly declines.
    """
    _launch(panekit, "", "", TMUX_NAME_STUB="zsh", TMUX_AUTO_STUB="off",
            TMUX_AUTO_SCOPE="global", TMUX_AUTO_LOCAL="on")

    assert _at_run(panekit)["panes"][_launched_name(panekit)]["window"] == ""


def test_the_reading_says_what_it_is_and_which_server_issued_it(panekit):
    """`kind` and `observer` for the reason the roster carries them. `server`
    for a sharper one: pane ids are recycled per tmux server, so a `viewed`
    marker written against one server must not be applied to a pane id from
    another. Without this field a reader cannot tell, and the failure mode is
    marking an agent seen that nobody looked at."""
    _launch(panekit, "", "")

    m = _at_run(panekit)

    assert m["version"] == 1
    assert m["kind"] == "tmux"
    assert m["observer"] == "host"
    assert m["server"] == "/private/tmp/tmux-501/default"
    assert m["observed_at"].endswith("Z") and len(m["observed_at"]) == 20


def test_each_entry_carries_the_server_that_issued_its_pane_id(panekit):
    """Per entry, not just at the top level. The file merges across tabs, and
    two tabs can be on two tmux servers — a single top-level socket path would
    relabel every carried-forward entry as this launch's, which is precisely
    the mis-attribution the field exists to prevent."""
    _launch(panekit, "", "")

    entry = _at_run(panekit)["panes"][_launched_name(panekit)]

    assert entry["server"] == "/private/tmp/tmux-501/default"


def test_a_window_name_that_could_break_the_json_is_stripped(panekit):
    """Unlike a container name, a window name is arbitrary user text. A lossy
    label beats an unparseable file, which would silently disable the map for
    every reader rather than for one tab."""
    _launch(panekit, "", "", TMUX_NAME_STUB='ev"il\\one', TMUX_AUTO_STUB="off")

    assert _at_run(panekit)["panes"][_launched_name(panekit)]["window"] == "evilone"


# --- merging ------------------------------------------------------------------

def test_another_tab_survives_this_tab_launching(panekit):
    """The file is a map of the whole fleet, written one tab at a time. A
    launch that overwrote it would leave the board able to label exactly one
    session — the one you just started, which is the one you least need
    labelled."""
    _seed(panekit, ("claude-other-01", "%3", "kit"))

    _launch(panekit, "claude-other-01", "claude-other-01")

    at_run = _at_run(panekit)["panes"]

    assert at_run["claude-other-01"]["pane"] == "%3"
    assert at_run["claude-other-01"]["window"] == "kit"
    assert len(at_run) == 2
    # And it is still there after this tab's own entry has been retired.
    assert list(_map(panekit)["panes"]) == ["claude-other-01"]


def test_a_carried_entry_keeps_the_server_it_was_written_with(panekit):
    """The reason `server` is per entry. This tab is on the default socket; the
    other one is on a second tmux server where `%3` means something else
    entirely. Carrying the entry forward under *this* launch's socket path
    would make a stale pane id look current, and a `viewed` marker for our `%3`
    would be applied to their session."""
    other = "/private/tmp/tmux-501/second"
    _seed(panekit, ("claude-other-01", "%3", "kit"), server=other)

    _launch(panekit, "claude-other-01", "claude-other-01")

    at_run = _at_run(panekit)["panes"]

    assert at_run["claude-other-01"]["server"] == other
    assert at_run[_launched_name(panekit)]["server"] == "/private/tmp/tmux-501/default"


def test_a_tab_whose_container_is_gone_is_dropped(panekit):
    """The bound on the file, and the mechanism that retires a closed tab.
    `docker ps` is the same reading `write_container_roster` already takes."""
    _seed(panekit, ("claude-dead-09", "%1", "old"))

    _launch(panekit, "", "")

    assert "claude-dead-09" not in _at_run(panekit)["panes"]


def test_this_launchs_own_entry_is_retired_on_the_way_out(panekit):
    """Two calls, and only the first passes a name. By the second, `--rm` has
    reaped the container, so the same absent-from-`docker ps` rule that drops
    everyone else's dead tab drops this one."""
    _launch(panekit, "", "")

    assert _map(panekit)["panes"] == {}


def test_it_is_written_at_both_of_the_roster_s_call_points(panekit):
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


# --- when it must not act -----------------------------------------------------

def test_outside_tmux_nothing_is_written(panekit):
    """The vanilla case for anyone who does not use tmux. No file at all, so a
    reader sees "no map" rather than an empty one it would have to interpret."""
    launch = _launch(panekit, "", "", inside=False)

    assert not panekit.panes.exists()
    assert launch.status == 0


def test_no_data_dir_means_no_map_and_no_complaint(kit, tmp_path):  # noqa: F811
    """No plugin, no registry, nothing to join a pane id to."""
    (kit.stub_dir / "tmux").write_text(PANE_TMUX_STUB)
    (kit.stub_dir / "tmux").chmod(0o755)
    launch = kit.launch("--shell", "-c", "true",
                        TMUX_LOG=str(tmp_path / "t.log"),
                        TMUX="/tmp/tmux-501/default,1234,0", TMUX_PANE="%12")

    assert not (kit.workspace / ".multiplai" / "data" / "tmux").exists()
    assert launch.status == 0


def test_a_pane_with_no_id_records_nothing_rather_than_a_blank_key(panekit):
    """The map exists to answer "which pane". An entry that cannot is worse
    than a missing one — it would join to whatever a blank pane id matched."""
    launch = _launch(panekit, "", "", TMUX_PANEID_STUB="")

    assert _at_run(panekit)["panes"] == {}
    assert launch.status == 0


# --- when it cannot act -------------------------------------------------------

def test_a_failing_tmux_never_reaches_the_user(panekit):
    """A tmux that errors on every call must not print, must not trip `set -e`,
    and must not leave a half-written map."""
    launch = _launch(panekit, "", "", TMUX_FAIL_STUB="1")

    assert launch.status == 0
    assert "tmux" not in launch.output.lower()


def test_a_failing_daemon_leaves_no_map_and_no_scratch_file(panekit):
    """A reader treats a parse failure as "no map", so a truncated file
    silently disables the feature. Better to write nothing."""
    launch = _launch(panekit, "ignored", "ignored", PS_STATUS="1")

    assert not panekit.panes.exists()
    assert launch.status == 0
    assert list((panekit.data_dir / "tmux").glob(".panes.json.*")) == []


def test_the_map_never_changes_the_exit_status(panekit):
    """It is a label on a status bar. Failing to observe must cost accuracy,
    never a session's exit code."""
    launch = _launch(panekit, "claude-01", "claude-01", MAIN_RUN_STATUS="42")

    assert launch.status == 42


def test_the_write_is_atomic(panekit):
    """A reader in another container must never see a half-written file, so the
    map is built in a scratch file and renamed into place."""
    src = (KIT_ROOT / "claude.sh").read_text()
    body = src.split("write_pane_map() {", 1)[1].split("\npost_exit_drain()", 1)[0]

    assert "mv -f" in body
    assert '> "$tmp"' in body
    assert '> "$data_dir/tmux/panes.json"' not in body


def test_the_docker_guard_is_present_for_a_host_without_it(panekit):
    """Container mode refuses to start without docker, so a full launch cannot
    reach this — but the function also runs from the exit path, and a daemon
    can be uninstalled mid-session."""
    src = (KIT_ROOT / "claude.sh").read_text()
    fn = "write_pane_map() {" + src.split("write_pane_map() {", 1)[1] \
        .split("\npost_exit_drain()", 1)[0]
    avail = "tmux_available() {" + src.split("tmux_available() {", 1)[1] \
        .split("\n}", 1)[0] + "\n}"

    script = (f'WORKSPACE="{panekit.workspace}"\nTMUX=x\nTMUX_PANE=%1\n'
              f'{avail}\n{fn}\nwrite_pane_map claude-x\necho "rc=$?"')
    proc = subprocess.run(
        ["/bin/bash", "-c", script],
        env={"PATH": "/nonexistent"}, capture_output=True, text=True,
    )

    assert "rc=0" in proc.stdout
    assert not panekit.panes.exists()
