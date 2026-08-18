"""Pins the post-exit extraction drain in `claude.sh`.

The multiplai-context plugin defers extraction to a marker file, and until this
landed the only thing that ever drained the queue was the *next* `SessionStart`
— so the last tab of the day left its diary entry unwritten until the next
session opened, possibly days later. `claude.sh` now launches a disposable,
detached **drain container** from the same image the session ran in, with the
plugin's `drain_extractions.py` as its process.

An earlier design ran the drain directly on the host and was rejected: it
executed code resolved from `installed_plugins.json` / the plugin cache, both
of which live in the rw-mounted dotfiles dir and are writable by in-container
code — a container→host code-execution channel. In the shipped design the host
only decides WHETHER to launch (markers present?) and assembles the
`docker run`; resolving which script to run happens inside the container.

Two layers are tested, both without a docker daemon:

* **The launcher's decision logic** — a stub `docker` first on `PATH` records
  the drain `docker run` argv (NUL-separated, since the in-container command
  spans lines). Same technique as `test_claude_sh_env.py`, same reason: what
  the argv asks docker for is exactly what the container would get.
* **The in-container command** — the `bash -c` payload recorded on that argv is
  executed locally against a fixture config dir with a stub `uv`, which is
  faithful because inside the container it runs under bash against the same
  mounted paths.

The guard preconditions (`command -v docker`, `docker image inspect`) cannot be
exercised through a full launch — container mode refuses to start without both,
so by the time `post_exit_drain` runs they always hold. Those two tests extract
the drain block from the shipped source and run it under a sanitized `PATH`
that genuinely lacks docker / serves a failing stub. (The previous design's
missing-`uv` test skipped the sanitization and was vacuous: real `uv` was
always reachable through the inherited `PATH`.)

The invariants that matter, and that this file breaks if a future edit does:

* the drain never changes `claude.sh`'s exit status;
* it launches only when a marker is actually queued, and the host reads
  nothing but marker filenames — never `installed_plugins.json`, never the
  plugin cache;
* the drain container gets exactly two env vars (`WORKSPACE`,
  `CLAUDE_CONFIG_DIR`) and three mounts (workspace, config dir, live
  credentials) — no `.env` secrets, no API key, no kit checkout;
* it is silent — no output on any path, and no prompt (a second `read` here
  would fight the hub take-back's);
* in-container resolution follows the manifest only, and runs the drain with
  `--wait` so the `--rm` container outlives its extraction children.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from test_claude_sh_env import kit  # noqa: F401 — `kit` is a fixture

from conftest import KIT_ROOT
LAUNCHER_SOURCE = KIT_ROOT / "claude.sh"

# Distinguishes the session's `docker run` from the drain's by the --name the
# drain always passes, and records the drain argv NUL-separated: the drain's
# `bash -c` payload contains newlines, so line-based capture could not be
# split back into argv entries.
DRAIN_DOCKER_STUB = """\
#!/bin/bash
case "$1" in
    image) exit 0 ;;
    run)
        # The venv-ownership prep run uses --entrypoint; not one we record.
        for a in "$@"; do
            if [ "$a" = "--entrypoint" ]; then exit 0; fi
        done
        for a in "$@"; do
            case "$a" in
                multiplai-drain-*)
                    printf '%s\\0' "$@" > "$DRAIN_ARGV_OUT"
                    exit "${DRAIN_RUN_STATUS:-0}" ;;
            esac
        done
        printf '%s\\n' "$@" > "$DOCKER_ARGV_OUT"
        env > "$DOCKER_ENV_OUT"
        exit "${MAIN_RUN_STATUS:-0}"
        ;;
