"""Pins the live-container roster in `claude.sh`.

A Claude session cannot observe its own death. A hook is code running inside
the session, so nothing fires for a reboot, a closed terminal, a `docker kill`
or an OOM — the multiplai-context fleet view has had to infer death from
silence, which on a real registry left 49 entries in permanent limbo. Only the
Mac can answer the question, because the container has no docker binary, no
socket, no root, and the build gateway's allowlist has never carried docker.

So `write_container_roster` writes `docker ps` names into
`$WORKSPACE/.multiplai/data/live_containers.json`, and the plugin treats "this
entry's container is absent from a roster observed *after* the entry's last
event" as proof the session is over.

**It is a poll, and that is the whole difference from the design kit 0.15.1
dropped.** That one wrote an `.exited` marker when `docker run` returned; the
launcher dies with the terminal on a reboot or a closed window, so the marker
only ever covered `docker kill` and OOM — zero entries in practice. A poll does
not care whether any launcher survived.

The invariants this file breaks if a future edit does:

* the roster is written **before** `docker run` — that is what makes it seconds
  old at the SessionStart that renders `AGENTS.md`, with no daemon and no timer;
* and **again after the session exits**, or the last container of a run would
  look alive until the next launch;
* it carries `observed_at`, `kind` and `observer`, because a reader must be able
  to refuse a roster it cannot interpret (a pid means something only in the
  namespace that saw it — the plugin's `fleet_sources/jobs.py` carries that scar
  already);
* it is best-effort everywhere: no docker, no data dir, or a daemon that has
  gone away are silent no-ops, and none of them may change the exit status.

Losing the roster costs accuracy in a status view. It must never cost a session.
"""

import json
import subprocess

import pytest

from test_claude_sh_env import kit  # noqa: F401 — `kit` is a fixture

from conftest import KIT_ROOT

# Serves `docker ps` from a counter-indexed script so the pre-run and post-exit
# observations can be told apart — the point of the second write is that it sees
# a *different* world from the first. An index with no `PS_NAMES_<n>` set falls
# back to the last one that is, so a test that passes a single reading is saying
# "the world does not change across this launch".
ROSTER_DOCKER_STUB = """\
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
        exit 0
        ;;
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
def rosterkit(kit, tmp_path):  # noqa: F811
    """`kit` with a ps-aware docker stub and a data dir for the roster."""
    (kit.stub_dir / "docker").write_text(ROSTER_DOCKER_STUB)
    (kit.stub_dir / "docker").chmod(0o755)
    kit.data_dir = kit.workspace / ".multiplai" / "data"
    kit.data_dir.mkdir(parents=True)
    kit.ps_count = tmp_path / "ps_count.txt"
    kit.roster = kit.data_dir / "live_containers.json"
    return kit


def _launch(kit, *names_per_call, status=None):  # noqa: F811
    """Run the launcher; `names_per_call[i]` is what the i-th `docker ps` sees."""
    extra = {"PS_COUNT": str(kit.ps_count)}
    for i, names in enumerate(names_per_call):
        extra[f"PS_NAMES_{i}"] = names
    if status is not None:
        extra["MAIN_RUN_STATUS"] = str(status)
    return kit.launch("--shell", "-c", "true", **extra)


def _roster(kit):  # noqa: F811
    return json.loads(kit.roster.read_text())


# --- the shape of the file ----------------------------------------------------

def test_a_launch_writes_the_running_container_names(rosterkit):
    _launch(rosterkit, "claude-personal-01\nclaude-work-02")

    assert set(_roster(rosterkit)["ids"]) == {"claude-personal-01", "claude-work-02"}


def test_the_reading_says_what_it_is_and_when(rosterkit):
    """`kind` and `observer` are not decoration. A container name is globally
    meaningful because there is one daemon; a pid is meaningful only in the
    namespace that observed it. When session identity moves to a pid under the
    SDK, these are what stop a reader from matching the two."""
    _launch(rosterkit, "claude-personal-01")

    r = _roster(rosterkit)

    assert r["kind"] == "container"
    assert r["observer"] == "host"
    assert r["version"] == 1
    # Parseable as an instant, which is the only property the reader needs:
    # a roster older than an entry decides nothing about it.
    assert r["observed_at"].endswith("Z") and len(r["observed_at"]) == 20


def test_an_empty_daemon_is_a_roster_of_nothing_not_a_missing_file(rosterkit):
    """The distinction the reader depends on: "nothing is running" is an
    answer, "no file" is the absence of one. Collapsing them would make the
    first reboot of the day indistinguishable from a vanilla install."""
    _launch(rosterkit, "")

    assert _roster(rosterkit)["ids"] == []


def test_a_name_that_could_break_the_json_is_dropped(rosterkit):
    """Docker's own name grammar cannot produce these, so this is belt and
    braces — but a corrupt roster is worse than no roster, since the reader
    would fall back on parse failure and silently lose every reading."""
    _launch(rosterkit, 'claude-ok\nbad"quote\nbad\\\\slash')

    assert _roster(rosterkit)["ids"] == ["claude-ok"]


# --- when it is written -------------------------------------------------------

def test_it_is_written_before_the_session_container_starts(rosterkit):
    """The load-bearing one. Every hook-path render of AGENTS.md happens at
    SessionStart, inside a container this launcher started seconds earlier — so
    a pre-run write is what makes the roster fresh with no daemon and no timer.

    The session's own container is deliberately absent from that reading: its
    registry entry does not exist yet, and an entry is only ever judged against
    a roster observed after its last event."""
    _launch(rosterkit, "claude-earlier-01", "claude-earlier-01")

    # Two observations for one launch: one before `docker run`, one after.
    assert int(rosterkit.ps_count.read_text()) == 2


def test_the_exit_observation_is_the_one_that_retires_the_session(rosterkit):
    """`docker run --rm` has reaped the container by the time the launcher
    returns, so the post-exit `ps` is the first that can see it gone. Without
    it the last session of a run stays "alive" until the next launch."""
    _launch(rosterkit, "claude-me-01\nclaude-other-02", "claude-other-02")

    assert _roster(rosterkit)["ids"] == ["claude-other-02"]


def test_the_roster_never_changes_the_exit_status(rosterkit):
    """It is a status view. A failure to observe must cost accuracy, never a
    session's exit code."""
    launch = _launch(rosterkit, "claude-01", "claude-01", status=42)

    assert launch.status == 42


