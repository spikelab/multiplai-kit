"""Pins what `claude.sh --pi` launches, what it refuses to launch, and the pi and
Codex state every container session mounts.

`--pi` replaces the container's command. Every container session — `--pi` or
not — mounts three host folders: the pi install (`~/.pi-cli`), one pi config
(`~/.pi`) and the Codex home (`~/.codex`). Both are easy to break silently: a
command left as `claude` still starts a working session, and a missing `~/.pi`
mount still starts a working *pi* session — one that quietly writes its
credentials and installed packages into a `--rm` container and loses them on
exit. Neither failure announces itself, so they get asserted here.

The refusals matter as much as the launch. pi ships no permission system, so the
container is the only boundary there is; `--pi --local` or `--pi` with no Docker
must be errors rather than a quiet downgrade to running unsandboxed on the host.

Same harness as `test_claude_sh_env`: a stub `docker` first on `PATH` records the
final `docker run` argv, so no daemon and no image are needed.
"""

import json
import shutil
import subprocess

import pytest

from test_claude_sh_crossplatform import _driver_launch
from test_claude_sh_docker_state import _path_without_docker
from test_claude_sh_env import kit  # noqa: F401 — `kit` is a fixture

from _kitpaths import KIT_ROOT

PI_HOME = "/home/agent/.pi"
PI_CLI = "/home/agent/.pi-cli"
CODEX_HOME = "/home/agent/.codex"


def _mounts(argv):
    """Every `-v` value in the recorded argv."""
    return [argv[i + 1] for i, a in enumerate(argv) if a == "-v" and i + 1 < len(argv)]


def _mount_for(argv, container_path):
    """The host side of the mount landing on `container_path`, or None."""
    for m in _mounts(argv):
        if m.rsplit(":", 1)[-1] == container_path:
            return m.rsplit(":", 1)[0]
    return None


# --- what gets launched ------------------------------------------------------


def test_pi_replaces_the_container_command(kit):
    result = kit.launch("--pi")
    assert result.status == 0, result.output
    assert any(a.endswith("scripts/pi-bootstrap.sh") for a in result.argv), result.argv
    # The bootstrap execs pi; `claude` must not also be on the command line.
    assert "claude" not in result.argv
    assert "--dangerously-skip-permissions" not in result.argv