esac
exit 0
"""

UV_STUB = """\
#!/bin/bash
printf '%s\\n' "$@" > "$UV_ARGV_OUT"
exit 0
"""


class DrainRun:
    """The drain container's `docker run` argv, or nothing if never assembled."""

    def __init__(self, argv, launch):
        self.argv = argv
        self.launch = launch

    @property
    def ran(self):
        return bool(self.argv)

    def values_after(self, flag):
        """Every argv value directly following `flag` (e.g. all -v mounts)."""
        return [self.argv[i + 1] for i, a in enumerate(self.argv) if a == flag]

    @property
    def name(self):
        names = self.values_after("--name")
        assert len(names) == 1, self.argv
        return names[0]

    @property
    def payload(self):
        """The `bash -c` command the container would execute."""
        assert self.argv[-3:-1] == ["bash", "-c"], self.argv
        return self.argv[-1]


def _install_plugin(kit, version="0.11.0", with_script=True):
    """A plugin cache entry plus the manifest Claude Code writes beside it."""
    install_path = (
        kit.root / "dotfiles" / "plugins" / "cache" / "multiplai" /
        "multiplai-context" / version
    )
    (install_path / "scripts").mkdir(parents=True)
    if with_script:
        (install_path / "scripts" / "drain_extractions.py").write_text("# stub\n")
    manifest = kit.root / "dotfiles" / "plugins" / "installed_plugins.json"
    manifest.write_text(json.dumps({
        "version": 2,
        "plugins": {
            "multiplai-context@multiplai": [
                {"scope": "user", "installPath": str(install_path), "version": version}
            ]
        },
    }))
    return install_path


def _queue_marker(kit, sid="11111111-2222-3333-4444-555555555555"):
    pending = kit.workspace / ".multiplai" / "data" / "pending_extractions"
    pending.mkdir(parents=True, exist_ok=True)
    (pending / f"{sid}.json").write_text(json.dumps({"session_id": sid}))
    return pending


def _strand_marker(kit, sid="99999999-8888-7777-6666-555555555555"):
    """A marker orphaned in processing_extractions/.

    This is what a container torn down mid-extraction leaves behind: the
    detached child died with it, and only the drain's recover_stale_processing
    ever puts the marker back.
    """
    processing = kit.workspace / ".multiplai" / "data" / "processing_extractions"
    processing.mkdir(parents=True, exist_ok=True)
    (processing / f"{sid}.json").write_text(json.dumps({"session_id": sid}))
    return processing


def _creds(kit):
    """The host credentials file the launcher bind-mounts into the container."""
    d = kit.home / ".claude-container"
    d.mkdir(parents=True, exist_ok=True)
    f = d / "credentials.json"
    f.write_text('{"token": "live"}')
    return f


def _run(kit, *args, **env):
    """Launch and collect the drain `docker run` argv the stub recorded.

    The drain's docker CLIENT call is synchronous (only the container it asks
    for would be detached), and here the client is the stub — so by the time
    `claude.sh` exits, the argv file is final. No polling.
    """
    launch = kit.launch(*args, DRAIN_ARGV_OUT=str(kit.drain_argv_out), **env)
    raw = kit.drain_argv_out.read_text()
    argv = raw.split("\0")[:-1] if raw else []
    return DrainRun(argv, launch)


@pytest.fixture
def drainkit(kit):
    (kit.stub_dir / "docker").write_text(DRAIN_DOCKER_STUB)
    kit.drain_argv_out = kit.root / "drain_argv.txt"
    kit.drain_argv_out.write_text("")
    _creds(kit)
    return kit


# --- launch decision ---------------------------------------------------------


def test_a_queued_marker_launches_a_drain_container(drainkit):
    _install_plugin(drainkit)
    _queue_marker(drainkit)

    d = _run(drainkit, "--shell", "-c", "true")

    assert d.launch.status == 0, d.launch.output
    assert d.ran, "a marker was queued but no drain container was launched"
    # Detached client, self-reaping container, the session's own image.
    assert "-d" in d.argv
    assert "--rm" in d.argv
    assert d.argv[-4] == "claude-multiplai:local"
    assert re.fullmatch(r"multiplai-drain-\d{14}-\d+", d.name)
    # The container command is a bash payload — the launcher hands over a
    # program to run inside the trust domain, never a resolved host path.
    assert "drain_extractions.py" in d.payload


