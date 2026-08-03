"""Pins the observed-exit marker `claude.sh` drops when a container dies.

The multiplai-context plugin's hooks maintain a session registry, but a hook
can only ever report from *inside* a session — so a container killed before
its SessionEnd could fire (reboot, `docker kill`, OOM, or simply closing the
tab, all routine with `--rm`) leaves an entry whose last recorded event is a
week-old Notification. The fleet view then reads that entry as a live agent
waiting on you. On the real registry (2026-08-03) this produced a status line
reading "36 fronts · 5 need you" over a fleet of one running session.

The launcher is the only observer standing *outside* the container at the
moment it dies, which is why the fix lives here and not in a hook. It writes
an empty `<sid>.exited` file beside the registry entry; the plugin reads it
(`session_registry.is_exited`) and clears it on the next in-session event.

**A marker, not an `end` event written into the entry.** The host may have no
`jq`, and a second writer of registry *state* is exactly the drift the JSON
entry format exists to prevent. Outside observers leave markers — the hub's
`.adopt` is the same convention — and the plugin owns the JSON.

Tested with a stub `docker` that plays the part of the container: on `run` it
writes the registry entry the plugin's hooks would have written, stamped with
the `--name` the launcher just assigned it. That is what makes the hostname
lookup a real lookup rather than a fixture — the test cannot predict the
container name (it carries a timestamp suffix), and neither can anything else
but the launcher itself.
"""

import json
import subprocess
from pathlib import Path

import pytest

from test_claude_sh_env import kit  # noqa: F401 — `kit` is a fixture

SID = "11111111-2222-3333-4444-555555555555"

# Plays the container: records its own registry entry under the --name the
# launcher assigned, then exits. The drain container (--name multiplai-drain-*)
# and the venv-ownership prep run (--entrypoint) are not the session and must
# not overwrite it.
SESSION_DOCKER_STUB = """\
#!/bin/bash
case "$1" in
    image) exit 0 ;;
    run)
        for a in "$@"; do
            [ "$a" = "--entrypoint" ] && exit 0
            case "$a" in multiplai-drain-*) exit 0 ;; esac
        done
        name=""
        prev=""
        for a in "$@"; do
            [ "$prev" = "--name" ] && name="$a"
            prev="$a"
        done
        if [ -n "$ENTRY_DIR" ] && [ -n "$ENTRY_SID" ]; then
            mkdir -p "$ENTRY_DIR"
            printf '{"session_id":"%s","hostname":"%s","cwd":"/work",' \
                "$ENTRY_SID" "${ENTRY_HOSTNAME:-$name}" > "$ENTRY_DIR/$ENTRY_SID.json"
            printf '"last_event":{"ts":"2026-01-01T00:00:00+00:00","kind":"notification"}}' \
                >> "$ENTRY_DIR/$ENTRY_SID.json"
        fi
        exit "${MAIN_RUN_STATUS:-0}"
        ;;
esac
exit 0
"""


@pytest.fixture
def sessionkit(kit):
    (kit.stub_dir / "docker").write_text(SESSION_DOCKER_STUB)
    (kit.stub_dir / "docker").chmod(0o755)
    kit.sessions = kit.workspace / ".multiplai" / "data" / "sessions"
    return kit


def _launch(kit, *args, sid=SID, **env):
    return kit.launch(*args, ENTRY_DIR=str(kit.sessions), ENTRY_SID=sid, **env)


def _marker(kit, sid=SID):
    return kit.sessions / f"{sid}.exited"


class TestExitMarker:

    def test_it_is_written_when_the_container_exits(self, sessionkit):
        _launch(sessionkit)

        assert _marker(sessionkit).exists()
        assert _marker(sessionkit).read_bytes() == b"", "an empty marker, not state"

    def test_the_entry_itself_is_untouched(self, sessionkit):
        """The plugin owns the JSON. The launcher only leaves a filename."""
        _launch(sessionkit)

        entry = json.loads((sessionkit.sessions / f"{SID}.json").read_text())
        assert entry["last_event"]["kind"] == "notification"

    def test_a_failing_session_is_still_marked(self, sessionkit):
        """A non-zero exit is the case that most needs marking — a crash is
        precisely what does not get to run its SessionEnd hook."""
        _launch(sessionkit, MAIN_RUN_STATUS="3")

        assert _marker(sessionkit).exists()

    def test_it_does_not_change_the_exit_status(self, sessionkit):
        launch = _launch(sessionkit, MAIN_RUN_STATUS="3")

        assert launch.status == 3

    def test_it_is_silent(self, sessionkit):
        launch = _launch(sessionkit)

        assert "exited" not in launch.output

    def test_no_registry_means_no_marker(self, sessionkit):
        """No plugin installed: nothing to mark, and nothing to fail on."""
        launch = sessionkit.launch()

        assert launch.status == 0
        assert not sessionkit.sessions.exists()

    def test_an_entry_for_another_container_is_not_marked(self, sessionkit):
        """The lookup is by hostname. Another session's entry — a tab still
        running in a different container — must not be declared dead."""
        _launch(sessionkit, ENTRY_HOSTNAME="claude-some-other-container")

        assert not _marker(sessionkit).exists()

    def test_a_non_uuid_entry_name_is_refused(self, sessionkit):
        """Registry filenames come from a container-writable directory, and
        the name is interpolated into a path. Same guard the `--resume` and
        hub-URL uses get."""
        _launch(sessionkit, sid="not-a-uuid")

        assert not _marker(sessionkit, sid="not-a-uuid").exists()

    def test_shell_mode_has_no_session_to_mark(self, sessionkit):
        """`--shell` runs bash; there is no claude session behind it."""
        _launch(sessionkit, "--shell")

        assert not _marker(sessionkit).exists()

    def test_a_read_only_registry_does_not_fail_the_exit(self, sessionkit):
        """Best-effort: an unwritable registry is a degraded environment, not
        a reason to change what the user's session returned."""
        _launch(sessionkit)  # create the dir via the stub
        sessionkit.sessions.chmod(0o555)
        try:
            launch = _launch(sessionkit, MAIN_RUN_STATUS="7")
        finally:
            sessionkit.sessions.chmod(0o755)

        assert launch.status == 7


class TestShippedSource:
    """The marker's name is a contract with the plugin — it is what
    `session_registry.EXITED_SUFFIX` globs for. Renaming it here silently
    turns the whole mechanism off rather than breaking anything loudly."""

    def test_the_suffix_is_exited(self):
        src = (Path(__file__).resolve().parents[2] / "claude.sh").read_text()

        assert '"$SESSIONS_DIR/$SID.exited"' in src

    def test_the_launcher_still_parses(self):
        launcher = Path(__file__).resolve().parents[2] / "claude.sh"

        assert subprocess.run(["bash", "-n", str(launcher)]).returncode == 0
