"""Pins the post-exit extraction drain in `claude.sh`.

The multiplai-context plugin defers extraction to a marker file, and until this
landed the only thing that ever drained the queue was the *next* `SessionStart`
— so the last tab of the day left its diary entry unwritten until the next
session opened, possibly days later. `claude.sh` now runs the plugin's
`drain_extractions.py` on the host once the container has exited.

What is tested here is the launcher's **decision logic**, with a stub `uv`
first on `PATH` recording the argv and environment it was handed. That is the
same technique as `test_claude_sh_env.py`, and for the same reason: whether the
drain then actually extracts anything depends on a real container having
written a real marker and on host OAuth, neither of which exists in CI.

The invariants that matter, and that this file breaks if a future edit does:

* the drain never changes `claude.sh`'s exit status;
* it launches only when a marker is actually queued;
* it is silent — no output on any path, and no prompt (a second `read` here
  would fight the hub take-back's);
* it hands the child `WORKSPACE` (without which the diary silently lands in
  `~/.multiplai/` instead of the workspace) and a `CLAUDE_CONFIG_DIR` whose
  `.credentials.json` resolves to the live host credentials file;
* it never copies the credentials file.
"""

import json
import time
from pathlib import Path

import pytest

from test_claude_sh_env import (  # noqa: F401 — `kit` is a fixture
    BASE_ENV_FILE,
    kit,
)

UV_STUB = """\
#!/bin/bash
printf '%s\\n' "$@" > "$UV_ARGV_OUT"
env > "$UV_ENV_OUT"
exit 0
"""


class Drain:
    """What the stub `uv` saw, or nothing if it was never invoked."""

    def __init__(self, argv, env, launch):
        self.argv = argv
        self.env = env
        self.launch = launch

    @property
    def ran(self):
        return bool(self.argv)

    def flag(self, name):
        """The value following `--name` in the drain argv, or None."""
        if name in self.argv:
            i = self.argv.index(name)
            if i + 1 < len(self.argv):
                return self.argv[i + 1]
        return None


def _install_uv_stub(kit):
    stub = kit.stub_dir / "uv"
    stub.write_text(UV_STUB)
    stub.chmod(0o755)
    kit.uv_argv_out = kit.root / "uv_argv.txt"
    kit.uv_env_out = kit.root / "uv_env.txt"
    kit.uv_argv_out.write_text("")
    kit.uv_env_out.write_text("")


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


def _creds(kit):
    """The host credentials file the launcher mounts into the container."""
    d = kit.home / ".claude-container"
    d.mkdir(parents=True, exist_ok=True)
    f = d / "credentials.json"
    f.write_text('{"token": "live"}')
    return f


def _run(kit, *args, expect_drain=True, **env):
    """Launch, then wait for the detached drain child to record itself.

    The drain is deliberately backgrounded, so `claude.sh` returns before the
    stub `uv` has written anything — without the poll this races. Absence is
    asserted on a short budget: the child is spawned *before* the launcher
    exits, so if it were coming it would already be here.
    """
    launch = kit.launch(
        *args,
        UV_ARGV_OUT=str(kit.uv_argv_out),
        UV_ENV_OUT=str(kit.uv_env_out),
        **env,
    )

    deadline = time.monotonic() + (5.0 if expect_drain else 0.75)
    while time.monotonic() < deadline:
        if kit.uv_argv_out.read_text().strip() and kit.uv_env_out.read_text().strip():
            break
        time.sleep(0.02)

    argv = [ln for ln in kit.uv_argv_out.read_text().splitlines() if ln]
    uv_env = {}
    for line in kit.uv_env_out.read_text().splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            uv_env[k] = v
    return Drain(argv, uv_env, launch)


@pytest.fixture
def drainkit(kit):
    _install_uv_stub(kit)
    _creds(kit)
    return kit


def test_drain_runs_after_the_container_exits(drainkit):
    install_path = _install_plugin(drainkit)
    _queue_marker(drainkit)

    d = _run(drainkit, "--shell", "-c", "true")

    assert d.launch.status == 0, d.launch.output
    assert d.ran, "a marker was queued but the drain never launched"
    assert d.argv == [
        "run",
        "--no-project",
        str(install_path / "scripts" / "drain_extractions.py"),
        "--data-dir",
        str(drainkit.workspace / ".multiplai" / "data"),
    ]


def test_no_marker_means_no_drain(drainkit):
    """A launcher that spawns a uv process on every exit for nothing is a tax
    on every session; the queue check is what keeps it free."""
    _install_plugin(drainkit)
    # No marker queued.

    d = _run(drainkit, "--shell", "-c", "true", expect_drain=False)

    assert d.launch.status == 0, d.launch.output
    assert not d.ran


def test_plugin_absent_means_no_drain(drainkit):
    """Vanilla Claude Code with no multiplai-context installed: nothing to run,
    and the launcher must not complain about it."""
    _queue_marker(drainkit)

    d = _run(drainkit, "--shell", "-c", "true", expect_drain=False)

    assert d.launch.status == 0, d.launch.output
    assert not d.ran