def test_no_marker_means_no_drain(drainkit):
    """A launcher that spawns a container on every exit for nothing is a tax
    on every session; the queue check is what keeps it free."""
    _install_plugin(drainkit)
    # No marker queued.

    d = _run(drainkit, "--shell", "-c", "true")

    assert d.launch.status == 0, d.launch.output
    assert not d.ran


def test_a_stranded_marker_still_triggers_the_drain(drainkit):
    """The repair case, and the one this launcher is best placed to serve.

    A session whose container died mid-extraction leaves its marker in
    processing_extractions/, never in pending_extractions/. Checking only the
    pending queue meant the launcher returned early and the orphan waited for
    whenever a *new* session next happened to start — which, for the last tab
    of the day, is the exact wait this whole feature exists to remove.
    """
    _install_plugin(drainkit)
    _strand_marker(drainkit)
    # Deliberately nothing in pending_extractions/.

    d = _run(drainkit, "--shell", "-c", "true")

    assert d.launch.status == 0, d.launch.output
    assert d.ran


def test_an_empty_pending_dir_alongside_an_orphan_still_drains(drainkit):
    """Guards the glob subtlety.

    Without nullglob an unmatched glob stays literal, so testing only the first
    array element sees the literal pattern whenever pending_extractions/ is the
    empty one — and reports "no work" while an orphan sits in the next
    directory. Creating the empty dir makes that ordering explicit.
    """
    _install_plugin(drainkit)
    (drainkit.workspace / ".multiplai" / "data" / "pending_extractions").mkdir(
        parents=True, exist_ok=True
    )
    _strand_marker(drainkit)

    d = _run(drainkit, "--shell", "-c", "true")

    assert d.launch.status == 0, d.launch.output
    assert d.ran


def test_both_queues_empty_means_no_drain(drainkit):
    """The saving must survive the widened check: empty dirs are not work."""
    _install_plugin(drainkit)
    for name in ("pending_extractions", "processing_extractions"):
        (drainkit.workspace / ".multiplai" / "data" / name).mkdir(
            parents=True, exist_ok=True
        )

    d = _run(drainkit, "--shell", "-c", "true")

    assert d.launch.status == 0, d.launch.output
    assert not d.ran


def test_host_launches_without_consulting_plugin_state(drainkit):
    """The trust-boundary pin: the host must not read installed_plugins.json or
    the plugin cache — that state is writable from inside every container, and
    resolving anything from it host-side is how the rejected design turned into
    a container→host execution channel.

    Behaviourally: with a marker queued and NO plugin installed at all, the
    drain container still launches. A marker can only exist because the plugin
    wrote one, so marker-presence is the host's whole test; whether the plugin
    is (still) installed is the container's question to answer.
    """
    _queue_marker(drainkit)
    # Deliberately no _install_plugin: no manifest, no cache.

    d = _run(drainkit, "--shell", "-c", "true")

    assert d.launch.status == 0, d.launch.output
    assert d.ran


# --- the drain container's contract ------------------------------------------


def test_drain_container_mounts_exactly_what_it_needs(drainkit):
    """Workspace (queue in, diary out), config dir (manifest + cache +
    transcripts), and the same renaming credentials bind a session gets —
    pointing at the LIVE host file, so in-place OAuth refreshes are seen and
    nothing is ever copied. Nothing else: no kit checkout, no kit venv, no SSH
    agent, no CLI dir."""
    _install_plugin(drainkit)
    _queue_marker(drainkit)
    creds = _creds(drainkit)

    d = _run(drainkit, "--shell", "-c", "true")

    dotfiles = drainkit.root / "dotfiles"
    assert sorted(d.values_after("-v")) == sorted([
        f"{drainkit.workspace}:{drainkit.workspace}",
        f"{dotfiles}:{dotfiles}",
        f"{creds}:{dotfiles}/.credentials.json",
    ])