# --- when it cannot be written ------------------------------------------------

def test_no_data_dir_means_no_roster_and_no_complaint(kit):  # noqa: F811
    """No plugin, no registry, nothing to judge — so nothing to observe. The
    workspace here has no `.multiplai/data`."""
    launch = kit.launch("--shell", "-c", "true")

    assert not (kit.workspace / ".multiplai" / "data" / "live_containers.json").exists()
    assert launch.status == 0


def test_a_failing_daemon_leaves_no_partial_file(rosterkit):
    """`docker ps` failing mid-run must leave the previous reading — or no
    reading — never a truncated one. The reader treats a parse failure as "no
    roster", so a half-written file silently disables the whole feature."""
    (rosterkit.stub_dir / "docker").write_text(
        ROSTER_DOCKER_STUB.replace("        exit 0\n        ;;\n    run)",
                                   "        exit 1\n        ;;\n    run)")
    )
    (rosterkit.stub_dir / "docker").chmod(0o755)

    launch = _launch(rosterkit, "ignored")

    assert not rosterkit.roster.exists()
    assert launch.status == 0
    # And no scratch file was left behind next to it.
    assert list(rosterkit.data_dir.glob(".live_containers.json.*")) == []


def test_the_write_is_atomic():
    """A reader in another container must never see a half-written file, so the
    roster is built in a scratch file and renamed into place."""
    src = (KIT_ROOT / "claude.sh").read_text()
    body = src.split("write_container_roster() {", 1)[1].split("\npost_exit_drain()", 1)[0]

    assert "mv -f" in body
    assert '> "$tmp"' in body
    assert "> \"$data_dir/live_containers.json\"" not in body


def test_the_docker_guard_is_present_for_a_host_without_it(rosterkit):
    """Container mode refuses to start without docker, so this guard cannot be
    reached through a full launch — but the function is called from the exit
    path too, and a daemon can be uninstalled mid-session. Extracted and run
    under a PATH that genuinely lacks docker."""
    src = (KIT_ROOT / "claude.sh").read_text()
    fn = "write_container_roster() {" + src.split("write_container_roster() {", 1)[1] \
        .split("\npost_exit_drain()", 1)[0]

    script = f'WORKSPACE="{rosterkit.workspace}"\n{fn}\nwrite_container_roster\necho "rc=$?"'
    proc = subprocess.run(
        ["/bin/bash", "-c", script],
        env={"PATH": "/nonexistent"}, capture_output=True, text=True,
    )

    assert "rc=0" in proc.stdout
    assert not rosterkit.roster.exists()