def test_pi_sh_wrapper_matches_claude_sh_pi(kit):
    """`./pi.sh` must resolve to the same launch as `./claude.sh --pi`.

    The wrapper exists so there is exactly one launcher; a copy that drifted
    into its own docker invocation would defeat the point.
    """
    shutil.copy(KIT_ROOT / "pi.sh", kit.root / "pi.sh")
    (kit.root / "pi.sh").chmod(0o755)

    via_flag = kit.launch("--pi")

    kit.argv_out.write_text("")
    env = {
        "PATH": f"{kit.stub_dir}:/usr/bin:/bin",
        "HOME": str(kit.home),
        "TERM": "xterm",
        "DOCKER_ARGV_OUT": str(kit.argv_out),
        "DOCKER_ENV_OUT": str(kit.env_out),
        "CLAUDE_ENV_OUT": str(kit.bare_env_out),
    }
    proc = subprocess.run(
        [str(kit.root / "pi.sh")], env=env, capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    via_wrapper = kit.argv_out.read_text().splitlines()

    # Container names carry a timestamp, so compare the parts that must match.
    assert _mount_for(via_wrapper, PI_HOME) == _mount_for(via_flag.argv, PI_HOME)
    assert [a for a in via_wrapper if a.endswith("pi-bootstrap.sh")] == [
        a for a in via_flag.argv if a.endswith("pi-bootstrap.sh")
    ]


# --- the mount that makes the pi config persist ------------------------------


def test_pi_config_is_mounted_from_the_host(kit):
    """Without this mount, credentials and installed packages die with the container."""
    result = kit.launch("--pi")
    host = _mount_for(result.argv, PI_HOME)
    assert host == str(kit.home / ".claude-container/pi/default"), _mounts(result.argv)


@pytest.mark.parametrize(
    "flags",
    [("--pi-profile", "x"), ("--pi-profile=x",), ("--pi", "--pi-profile", "default")],
)
def test_pi_profile_flag_is_removed(kit, flags):
    """There is one pi config; the old flag fails loudly rather than reaching pi."""
    result = kit.launch(*flags)
    assert result.status != 0
    assert "--pi-profile was removed" in result.output
    assert "docs/pi.md" in result.output
    assert result.argv == []


# --- every container session carries pi and Codex --------------------------
#
# `pi` and `codex` are tools a Claude session calls, not only things `--pi`
# launches. Their installs and their logins must survive a `--rm` container in
# every mode, or the weekly update and the ChatGPT login are redone every launch.


def _assert_pi_and_codex_mounts(kit, argv):
    cc = kit.home / ".claude-container"
    assert _mount_for(argv, PI_CLI) == str(cc / "pi-cli"), _mounts(argv)
    assert _mount_for(argv, PI_HOME) == str(cc / "pi" / "default"), _mounts(argv)
    assert _mount_for(argv, CODEX_HOME) == str(cc / "codex"), _mounts(argv)
    # Created before the launch: a bind mount of a missing host path makes
    # Docker create it root-owned, which the agent user cannot write to.
    for d in ("pi-cli", "pi/default", "codex"):
        assert (cc / d).is_dir(), d


def test_plain_launch_mounts_pi_and_codex_state(kit):
    """(a) A plain claude launch mounts all three, with `pi/default` at `~/.pi`."""
    result = kit.launch()
    assert result.status == 0, result.output
    assert "claude" in result.argv, "a plain launch must still run claude"
    _assert_pi_and_codex_mounts(kit, result.argv)


def test_shell_launch_mounts_pi_and_codex_state(kit):
    result = kit.launch("--shell", "-c", "true")
    assert result.status == 0, result.output
    _assert_pi_and_codex_mounts(kit, result.argv)


def test_driver_launch_mounts_pi_and_codex_state(kit):
    """The hub driver composes its own `docker run`; it must carry them too."""
    result = _driver_launch(kit)
    assert result.status == 0, result.output
    assert "--name" in result.argv
    assert result.argv[result.argv.index("--name") + 1].startswith("claude-drv-")
    _assert_pi_and_codex_mounts(kit, result.argv)


@pytest.mark.parametrize("flags", [(), ("--pi",)])
@pytest.mark.parametrize("source", ["shell", ".env"])
def test_a_leftover_pi_profile_variable_changes_no_mount(kit, flags, source):
    """A MULTIPLAI_PI_PROFILE from the old profile selection mounts `pi/default` all the same."""
    if source == ".env":
        kit.append_env('MULTIPLAI_PI_PROFILE="x"\n')
        result = kit.launch(*flags)
    else:
        result = kit.launch(*flags, MULTIPLAI_PI_PROFILE="x")
    assert result.status == 0, result.output
    _assert_pi_and_codex_mounts(kit, result.argv)
    assert not (kit.home / ".claude-container" / "pi" / "x").exists()


def test_git_profile_changes_no_pi_mount(kit):
    """(d) `--profile work` changes no pi mount.

    pi is never tied to `--profile`: that flag picks a git identity and a GitHub
    token.
    """
    kit.write_profile("work", 'GIT_AUTHOR_NAME="Work Name"\n')
    plain = kit.launch()
    work = kit.launch("--profile", "work")
    assert work.status == 0, work.output
    assert work.resolved("GIT_AUTHOR_NAME") == "Work Name"
    for path in (PI_CLI, PI_HOME, CODEX_HOME):
        assert _mount_for(work.argv, path) == _mount_for(plain.argv, path), path
    _assert_pi_and_codex_mounts(kit, work.argv)


# --- the git identity axis stays independent ---------------------------------


def test_pi_and_git_profile_compose(kit):
    """`--pi --profile work` takes work's git identity and still mounts `pi/default`.

    A change that tied the pi config to `--profile` would make `--profile work`
    silently mount a pi config named `work`.
    """
    kit.write_profile("work", 'GIT_AUTHOR_NAME="Work Name"\n')
    result = kit.launch("--profile", "work", "--pi")
    assert result.status == 0, result.output
    assert _mount_for(result.argv, PI_HOME) == str(kit.home / ".claude-container/pi/default")
    assert result.resolved("GIT_AUTHOR_NAME") == "Work Name"


# --- refusals ----------------------------------------------------------------


@pytest.mark.parametrize("flags", [("--pi", "--local"), ("--local", "--pi")])
def test_pi_refuses_local_mode(kit, flags):
    """Order-independent: last-flag-wins would run pi unsandboxed on the host."""
    result = kit.launch(*flags)
    assert result.status != 0
    assert "--pi cannot combine with --local" in result.output
    assert result.argv == []


def test_pi_refuses_shell_mode(kit):
    result = kit.launch("--pi", "--shell")
    assert result.status != 0
    assert "--pi cannot combine with --shell" in result.output


def test_pi_refuses_claude_only_flags(kit):
    """`--plugin-dir`/`--add-dir` mean nothing to pi and would be passed verbatim."""
    result = kit.launch("--pi", "--add-dir", "/tmp")
    assert result.status != 0
    assert "claude-only" in result.output


def test_pi_refuses_without_docker(kit, tmp_path):
    """No bare rung for pi: the container is the whole permission boundary.

    The PATH must carry no `docker` at all, not merely a stub-free prefix: on
    a runner with Docker installed, `/usr/bin/docker` further down would turn
    this into the missing-image case instead.
    """
    path = _path_without_docker(kit, tmp_path)

    result = kit.launch("--pi", PATH=path)

    assert result.status != 0
    assert "requires Docker" in result.output


def test_pi_refuses_driver_mode(kit):
    result = kit.launch("driver", "--pi")
    assert result.status != 0


# --- the in-container bootstrap ----------------------------------------------
#
# `scripts/pi-bootstrap.sh` runs inside the container as `--pi`'s command. The
# container entrypoint now owns installing and updating pi, so the bootstrap
# only seeds the config, installs its packages and execs the `pi` on PATH. It
# is run here directly, against the real templates, with a stub `pi` and a stub
# `npm` that fails the test if anything still calls it.

PI_STUB = """\
#!/bin/bash
printf '%s\\n' "$*" >> "$PI_CALLS"
exit 0
"""

NPM_STUB = """\
#!/bin/bash
echo "npm $*" >> "$NPM_CALLS"
exit 1
"""


def _bootstrap(tmp_path, *args, with_pi=True, **env_extra):
    stubs = tmp_path / "bootstrap-bin"
    stubs.mkdir(exist_ok=True)
    if with_pi:
        (stubs / "pi").write_text(PI_STUB)
        (stubs / "pi").chmod(0o755)
    (stubs / "npm").write_text(NPM_STUB)
    (stubs / "npm").chmod(0o755)
    home = tmp_path / "agent-home"
    home.mkdir(exist_ok=True)
    pi_calls = tmp_path / "pi-calls.txt"
    npm_calls = tmp_path / "npm-calls.txt"
    env = {
        "PATH": f"{stubs}:/usr/bin:/bin",
        "HOME": str(home),
        "CLAUDE_MULTIPLAI_HOME": str(KIT_ROOT),
        "PI_CALLS": str(pi_calls),
        "NPM_CALLS": str(npm_calls),
    }
    env.update({k: v for k, v in env_extra.items() if v is not None})
    proc = subprocess.run(
        ["bash", str(KIT_ROOT / "scripts" / "pi-bootstrap.sh"), *args],
        env=env, capture_output=True, text=True,
    )
    calls = pi_calls.read_text().splitlines() if pi_calls.exists() else []
    npm = npm_calls.read_text().splitlines() if npm_calls.exists() else []
    return proc, home, calls, npm


def test_missing_openrouter_key_warns_and_still_launches(tmp_path):
    """(e) One config holds several providers; a missing key disables only its own."""
    proc, home, calls, npm = _bootstrap(
        tmp_path, "-p", "hello", DEEPSEEK_API_KEY="sk-deepseek-secret"
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "OPENROUTER_API_KEY" in proc.stderr
    assert "DEEPSEEK_API_KEY" not in proc.stderr
    assert "sk-deepseek-secret" not in proc.stdout + proc.stderr
    # The last pi call is the exec, with the passthrough args intact.
    assert calls and calls[-1] == "-p hello", calls
    assert (home / ".pi" / "agent" / "models.json").is_file()


def test_bootstrap_seeds_the_default_template(tmp_path):
    proc, home, calls, _ = _bootstrap(tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    seeded = json.loads((home / ".pi" / "agent" / "models.json").read_text())
    assert sorted(seeded["providers"]) == ["deepseek", "openrouter"]


def test_bootstrap_ignores_a_leftover_pi_profile_variable(tmp_path):
    proc, home, calls, _ = _bootstrap(tmp_path, MULTIPLAI_PI_PROFILE="openrouter")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    seeded = json.loads((home / ".pi" / "agent" / "models.json").read_text())
    assert sorted(seeded["providers"]) == ["deepseek", "openrouter"]


def test_bootstrap_no_longer_installs_pi(tmp_path):
    """The entrypoint installs and updates pi; MULTIPLAI_PI_VERSION is gone."""
    proc, home, calls, npm = _bootstrap(tmp_path, MULTIPLAI_PI_VERSION="0.84.2")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert npm == []
    assert not (home / ".pi-cli").exists()
    assert "MULTIPLAI_PI_VERSION" not in (KIT_ROOT / "scripts" / "pi-bootstrap.sh").read_text()


def test_bootstrap_without_pi_on_path_names_the_cause(tmp_path):
    proc, _, _, npm = _bootstrap(tmp_path, with_pi=False)
    assert proc.returncode != 0
    assert "pi is not installed" in proc.stderr
    assert npm == []


def test_bootstrap_keeps_user_edits(tmp_path):
    """S8 in the bootstrap: only absent files are copied."""
    home = tmp_path / "agent-home"
    agent = home / ".pi" / "agent"
    agent.mkdir(parents=True)
    (agent / "settings.json").write_text('{"deviceId": "user-device"}\n')
    (agent / "auth.json").write_text('{"openai": {"type": "oauth"}}\n')

    proc, _, _, _ = _bootstrap(tmp_path)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert (agent / "settings.json").read_text() == '{"deviceId": "user-device"}\n'
    assert (agent / "auth.json").read_text() == '{"openai": {"type": "oauth"}}\n'
    assert (agent / "models.json").is_file()


# --- seeding on the Mac, before the container starts -------------------------
#
# A plain Claude session never runs the bootstrap, so `pi` from inside it would
# find an empty ~/.pi. The launcher seeds the mounted pi config folder on the host
# with the same absent-files-only copy, from the kit's templates.


def _with_templates(kit):
    shutil.copytree(
        KIT_ROOT / "dotfiles" / "pi-profiles", kit.root / "dotfiles" / "pi-profiles"
    )
    return kit.home / ".claude-container" / "pi"


def test_plain_launch_seeds_the_default_config(kit):
    state = _with_templates(kit)
    result = kit.launch()
    assert result.status == 0, result.output

    template = kit.root / "dotfiles" / "pi-profiles"
    seeded = state / "default"
    for rel in ("agent/models.json", "agent/settings.json"):
        assert (seeded / rel).read_text() == (template / "default" / rel).read_text(), rel
    # _shared lands at the ~/.pi root, mirroring the template tree.
    assert (seeded / "web-search.json").read_text() == (
        template / "_shared" / "web-search.json"
    ).read_text()
    # Control files and docs are read by the bootstrap, never copied.
    for name in ("packages.txt", "required-env.txt", "README.md"):
        assert not (seeded / name).exists(), name


def test_seeding_never_overwrites_user_edits(kit):
    """S8: settings.json (with pi's deviceId) and auth.json edited since the last launch."""
    state = _with_templates(kit)
    agent = state / "default" / "agent"
    agent.mkdir(parents=True)
    settings = '{"deviceId": "user-device", "defaultProvider": "openai"}\n'
    auth = '{"openai": {"type": "oauth", "refresh": "kept"}}\n'
    (agent / "settings.json").write_text(settings)
    (agent / "auth.json").write_text(auth)

    first = kit.launch()
    assert first.status == 0, first.output
    assert (agent / "settings.json").read_text() == settings
    assert (agent / "auth.json").read_text() == auth
    assert (agent / "models.json").is_file(), "an absent file is still seeded"

    # A later edit to a seeded file survives the next launch too.
    (agent / "models.json").write_text('{"providers": {}}\n')
    second = kit.launch()
    assert second.status == 0, second.output
    assert (agent / "models.json").read_text() == '{"providers": {}}\n'
    assert (agent / "settings.json").read_text() == settings
    assert (agent / "auth.json").read_text() == auth


def test_a_failed_seed_copy_warns_and_still_launches(kit):
    """A copy that fails on the Mac costs only that file, never the session.

    The launcher runs under `set -e`, so an unguarded `cp` that fails would end
    the launch before `docker run`. A read-only `agent/` folder with
    `models.json` absent makes the copy fail the way a permissions slip on the
    Mac would.
    """
    state = _with_templates(kit)
    agent = state / "default" / "agent"
    agent.mkdir(parents=True)
    agent.chmod(0o555)
    try:
        result = kit.launch()
    finally:
        agent.chmod(0o755)

    assert result.status == 0, result.output
    assert "could not seed" in result.output
    assert str(agent / "models.json") in result.output
    assert not (agent / "models.json").exists()
    assert "claude" in result.argv, "docker run must still be reached"
    _assert_pi_and_codex_mounts(kit, result.argv)


# --- a nested --pi launch, from inside a container ---------------------------
#
# Inside a container `claude.sh --pi` cannot mount anything: it runs the
# bootstrap on the ~/.pi the outer launch already mounted from the Mac.

BOOTSTRAP_STUB = """\
#!/bin/bash
printf '%s\\n' "$@" > "$BOOTSTRAP_OUT"
exit 0
"""


@pytest.fixture
def nested(kit, tmp_path):
    """The kit launcher as it behaves inside a container, with a stub bootstrap."""
    marker = tmp_path / "dockerenv"
    marker.write_text("")
    launcher = kit.root / "claude.sh"
    launcher.write_text(
        launcher.read_text().replace("/nonexistent-dockerenv-marker", str(marker))
    )
    (kit.root / "scripts").mkdir()
    stub = kit.root / "scripts" / "pi-bootstrap.sh"
    stub.write_text(BOOTSTRAP_STUB)
    stub.chmod(0o755)
    kit.bootstrap_out = tmp_path / "bootstrap.txt"
    return kit


def _nested_launch(kit, *args, **env):
    if kit.bootstrap_out.exists():
        kit.bootstrap_out.unlink()
    result = kit.launch(*args, BOOTSTRAP_OUT=str(kit.bootstrap_out), **env)
    ran = kit.bootstrap_out.read_text().splitlines() if kit.bootstrap_out.exists() else None
    return result, ran


def test_nested_pi_runs_the_bootstrap_on_the_mounted_config(nested):
    result, ran = _nested_launch(nested, "--pi", "-p", "hi")
    assert result.status == 0, result.output
    assert result.argv == [], "a nested launch must not start another container"
    assert ran == ["-p", "hi"]


# --- (e) through the launcher: a missing OPENROUTER_API_KEY -------------------
#
# The launcher has no key check of its own; the warning lives in the bootstrap,
# which only runs inside the container. So the case runs both halves: the
# stub-docker launch shows `--pi` still launches with the key unset, and the
# bootstrap, handed exactly the environment that `docker run` would give the
# container, warns about that key and execs pi.


def _container_env(result):
    """The environment real docker would give the container, from the recorded argv."""
    env = {}
    argv = result.argv
    for i, a in enumerate(argv):
        if a == "-e" and i + 1 < len(argv):
            name, sep, value = argv[i + 1].partition("=")
            if sep:
                env[name] = value
            elif result.resolved(name) is not None:
                env[name] = result.resolved(name)
    return env


def test_launch_with_openrouter_key_unset_warns_and_still_launches(kit, tmp_path):
    """(e) through the stub-docker launch, then the bootstrap on what it forwards."""
    kit.append_env('DEEPSEEK_API_KEY="sk-deepseek-secret"\nOPENROUTER_API_KEY=""\n')
    result = kit.launch("--pi", "-p", "hello")
    assert result.status == 0, result.output
    assert any(a.endswith("scripts/pi-bootstrap.sh") for a in result.argv), result.argv
    forwarded = _container_env(result)
    assert forwarded.get("DEEPSEEK_API_KEY") == "sk-deepseek-secret"
    assert "OPENROUTER_API_KEY" not in forwarded, "an empty key is never forwarded"

    boot = next(i for i, a in enumerate(result.argv) if a.endswith("scripts/pi-bootstrap.sh"))
    passthrough = result.argv[boot + 1:]
    proc, _, calls, _ = _bootstrap(
        tmp_path, *passthrough,
        DEEPSEEK_API_KEY=forwarded["DEEPSEEK_API_KEY"],
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "OPENROUTER_API_KEY" in proc.stderr
    assert "DEEPSEEK_API_KEY" not in proc.stderr
    assert "sk-deepseek-secret" not in proc.stdout + proc.stderr
    assert calls and calls[-1] == "-p hello", calls