def test_drain_container_env_is_exactly_workspace_and_config_dir(drainkit):
    """The env allowlist is the API-key/secrets pin. A session container gets
    the whole .env sweep plus every CLAUDE_PLUGIN_OPTION_*; the drain container
    gets two non-secret paths, passed by VALUE — so even a user who sets
    CLAUDE_PLUGIN_OPTION_anthropic_api_key in .env cannot leak it (or any other
    secret) into the drain, which therefore always runs on the OAuth-backed
    Agent SDK and never bills an API key."""
    _install_plugin(drainkit)
    _queue_marker(drainkit)
    drainkit.append_env(
        'CLAUDE_PLUGIN_OPTION_anthropic_api_key="sk-ant-from-env-file"\n'
    )

    d = _run(drainkit, "--shell", "-c", "true")

    dotfiles = drainkit.root / "dotfiles"
    assert sorted(d.values_after("-e")) == sorted([
        f"WORKSPACE={drainkit.workspace}",
        f"CLAUDE_CONFIG_DIR={dotfiles}",
    ])
    # And no secret value reaches the drain's argv in any position. The .env
    # fixture carries GH_TOKEN and TAVILY_API_KEY; both must stay host-side.
    joined = "\0".join(d.argv)
    for leak in ("anthropic_api_key", "sk-ant-from-env-file",
                 "GH_TOKEN", "token-from-env-file", "TAVILY", "tvly-from-file"):
        assert leak not in joined, f"{leak!r} leaked into the drain container"


def test_drain_container_is_hardened_like_a_session(drainkit):
    _install_plugin(drainkit)
    _queue_marker(drainkit)

    d = _run(drainkit, "--shell", "-c", "true")

    assert "--cap-drop=ALL" in d.argv
    assert "--security-opt=no-new-privileges" in d.argv


def test_drain_never_changes_the_exit_status(drainkit):
    """`exit $DOCKER_STATUS` is documented behaviour. Even a drain launch that
    fails outright must not touch what the launcher reports about the session:
    container exits 7, drain docker run exits 42, claude.sh says 7."""
    _install_plugin(drainkit)
    _queue_marker(drainkit)

    d = _run(
        drainkit, "--shell", "-c", "true",
        MAIN_RUN_STATUS="7", DRAIN_RUN_STATUS="42",
    )

    assert d.ran, "precondition: the failing drain run must actually be attempted"
    assert d.launch.status == 7, d.launch.output


def test_drain_prints_nothing_on_the_happy_path(drainkit):
    _install_plugin(drainkit)
    _queue_marker(drainkit)

    d = _run(drainkit, "--shell", "-c", "true")

    assert "drain" not in d.launch.output.lower()
    assert "extract" not in d.launch.output.lower()


# --- the in-container command -------------------------------------------------
#
# The payload recorded on the drain argv is exactly what the container's bash
# would execute against the same mounted paths, so running it locally with the
# container's two env vars pointed at the fixture tree is a faithful test of
# in-container resolution. A stub `uv` records what would be exec'd.


def _run_payload(kit, payload, path_dirs, uv_argv_out):
    # Absolute interpreter path: with a sanitized PATH in env, execvpe would
    # otherwise fail to find bash itself.
    return subprocess.run(
        ["/bin/bash", "-c", payload],
        env={
            "PATH": ":".join(str(p) for p in path_dirs),
            "CLAUDE_CONFIG_DIR": str(kit.root / "dotfiles"),
            "WORKSPACE": str(kit.workspace),
            "UV_ARGV_OUT": str(uv_argv_out),
        },
        capture_output=True,
        text=True,
    )


