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


# --- the mounts that make a profile persist ----------------------------------


def test_profile_state_is_mounted_from_the_host(kit):
    """Without this mount, credentials and installed packages die with the container."""
    result = kit.launch("--pi")
    host = _mount_for(result.argv, PI_HOME)
    assert host == str(kit.home / ".claude-container/pi/default"), _mounts(result.argv)


def test_cli_dir_is_shared_across_profiles(kit):
    """One pi install, many profiles — the CLI mount must not be profile-scoped."""
    default = _mount_for(kit.launch("--pi").argv, PI_CLI)
    other = _mount_for(kit.launch("--pi-profile", "kimi").argv, PI_CLI)
    assert default == other == str(kit.home / ".claude-container/pi-cli")


def test_profiles_get_separate_state_dirs(kit):
    """The isolation claim in docs/pi.md, asserted.

    pi reads its config from `homedir()/.pi/agent` with no env-var override, so
    two profiles sharing a host directory would share credentials, models and
    session history — silently.
    """
    a = _mount_for(kit.launch("--pi").argv, PI_HOME)
    b = _mount_for(kit.launch("--pi-profile", "kimi").argv, PI_HOME)
    assert a is not None and b is not None
    assert a != b
    assert a.endswith("/default") and b.endswith("/kimi")


def test_profile_name_reaches_the_bootstrap(kit):
    result = kit.launch("--pi-profile", "kimi")
    assert "MULTIPLAI_PI_PROFILE=kimi" in result.argv


# --- every container session carries pi and Codex --------------------------
#
# `pi` and `codex` are tools a Claude session calls, not only things `--pi`
# launches. Their installs and their logins must survive a `--rm` container in
# every mode, or the weekly update and the ChatGPT login are redone every launch.


def _assert_pi_and_codex_mounts(kit, argv, pi_profile="default"):
    cc = kit.home / ".claude-container"
    assert _mount_for(argv, PI_CLI) == str(cc / "pi-cli"), _mounts(argv)
    assert _mount_for(argv, PI_HOME) == str(cc / "pi" / pi_profile), _mounts(argv)
    assert _mount_for(argv, CODEX_HOME) == str(cc / "codex"), _mounts(argv)
    # Created before the launch: a bind mount of a missing host path makes
    # Docker create it root-owned, which the agent user cannot write to.
    for d in ("pi-cli", f"pi/{pi_profile}", "codex"):
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


def test_env_pi_profile_selects_the_mounted_config(kit):
    """(b) `MULTIPLAI_PI_PROFILE=x` mounts `pi/x` in a plain session."""
    result = kit.launch(MULTIPLAI_PI_PROFILE="x")
    assert result.status == 0, result.output
    _assert_pi_and_codex_mounts(kit, result.argv, pi_profile="x")


def test_env_pi_profile_from_the_env_file_selects_the_mounted_config(kit):
    kit.append_env('MULTIPLAI_PI_PROFILE="x"\n')
    result = kit.launch()
    assert result.status == 0, result.output
    _assert_pi_and_codex_mounts(kit, result.argv, pi_profile="x")


def test_pi_profile_flag_overrides_the_env_profile(kit):
    """(c) `--pi --pi-profile kimi` mounts `pi/kimi`, whatever the env names."""
    result = kit.launch("--pi", "--pi-profile", "kimi", MULTIPLAI_PI_PROFILE="x")
    assert result.status == 0, result.output
    _assert_pi_and_codex_mounts(kit, result.argv, pi_profile="kimi")
    # The computed value, never the env's, is what the container is told.
    assert "MULTIPLAI_PI_PROFILE=kimi" in result.argv
    assert "MULTIPLAI_PI_PROFILE" not in result.argv


def test_pi_without_a_profile_flag_uses_the_env_profile(kit):
    result = kit.launch("--pi", MULTIPLAI_PI_PROFILE="x")
    assert result.status == 0, result.output
    assert _mount_for(result.argv, PI_HOME) == str(kit.home / ".claude-container/pi/x")


def test_git_profile_changes_no_pi_mount(kit):
    """(d) `--profile work` changes no pi mount — not even when env.work names one.

    pi is never tied to `--profile`: that flag picks a git identity and a GitHub
    token. A pi profile named in env.work is ignored for the mount.
    """
    kit.write_profile(
        "work", 'GIT_AUTHOR_NAME="Work Name"\nMULTIPLAI_PI_PROFILE="work"\n'
    )
    plain = kit.launch()
    work = kit.launch("--profile", "work")
    assert work.status == 0, work.output
    assert work.resolved("GIT_AUTHOR_NAME") == "Work Name"
    for path in (PI_CLI, PI_HOME, CODEX_HOME):
        assert _mount_for(work.argv, path) == _mount_for(plain.argv, path), path
    _assert_pi_and_codex_mounts(kit, work.argv)
    assert "MULTIPLAI_PI_PROFILE=default" in work.argv


@pytest.mark.parametrize("bad", ["../escape", "a/b", ".hidden", "with space", "_shared"])
def test_env_pi_profile_name_is_validated(kit, bad):
    """The env value becomes a host directory and a mount target, same as the flag."""
    result = kit.launch(MULTIPLAI_PI_PROFILE=bad)
    assert result.status != 0, f"accepted profile name {bad!r}"
    assert result.argv == []


# --- the git identity axis stays independent ---------------------------------


def test_pi_profile_and_git_profile_compose(kit):
    """`--profile` picks a git identity, `--pi-profile` a model config.

    Two different things share the word "profile"; a change that collapsed them
    would make `--profile work` silently pick a pi profile named `work`.
    """
    kit.write_profile("work", 'GIT_AUTHOR_NAME="Work Name"\n')
    result = kit.launch("--profile", "work", "--pi")
    assert result.status == 0, result.output
    pi_home = _mount_for(result.argv, PI_HOME)
    assert pi_home is not None and pi_home.endswith("/default")
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


@pytest.mark.parametrize(
    "bad", ["../escape", "a/b", "", ".hidden", "with space", "_shared"]
)
def test_pi_profile_name_is_validated(kit, bad):
    """The name becomes a host directory and a mount target.

    `_shared` is in the list because it is a real directory under
    dotfiles/pi-profiles/ holding the package list every profile gets. It is not
    a profile, and selecting it would mount a state dir named after it.
    """
    result = kit.launch("--pi-profile", bad)
    assert result.status != 0, f"accepted profile name {bad!r}"
    assert result.argv == []


def test_pi_refuses_driver_mode(kit):
    result = kit.launch("driver", "--pi")
    assert result.status != 0


# --- the in-container bootstrap ----------------------------------------------
#
# `scripts/pi-bootstrap.sh` runs inside the container as `--pi`'s command. The
# container entrypoint now owns installing and updating pi, so the bootstrap
# only seeds the profile, installs its packages and execs the `pi` on PATH. It
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
        tmp_path, "-p", "hello",
        MULTIPLAI_PI_PROFILE="default", DEEPSEEK_API_KEY="sk-deepseek-secret",
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "OPENROUTER_API_KEY" in proc.stderr
    assert "DEEPSEEK_API_KEY" not in proc.stderr
    assert "sk-deepseek-secret" not in proc.stdout + proc.stderr
    # The last pi call is the exec, with the passthrough args intact.
    assert calls and calls[-1] == "-p hello", calls
    assert (home / ".pi" / "agent" / "models.json").is_file()


def test_bootstrap_defaults_to_the_default_profile(tmp_path):
    proc, home, calls, _ = _bootstrap(tmp_path)
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
