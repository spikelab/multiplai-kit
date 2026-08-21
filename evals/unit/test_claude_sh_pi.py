"""Pins what `claude.sh --pi` launches, and what it refuses to launch.

`--pi` replaces the container's command and adds two mounts. Both are easy to
break silently: a command left as `claude` still starts a working session, and a
missing `~/.pi` mount still starts a working *pi* session — one that quietly
writes its credentials and installed packages into a `--rm` container and loses
them on exit. Neither failure announces itself, so they get asserted here.

The refusals matter as much as the launch. pi ships no permission system, so the
container is the only boundary there is; `--pi --local` or `--pi` with no Docker
must be errors rather than a quiet downgrade to running unsandboxed on the host.

Same harness as `test_claude_sh_env`: a stub `docker` first on `PATH` records the
final `docker run` argv, so no daemon and no image are needed.
"""

import shutil
import subprocess

import pytest

from test_claude_sh_env import kit  # noqa: F401 — `kit` is a fixture

from _kitpaths import KIT_ROOT

PI_HOME = "/home/agent/.pi"
PI_CLI = "/home/agent/.pi-cli"


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
    assert host == str(kit.home / ".claude-container/pi/deepseek"), _mounts(result.argv)


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
    assert a.endswith("/deepseek") and b.endswith("/kimi")


def test_profile_name_reaches_the_bootstrap(kit):
    result = kit.launch("--pi-profile", "kimi")
    assert "MULTIPLAI_PI_PROFILE=kimi" in result.argv


def test_pi_mounts_are_absent_without_the_flag(kit):
    """A plain claude session must not carry pi's state into the container."""
    result = kit.launch("--shell", "-c", "true")
    assert _mount_for(result.argv, PI_HOME) is None
    assert _mount_for(result.argv, PI_CLI) is None


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
    assert pi_home is not None and pi_home.endswith("/deepseek")
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
    """No bare rung for pi: the container is the whole permission boundary."""
    empty_bin = tmp_path / "nodocker"
    empty_bin.mkdir()
    (empty_bin / "claude").write_text("#!/bin/bash\nexit 0\n")
    (empty_bin / "claude").chmod(0o755)
    env = {
        "PATH": f"{empty_bin}:/usr/bin:/bin",
        "HOME": str(kit.home),
        "TERM": "xterm",
    }
    proc = subprocess.run(
        [str(kit.root / "claude.sh"), "--pi"], env=env, capture_output=True, text=True
    )
    assert proc.returncode != 0
    assert "requires Docker" in proc.stdout + proc.stderr


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