@pytest.fixture
def payloadkit(drainkit, tmp_path):
    """drainkit plus a recorded payload and an isolated uv-stub PATH dir."""
    _queue_marker(drainkit)
    d = _run(drainkit, "--shell", "-c", "true")
    drainkit.payload = d.payload

    payload_bin = tmp_path / "payload-bin"
    payload_bin.mkdir()
    (payload_bin / "uv").write_text(UV_STUB)
    (payload_bin / "uv").chmod(0o755)
    drainkit.payload_bin = payload_bin
    drainkit.uv_argv_out = tmp_path / "uv_argv.txt"
    drainkit.uv_argv_out.write_text("")
    return drainkit


def test_container_resolution_follows_the_manifest(payloadkit):
    """Manifest installPath only — no newest-in-cache fallback, so a rolled-back
    plugin can never have a newer cached version run against its queue. The
    drain runs with --wait: PID 1 exiting tears down a --rm container, and
    without --wait the detached extraction children would die with it —
    reintroducing exactly the teardown this feature exists to survive.

    It also runs with --project pointed at the plugin's scripts/ directory —
    the member dir, which is the only form that resolves both in-repo and on
    an installed plugin (a copy of the plugin subtree, no workspace root above
    it). That directory's pyproject.toml is what provides multiplai_core; this
    assertion previously pinned the opposite, and the drain died on import
    every run without anything logging it."""
    install_path = _install_plugin(payloadkit)
    # A newer cached version that the manifest does NOT point at must lose.
    newer = (
        payloadkit.root / "dotfiles" / "plugins" / "cache" / "multiplai" /
        "multiplai-context" / "0.12.0" / "scripts"
    )
    newer.mkdir(parents=True)
    (newer / "drain_extractions.py").write_text("# newer, NOT installed\n")

    proc = _run_payload(
        payloadkit, payloadkit.payload,
        [payloadkit.payload_bin, "/usr/bin", "/bin"],
        payloadkit.uv_argv_out,
    )

    assert proc.returncode == 0, proc.stderr
    argv = payloadkit.uv_argv_out.read_text().splitlines()
    assert argv == [
        "run",
        "--project",
        str(install_path / "scripts"),
        str(install_path / "scripts" / "drain_extractions.py"),
        "--wait",
        "--data-dir",
        str(payloadkit.workspace / ".multiplai" / "data"),
    ]


def test_plugin_absent_is_silent_in_the_container(payloadkit):
    """Vanilla Claude Code with no multiplai-context installed: the container
    finds no manifest, exits 0, runs nothing, says nothing."""
    proc = _run_payload(
        payloadkit, payloadkit.payload,
        [payloadkit.payload_bin, "/usr/bin", "/bin"],
        payloadkit.uv_argv_out,
    )

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "" and proc.stderr == ""
    assert payloadkit.uv_argv_out.read_text() == ""


def test_older_plugin_without_the_script_is_silent(payloadkit):
    """The kit can be updated ahead of the plugin. Degrade, don't fail."""
    _install_plugin(payloadkit, version="0.10.0", with_script=False)

    proc = _run_payload(
        payloadkit, payloadkit.payload,
        [payloadkit.payload_bin, "/usr/bin", "/bin"],
        payloadkit.uv_argv_out,
    )

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "" and proc.stderr == ""
    assert payloadkit.uv_argv_out.read_text() == ""


def test_missing_uv_in_the_image_is_silent(payloadkit):
    """PATH here is ONLY the payload bin dir minus its uv stub — `command -v uv`
    genuinely fails, unlike a PATH that appends the inherited environment's.
    (The image bakes uv, so this is defence in depth for a stripped image.)"""
    _install_plugin(payloadkit)
    (payloadkit.payload_bin / "uv").unlink()
    # jq must still resolve for the guard under test to be uv's, not jq's.
    jq = payloadkit.payload_bin / "jq"
    jq.write_text('#!/bin/bash\nexec /usr/bin/jq "$@"\n')
    jq.chmod(0o755)

    proc = _run_payload(
        payloadkit, payloadkit.payload, [payloadkit.payload_bin],
        payloadkit.uv_argv_out,
    )

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "" and proc.stderr == ""
    assert payloadkit.uv_argv_out.read_text() == ""