def test_older_plugin_without_the_script_means_no_drain(drainkit):
    """The kit can be updated ahead of the plugin. Degrade, don't fail."""
    _install_plugin(drainkit, version="0.10.0", with_script=False)
    _queue_marker(drainkit)

    d = _run(drainkit, "--shell", "-c", "true", expect_drain=False)

    assert d.launch.status == 0, d.launch.output
    assert not d.ran


def test_missing_uv_is_silent(drainkit):
    """No uv on the host is a supported configuration — it just drains at the
    next SessionStart, as it always did."""
    _install_plugin(drainkit)
    _queue_marker(drainkit)
    (drainkit.stub_dir / "uv").unlink()

    d = _run(drainkit, "--shell", "-c", "true", expect_drain=False)

    assert d.launch.status == 0, d.launch.output
    assert not d.ran
    assert "uv" not in d.launch.output.lower() or "drain" not in d.launch.output.lower()


def test_drain_is_handed_the_workspace(drainkit):
    """Without WORKSPACE the plugin resolves diary/learnings to ~/.multiplai/
    and the extraction lands somewhere nobody looks. --data-dir fixes the
    queue's location, not the diary's."""
    _install_plugin(drainkit)
    _queue_marker(drainkit)

    d = _run(drainkit, "--shell", "-c", "true")

    assert d.env.get("WORKSPACE") == str(drainkit.workspace)


def test_drain_points_at_the_live_credentials_via_a_symlink(drainkit):
    """Claude Code reads $CLAUDE_CONFIG_DIR/.credentials.json; the host file is
    credentials.json. Bridge with a symlink — never a copy, because the CLI
    refreshes the token in place and a copy goes stale, then fails auth."""
    _install_plugin(drainkit)
    _queue_marker(drainkit)
    creds = _creds(drainkit)

    d = _run(drainkit, "--shell", "-c", "true")

    config_dir = Path(d.env["CLAUDE_CONFIG_DIR"])
    link = config_dir / ".credentials.json"
    assert link.is_symlink(), f"{link} must be a symlink, not a copy"
    assert link.resolve() == creds.resolve()
    assert link.read_text() == creds.read_text()

    # And it tracks in-place refreshes, which a copy would not.
    creds.write_text('{"token": "refreshed"}')
    assert link.read_text() == '{"token": "refreshed"}'


def test_drain_does_not_get_an_api_key(drainkit):
    """Its absence is what keeps create_client() on the OAuth-backed Agent SDK
    instead of billing a separate Anthropic API key."""
    _install_plugin(drainkit)
    _queue_marker(drainkit)

    d = _run(drainkit, "--shell", "-c", "true")

    assert "CLAUDE_PLUGIN_OPTION_anthropic_api_key" not in d.env


def test_drain_never_changes_the_exit_status(drainkit):
    """`exit $DOCKER_STATUS` is documented behaviour. Even a drain that fails
    outright must not touch it."""
    _install_plugin(drainkit)
    _queue_marker(drainkit)
    (drainkit.stub_dir / "uv").write_text("#!/bin/bash\nexit 42\n")
    (drainkit.stub_dir / "uv").chmod(0o755)

    # Stub docker reports the container's own failure status.
    failing_docker = (
        "#!/bin/bash\n"
        'case "$1" in\n'
        "  image) exit 0 ;;\n"
        "  run)\n"
        '    for a in "$@"; do [ "$a" = "--entrypoint" ] && exit 0; done\n'
        '    printf "%s\\n" "$@" > "$DOCKER_ARGV_OUT"\n'
        "    env > \"$DOCKER_ENV_OUT\"\n"
        "    exit 7 ;;\n"
        "esac\n"
        "exit 0\n"
    )
    (drainkit.stub_dir / "docker").write_text(failing_docker)
    (drainkit.stub_dir / "docker").chmod(0o755)

    d = _run(drainkit, "--shell", "-c", "true")

    assert d.launch.status == 7, d.launch.output


def test_drain_prints_nothing_on_the_happy_path(drainkit):
    _install_plugin(drainkit)
    _queue_marker(drainkit)

    d = _run(drainkit, "--shell", "-c", "true")

    assert "drain" not in d.launch.output.lower()
    assert "extract" not in d.launch.output.lower()


def test_launcher_adds_no_second_prompt(drainkit):
    """The hub take-back guards on `[ -t 0 ]`; a second interactive read in the
    post-exit path would swallow its input."""
    source = (Path(__file__).resolve().parents[2] / "claude.sh").read_text()
    tail = source.split("# --- Post-exit extraction drain ---", 1)[1]
    drain_block = tail.split("# --- Run, with the hub adoption take-back loop ---", 1)[0]
    assert "read " not in drain_block and "read\n" not in drain_block


def test_drain_block_does_not_copy_credentials(drainkit):
    source = (Path(__file__).resolve().parents[2] / "claude.sh").read_text()
    tail = source.split("# --- Post-exit extraction drain ---", 1)[1]
    drain_block = tail.split("# --- Run, with the hub adoption take-back loop ---", 1)[0]
    assert "cp " not in drain_block, "credentials must be symlinked, never copied"