# --- host-side guard preconditions --------------------------------------------
#
# Unreachable through a full launch (container mode refuses to start without
# docker and the image), so these run the shipped drain block directly under a
# PATH that actually lacks what the guard checks for.


def _drain_block():
    source = LAUNCHER_SOURCE.read_text()
    tail = source.split("# --- Post-exit extraction drain ---", 1)[1]
    return tail.split("# --- Run, with the hub adoption take-back loop ---", 1)[0]


def _sanitized_bin(tmp_path, *tools):
    """A PATH dir holding ONLY the named tools (symlinked from the real ones).

    The whole point: nothing appends the inherited environment's PATH, so a
    tool absent from this dir is genuinely absent — unlike the old missing-uv
    test, which "removed" the stub while real uv stayed reachable.
    """
    b = tmp_path / "sanitized-bin"
    b.mkdir()
    for tool in tools:
        real = shutil.which(tool)
        assert real, f"test needs {tool} on the real PATH"
        (b / tool).symlink_to(real)
    return b


def _run_drain_block(tmp_path, sanitized_bin):
    ws = tmp_path / "gws"
    pending = ws / ".multiplai" / "data" / "pending_extractions"
    pending.mkdir(parents=True)
    (pending / "s.json").write_text("{}")
    creds = tmp_path / "gcreds.json"
    creds.write_text("{}")

    script = "\n".join([
        f'WORKSPACE="{ws}"',
        f'DOTFILES_DIR="{tmp_path}/gdotfiles"',
        'IMAGE_NAME="claude-multiplai:local"',
        f'CREDS_FILE="{creds}"',
        _drain_block(),
        "post_exit_drain",
    ])
    # Absolute interpreter path: with a sanitized PATH in env, execvpe would
    # otherwise fail to find bash itself.
    return subprocess.run(
        ["/bin/bash", "-c", script],
        env={"PATH": str(sanitized_bin)},
        capture_output=True,
        text=True,
    )


def test_missing_docker_is_silent(tmp_path):
    """PATH holds only `cat` (the heredoc needs it): `command -v docker`
    genuinely fails, so what runs here is the real no-docker path — unlike the
    old missing-uv test, whose "removed" stub left real uv reachable and the
    guard untested. The pin is the behaviour (silent no-op, status 0), which
    the `command -v` guard and the redirected-`|| return 0` docker calls
    provide in two layers; stripping the silencing from either surfaces
    `docker: command not found` here."""
    proc = _run_drain_block(tmp_path, _sanitized_bin(tmp_path, "cat"))

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "" and proc.stderr == ""


def test_missing_image_is_silent(tmp_path):
    """`docker image inspect` failing must be a silent no-op, and no `docker
    run` may follow it."""
    sanitized = _sanitized_bin(tmp_path, "cat")
    ran_marker = tmp_path / "drain-run-attempted"
    docker = sanitized / "docker"
    docker.write_text(
        "#!/bin/bash\n"
        'case "$1" in\n'
        "    image) exit 1 ;;\n"
        f'    run) : > "{ran_marker}"; exit 0 ;;\n'
        "esac\n"
        "exit 0\n"
    )
    docker.chmod(0o755)

    proc = _run_drain_block(tmp_path, sanitized)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "" and proc.stderr == ""
    assert not ran_marker.exists(), "docker run was attempted despite no image"


# --- source shape -------------------------------------------------------------


def test_launcher_adds_no_second_prompt():
    """The hub take-back guards on `[ -t 0 ]`; a second interactive read in the
    post-exit path would swallow its input. Matches `read` only in command
    position so a comment mentioning the word cannot trip it."""
    assert re.search(r"(?m)^\s*read\b", _drain_block()) is None
