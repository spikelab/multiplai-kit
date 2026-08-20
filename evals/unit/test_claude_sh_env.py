"""Pins the container env-forwarding contract in `claude.sh`.

`claude.sh` decides which host variables reach the container. The rules it
implements are easy to break by accident and expensive to notice: a variable
that silently fails to arrive looks like a broken skill, and an *empty* one that
does arrive looks like a broken default (`-e NAME=` beats every
`${NAME:-fallback}` downstream). Before this file the launcher had no coverage
beyond `bash -n`.

How it works: the launcher is run with a stub `docker` first on `PATH`. The stub
records the final `docker run` argv *and the environment it was handed*. That
environment is exactly what real docker resolves a value-less `-e NAME` against,
so asserting on it is faithful to what lands inside the container — no daemon
and no image required, which is why this can run in CI.

These assertions were checked by mutation rather than trusted: breaking each
rule in the launcher in turn (forwarding empty values, putting secret values on
argv, letting the env file beat the shell, snapshotting per-file so `--profile`
goes inert, dropping the denylist, downgrading the missing-GCP-key error to a
silent skip, and `eval`-ing config values) makes the matching tests fail.

One deviation from a host launch: `claude.sh` short-circuits to bare mode when
`/.dockerenv` exists, which is true whenever the suite itself runs inside a
container. The copy under test has that one path literal repointed at a
nonexistent file so the container path is taken either way. Nothing else is
altered — see `_patched_launcher`.
"""

import os
import shutil
import subprocess
import textwrap

import pytest

from _platform_stubs import _pretend_linux, _pretend_macos

from _kitpaths import KIT_ROOT
LAUNCHER = KIT_ROOT / "claude.sh"

# Two contracts live in here — `image` exits 0, and a `run` carrying
# --entrypoint is the venv-ownership prep call to ignore. A verbatim copy is
# written by the "Composed docker argv" step in .github/workflows/ci.yml (that
# one runs on a throwaway runner with no checkout-relative path to source, so
# it cannot share this text): keep the two in sync.
DOCKER_STUB = """\
#!/bin/bash
case "$1" in
    image) exit 0 ;;
    run)
        # The venv-ownership prep run uses --entrypoint; not the one we want.
        for a in "$@"; do
            if [ "$a" = "--entrypoint" ]; then exit 0; fi
        done
        printf '%s\\n' "$@" > "$DOCKER_ARGV_OUT"
        env > "$DOCKER_ENV_OUT"
        exit 0
        ;;
esac
exit 0
"""

# Bare mode `exec`s `claude` directly, so the stub that stands in for it is how
# a bare launch becomes observable at all.
CLAUDE_STUB = """\
#!/bin/bash
env > "$CLAUDE_ENV_OUT"
exit 0
"""

BASE_ENV_FILE = """\
WORKSPACE="{ws}"
GIT_AUTHOR_NAME="Env File Name"
GIT_AUTHOR_EMAIL="envfile@example.com"
GH_TOKEN="token-from-env-file"
TAVILY_API_KEY="tvly-from-file"
SLACK_TOKEN=""
SMOKE_TEST_VAR="hello"
# ANTHROPIC_BASE_URL="http://commented-out:4000"
"""


class Launch:
    """The observable result of one `claude.sh` invocation."""

    def __init__(self, argv, docker_env, status, output, bare_env=None):
        self.argv = argv
        self.docker_env = docker_env
        self.status = status
        self.output = output
        # What a bare (`--local`) launch handed the real `claude`. Empty dict
        # when no bare launch happened.
        self.bare_env = bare_env or {}

    def forwarded_bare(self, name):
        """True if `-e NAME` was emitted with no `=value` (so it stays out of `ps`)."""
        return name in self.argv

    def forwarded_with_value(self, name):
        """The `NAME=value` argv entry, or None."""
        prefix = f"{name}="
        for line in self.argv:
            if line.startswith(prefix):
                return line
        return None

    def mentions(self, name):
        """True if the variable reaches docker in either form."""
        return self.forwarded_bare(name) or self.forwarded_with_value(name) is not None

    def resolved(self, name):
        """The value real docker would read for a value-less `-e NAME`."""
        return self.docker_env.get(name)


class Kit:
    """A scratch kit root: patched launcher, stub docker, writable .env."""

    def __init__(self, root, home, workspace, stub_dir):
        self.root = root
        self.home = home
        self.workspace = workspace
        self.stub_dir = stub_dir
        self.argv_out = root / "argv.txt"
        self.env_out = root / "denv.txt"
        self.bare_env_out = root / "benv.txt"

    def write_env(self, text):
        (self.root / ".env").write_text(text)

    def append_env(self, text):
        with (self.root / ".env").open("a") as fh:
            fh.write(text)

    def write_profile(self, name, text):
        (self.root / f"env.{name}").write_text(text)

    def launch(self, *args, **extra_env):
        """Run the launcher with a curated environment.

        The environment is built from scratch rather than inherited: with
        shell-env-wins, an inherited `GH_TOKEN` or `GIT_AUTHOR_NAME` would
        legitimately beat the test `.env` and a case meaning to read the file
        value would silently read the developer's instead.
        """
        env = {
            "PATH": f"{self.stub_dir}:{os.environ.get('PATH', '/usr/bin:/bin')}",
            "HOME": str(self.home),
            "TERM": "xterm",
            "DOCKER_ARGV_OUT": str(self.argv_out),
            "DOCKER_ENV_OUT": str(self.env_out),
            "CLAUDE_ENV_OUT": str(self.bare_env_out),
        }
        env.update({k: v for k, v in extra_env.items() if v is not None})

        self.argv_out.write_text("")
        self.env_out.write_text("")
        self.bare_env_out.write_text("")
        proc = subprocess.run(
            [str(self.root / "claude.sh"), *args],
            env=env,
            capture_output=True,
            text=True,
        )

        argv = [ln for ln in self.argv_out.read_text().splitlines()]

        def _as_env(path):
            out = {}
            for line in path.read_text().splitlines():
                if "=" in line:
                    key, _, value = line.partition("=")
                    out[key] = value
            return out

        return Launch(argv, _as_env(self.env_out), proc.returncode,
                      proc.stdout + proc.stderr, _as_env(self.bare_env_out))


def _patched_launcher():
    """The shipped launcher with only the container-detection literal repointed."""
    return LAUNCHER.read_text().replace("/.dockerenv", "/nonexistent-dockerenv-marker")


@pytest.fixture
def kit(tmp_path):
    root = tmp_path / "kit"
    (root / "dotfiles").mkdir(parents=True)
    (root / "claude.sh").write_text(_patched_launcher())
    (root / "claude.sh").chmod(0o755)

    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    (stub_dir / "docker").write_text(DOCKER_STUB)
    (stub_dir / "docker").chmod(0o755)
    (stub_dir / "claude").write_text(CLAUDE_STUB)
    (stub_dir / "claude").chmod(0o755)

    home = tmp_path / "home"
    home.mkdir()
    workspace = tmp_path / "ws"
    workspace.mkdir()

    k = Kit(root, home, workspace, stub_dir)
    k.write_env(BASE_ENV_FILE.format(ws=workspace))
    return k


def test_patch_touches_only_container_detection():
    """Guards the fixture itself: every line it rewrites must be a container check.

    The probe lives once, in `in_container()`, with two callers — the
    driver-mode refusal and the bare-mode fallback — and it should read "not
    containerized" here. If a future edit puts `/.dockerenv` somewhere with
    different intent, this fails before the rest of the suite starts testing a
    launcher that differs from the shipped one in a way nobody chose.
    """
    original = LAUNCHER.read_text().splitlines()
    patched = _patched_launcher().splitlines()
    assert original != patched, "container-detection literal not found — fixture is stale"

    rewritten = [
        (before, after)
        for before, after in zip(original, patched, strict=True)
        if before != after
    ]
    assert rewritten, "patch produced no line-level change"
    for before, after in rewritten:
        assert "/.dockerenv" in before, f"patch altered an unrelated line: {before!r}"
        assert "-f /nonexistent-dockerenv-marker" in after


# --- the empty-variable rule -------------------------------------------------
#
# `-e NAME=` makes a variable present but empty inside the container, which
# defeats `${NAME:-fallback}` and `os.environ.get(NAME, default)`. The concrete
# regression: an unset GH_TOKEN was forwarded as empty and shadowed the token
# the container mints for itself, leaving `gh` unauthenticated with no cause.


def test_empty_shell_var_is_not_forwarded(kit):
    result = kit.launch("--shell", "-c", "true", GH_TOKEN="")
    assert not result.mentions("GH_TOKEN")


def test_empty_env_file_var_is_not_forwarded(kit):
    result = kit.launch("--shell", "-c", "true")
    assert not result.mentions("SLACK_TOKEN")


def test_undeclared_var_is_not_forwarded(kit):
    result = kit.launch("--shell", "-c", "true")
    assert not result.mentions("GMAIL_CLIENT_ID")


def test_commented_out_assignment_is_not_forwarded(kit):
    result = kit.launch("--shell", "-c", "true")
    assert not result.mentions("ANTHROPIC_BASE_URL")


def test_secret_is_forwarded_without_its_value_on_argv(kit):
    """Secrets go as `-e NAME`, so they never appear in `ps` output."""
    result = kit.launch("--shell", "-c", "true")
    assert result.forwarded_bare("GH_TOKEN")
    assert result.forwarded_with_value("GH_TOKEN") is None
    assert result.resolved("GH_TOKEN") == "token-from-env-file"


# --- shell-env-wins precedence ----------------------------------------------


def test_shell_overrides_env_file(kit):
    result = kit.launch("--shell", "-c", "true", GIT_AUTHOR_NAME="OverrideTest")
    assert result.resolved("GIT_AUTHOR_NAME") == "OverrideTest"


def test_committer_defaults_follow_the_overridden_author(kit):
    result = kit.launch("--shell", "-c", "true", GIT_AUTHOR_NAME="OverrideTest")
    assert result.resolved("GIT_COMMITTER_NAME") == "OverrideTest"


def test_env_file_is_the_default_when_shell_is_silent(kit):
    result = kit.launch("--shell", "-c", "true")
    assert result.resolved("GIT_AUTHOR_NAME") == "Env File Name"


def test_shell_wins_for_secrets_too(kit):
    """The GH_TOKEN-minting case: a token exported for one launch must win."""
    result = kit.launch("--shell", "-c", "true", GH_TOKEN="minted-in-shell")
    assert result.resolved("GH_TOKEN") == "minted-in-shell"


# --- dynamic forwarding ------------------------------------------------------


def test_new_env_file_var_arrives_with_no_launcher_edit(kit):
    """The point of the refactor: declaring a variable is the whole install step."""
    kit.append_env('BRAND_NEW_SECRET="arrived"\n')
    result = kit.launch("--shell", "-c", "true")
    assert result.resolved("BRAND_NEW_SECRET") == "arrived"


def test_declared_api_key_is_forwarded(kit):
    result = kit.launch("--shell", "-c", "true")
    assert result.resolved("TAVILY_API_KEY") == "tvly-from-file"


def test_plugin_option_sweep_still_works(kit):
    result = kit.launch("--shell", "-c", "true", CLAUDE_PLUGIN_OPTION_FOO="bar")
    assert result.resolved("CLAUDE_PLUGIN_OPTION_FOO") == "bar"


def test_keep_list_var_is_forwarded_when_absent_from_env_file(kit):
    result = kit.launch("--shell", "-c", "true")
    assert result.forwarded_bare("TERM")


def test_shell_exported_proxy_url_is_forwarded_without_an_env_line(kit):
    """ANTHROPIC_BASE_URL is on the keep-list: pointing one launch at a proxy
    (`ANTHROPIC_BASE_URL=... ./claude.sh`) must work with the .env line still
    commented out — silently dropping it would send traffic direct to Anthropic
    with no visible cause."""
    result = kit.launch(
        "--shell", "-c", "true", ANTHROPIC_BASE_URL="http://host.docker.internal:4000"
    )
    assert result.forwarded_bare("ANTHROPIC_BASE_URL")
    assert result.resolved("ANTHROPIC_BASE_URL") == "http://host.docker.internal:4000"


# --- the denylist ------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["IMAGE_NAME", "KIT_VENV_VOLUME", "CLAUDE_CREDENTIALS_FILE", "GEMINI_CONFIG_DIR"],
)
def test_launcher_only_settings_are_not_forwarded(kit, name, tmp_path):
    """These configure the launcher; inside the container they are noise at best."""
    kit.append_env(
        textwrap.dedent(
            f"""\
            IMAGE_NAME="claude-multiplai:local"
            KIT_VENV_VOLUME="some-vol"
            CLAUDE_CREDENTIALS_FILE="{tmp_path}/creds.json"
            GEMINI_CONFIG_DIR="{tmp_path}/gemini"
            """
        )
    )
    result = kit.launch("--shell", "-c", "true")
    assert not result.mentions(name)


@pytest.mark.parametrize("name", ["PATH", "HOME"])
def test_host_shell_vars_in_env_file_are_not_forwarded(kit, name):
    """A stray `PATH=` in .env must not push macOS paths into a Linux container."""
    kit.append_env('PATH="/host/only/bin"\nHOME="/Users/someone"\n')
    result = kit.launch("--shell", "-c", "true")
    assert not result.mentions(name)


def test_ssh_socket_is_remapped_not_passed_through(kit):
    """The mount block forwards the socket at its container path; the host path
    must not also be emitted, or argv order decides which wins."""
    result = kit.launch("--shell", "-c", "true", SSH_AUTH_SOCK="/tmp/real-agent.sock")
    assert result.forwarded_with_value("SSH_AUTH_SOCK") == "SSH_AUTH_SOCK=/ssh-agent.sock"


def test_network_profile_is_launcher_only(kit):
    result = kit.launch("--shell", "-c", "true", MULTIPLAI_NET="unrestricted")
    assert not result.mentions("MULTIPLAI_NET")


# --- fixed container-side values --------------------------------------------


def test_workspace_and_host_paths_use_container_side_values(kit):
    result = kit.launch("--shell", "-c", "true")
    assert result.forwarded_with_value("WORKSPACE") == f"WORKSPACE={kit.workspace}"
    assert result.forwarded_with_value("HOST_HOME") == f"HOST_HOME={kit.home}"
    assert (
        result.forwarded_with_value("CLAUDE_CONFIG_DIR")
        == f"CLAUDE_CONFIG_DIR={kit.root / 'dotfiles'}"
    )
    assert result.forwarded_with_value("DISABLE_AUTOUPDATER") == "DISABLE_AUTOUPDATER=1"


# --- GCP activation ---------------------------------------------------------


def test_missing_gcp_key_is_a_hard_error_naming_the_path(kit):
    """Silently launching without the credential surfaces as an opaque auth
    failure much later, so a set-but-missing key fails at the door."""
    result = kit.launch("--shell", "-c", "true", GCP_KEY_FILE="/nonexistent/key.json")
    assert result.status != 0
    assert "/nonexistent/key.json" in result.output


def test_gcp_key_is_mounted_readonly_and_credentials_point_at_it(kit, tmp_path):
    key = tmp_path / "key.json"
    key.write_text('{"type":"service_account"}')
    result = kit.launch("--shell", "-c", "true", GCP_KEY_FILE=str(key))

    assert f"{key}:/home/agent/.gcp/key.json:ro" in result.argv
    container_path = "/home/agent/.gcp/key.json"
    assert (
        result.forwarded_with_value("GOOGLE_APPLICATION_CREDENTIALS")
        == f"GOOGLE_APPLICATION_CREDENTIALS={container_path}"
    )
    assert (
        result.forwarded_with_value("CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE")
        == f"CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE={container_path}"
    )
    # The host-side path is meaningless inside the container.
    assert not result.mentions("GCP_KEY_FILE")


def test_gcp_is_inactive_by_default(kit):
    result = kit.launch("--shell", "-c", "true")
    assert result.forwarded_with_value("GOOGLE_APPLICATION_CREDENTIALS") is None


def test_tilde_in_gcp_key_path_is_expanded(kit):
    key_dir = kit.home / ".gcptest"
    key_dir.mkdir()
    (key_dir / "key.json").write_text("{}")
    result = kit.launch("--shell", "-c", "true", GCP_KEY_FILE="~/.gcptest/key.json")
    assert f"{key_dir / 'key.json'}:/home/agent/.gcp/key.json:ro" in result.argv


def test_config_values_are_not_evaluated_as_shell(kit, tmp_path):
    """Tilde expansion uses parameter substitution, not `eval`, so a command
    substitution sitting in a config value stays inert."""
    canary = tmp_path / "pwned"
    kit.launch("--shell", "-c", "true", GCP_KEY_FILE=f"$(touch {canary})")
    assert not canary.exists()


# --- IDE lockfile mount -----------------------------------------------------
#
# What makes `/ide` work from a container against an editor on the host. Two
# halves, and each fails in a way that looks like the other: the mount (the CLI
# cannot find a lockfile at all) and CLAUDE_CODE_IDE_HOST_OVERRIDE (it finds one
# and dials container-localhost, where nothing listens).


def test_ide_lockfile_dir_is_mounted_readonly_at_the_home_path(kit):
    """The container path is /home/agent/.claude/ide, NOT "$DOTFILES_DIR/ide".

    The CLI's search path is the resolved config dir *plus* $HOME/.claude/ide
    whenever CLAUDE_CONFIG_DIR is set — which it always is here. Mounting at the
    dotfiles path is the plausible-looking mistake, and it fails silently: `/ide`
    just reports no IDE.
    """
    ide_dir = kit.home / ".claude" / "ide"
    ide_dir.mkdir(parents=True)
    (ide_dir / "59811.lock").write_text('{"port":59811}')

    result = kit.launch("--shell", "-c", "true")
    assert f"{ide_dir}:/home/agent/.claude/ide:ro" in result.argv


def test_ide_mount_is_skipped_when_the_host_has_no_lockfile_dir(kit):
    """`docker -v` on a missing source silently creates a root-owned directory
    on the host. Without the [ -d ] guard that happens on every launch, for
    every user with no editor extension installed."""
    result = kit.launch("--shell", "-c", "true")
    assert not any("/home/agent/.claude/ide" in a for a in result.argv)
    assert not (kit.home / ".claude" / "ide").exists()


def test_ide_lock_dir_override_is_honoured(kit, tmp_path):
    custom = tmp_path / "elsewhere" / "ide"
    custom.mkdir(parents=True)

    result = kit.launch("--shell", "-c", "true", IDE_LOCK_DIR=str(custom))
    assert f"{custom}:/home/agent/.claude/ide:ro" in result.argv


def test_ide_lock_dir_from_the_env_file_is_not_forwarded(kit, tmp_path):
    """It names a *host* path — launcher-only, meaningless in the container, and
    denied like GEMINI_CONFIG_DIR and GCP_KEY_FILE.

    It must be assigned in the env FILE to test anything: the forwarding loop
    walks the file's own names plus the keep-list, so a shell-only variable
    never forwards whether or not the denylist mentions it, and asserting on
    that path passes even with the denylist entry deleted.
    """
    custom = tmp_path / "fromenv" / "ide"
    custom.mkdir(parents=True)
    kit.write_env(BASE_ENV_FILE.format(ws=kit.workspace))
    kit.append_env(f'IDE_LOCK_DIR="{custom}"\n')

    result = kit.launch("--shell", "-c", "true")
    assert f"{custom}:/home/agent/.claude/ide:ro" in result.argv
    assert not result.mentions("IDE_LOCK_DIR")


def test_tilde_in_ide_lock_dir_is_expanded(kit):
    ide_dir = kit.home / ".idetest"
    ide_dir.mkdir()
    result = kit.launch("--shell", "-c", "true", IDE_LOCK_DIR="~/.idetest")
    assert f"{ide_dir}:/home/agent/.claude/ide:ro" in result.argv


def test_ide_host_override_reaches_the_container(kit):
    """The other half. Forwarded by the ordinary dynamic rule — it is a
    container-side variable, so it must NOT be on the denylist."""
    kit.write_env(BASE_ENV_FILE.format(ws=kit.workspace))
    kit.append_env('CLAUDE_CODE_IDE_HOST_OVERRIDE="host.docker.internal"\n')

    result = kit.launch("--shell", "-c", "true")
    assert result.forwarded_bare("CLAUDE_CODE_IDE_HOST_OVERRIDE")
    assert result.resolved("CLAUDE_CODE_IDE_HOST_OVERRIDE") == "host.docker.internal"


# --- profile overlays -------------------------------------------------------


def test_profile_overrides_env_file_but_not_the_shell(kit):
    """The three-way precedence in one test: shell > profile > .env.

    The subtle failure mode is a per-file environment snapshot, which restores
    .env's value over the profile and makes `--profile` silently inert.
    """
    kit.write_profile("work", 'GIT_AUTHOR_NAME="Work Name"\n')

    from_profile = kit.launch("--profile", "work", "--shell", "-c", "true")
    assert from_profile.resolved("GIT_AUTHOR_NAME") == "Work Name"
    assert from_profile.resolved("SMOKE_TEST_VAR") == "hello", "unrelated .env var lost"

    from_shell = kit.launch(
        "--profile", "work", "--shell", "-c", "true", GIT_AUTHOR_NAME="ShellWins"
    )
    assert from_shell.resolved("GIT_AUTHOR_NAME") == "ShellWins"


def test_unknown_profile_errors_and_lists_real_ones(kit):
    kit.write_profile("work", 'GIT_AUTHOR_NAME="Work Name"\n')
    result = kit.launch("--profile", "nope", "--shell", "-c", "true")
    assert result.status != 0
    assert "work" in result.output
    assert "example" not in result.output, "listed the env.example template as a profile"


# --- GitHub auth mode selection ----------------------------------------------
#
# Two modes, both supported, never both at once: a PAT (`GH_TOKEN` /
# `GH_TOKEN_KEYCHAIN`) or a GitHub App (`GH_TOKEN_APP`, minted per session by
# hooks inside the container). What these pin is the *refusal*: when both are
# declared in configuration the launcher must stop, because a silent winner runs
# the session as the wrong GitHub identity — a failure that looks like a
# permissions bug hours later, in someone else's repo.
#
# App mode is macOS-only (minting goes over the Mac host bridge), so the cases
# below pin `uname` — `_pretend_macos` for the cases that must reach macOS-only
# behaviour, `_pretend_linux` for the two that assert the refusal. Pin it in
# EVERY case; an unpinned one asserts whatever the developer's laptop is, which
# is how `test_app_mode_off_darwin_refuses_to_launch` and
# `test_app_mode_on_a_non_mac_names_the_platform` came to pass on Linux CI while
# failing on a Mac. The stub is NOT confined to this block — the native-Linux
# port added `uname` calls on the PAT/Keychain path too (claude.sh: the App-mode
# refusal here, and the Keychain-unavailable split between a non-Mac and a Mac
# with `security` off PATH) — so do not add a case here assuming `uname` affects
# nothing else.

APP_ENV_FILE = """\
WORKSPACE="{ws}"
GIT_AUTHOR_NAME="Env File Name"
GIT_AUTHOR_EMAIL="envfile@example.com"
GH_TOKEN_APP="acme"
"""


def _install_host_minter(kit):
    """The host-side minting script the launcher pre-flights for in App mode."""
    bin_dir = kit.home / ".local" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    script = bin_dir / "multiplai-gh-token"
    script.write_text("#!/bin/sh\nexit 0\n")
    script.chmod(0o755)
    return script


def test_pat_mode_is_unchanged_and_forwards_no_app_name(kit):
    _pretend_macos(kit)
    result = kit.launch("--shell", "-c", "true")
    assert result.status == 0
    assert result.resolved("GH_TOKEN") == "token-from-env-file"
    assert not result.mentions("GH_TOKEN_APP")


def test_app_mode_forwards_the_app_name_and_no_token(kit):
    """The token is minted in the container, so the launcher forwards only the
    profile name. A forwarded GH_TOKEN would also beat gh's credential store and
    make `gh auth login --with-token` refuse outright."""
    _pretend_macos(kit)
    _install_host_minter(kit)
    kit.write_env(APP_ENV_FILE.format(ws=kit.workspace))

    result = kit.launch("--shell", "-c", "true")
    assert result.status == 0, result.output
    assert result.forwarded_bare("GH_TOKEN_APP")
    assert result.resolved("GH_TOKEN_APP") == "acme"
    assert not result.mentions("GH_TOKEN")


@pytest.mark.parametrize("pat_line", ['GH_TOKEN="pat-token"', 'GH_TOKEN_KEYCHAIN="gh-acme"'])
def test_both_identities_declared_in_files_is_a_hard_error(kit, pat_line):
    """Not a precedence rule. The message must name both variables and the file
    each came from — "both are set" is useless advice to someone with three env
    files."""
    _pretend_macos(kit)
    _install_host_minter(kit)
    kit.write_env(APP_ENV_FILE.format(ws=kit.workspace).replace('GH_TOKEN_APP="acme"', pat_line))
    kit.write_profile("acme", 'GH_TOKEN_APP="acme"\n')

    result = kit.launch("--profile", "acme", "--shell", "-c", "true")
    assert result.status != 0
    assert "GH_TOKEN_APP" in result.output
    assert pat_line.split("=")[0] in result.output
    assert "env.acme" in result.output and ".env" in result.output
    assert result.argv == [], "a container was launched despite the conflict"


def test_shell_token_overrides_a_file_declared_app(kit):
    """The kit's documented "your shell wins" rule. Not a conflict: the token is
    used and GH_TOKEN_APP is dropped so the container hooks stay inert rather
    than fighting the credential that was handed in."""
    _pretend_macos(kit)
    _install_host_minter(kit)
    kit.write_env(APP_ENV_FILE.format(ws=kit.workspace))

    result = kit.launch("--shell", "-c", "true", GH_TOKEN="minted-in-shell")
    assert result.status == 0, result.output
    assert result.resolved("GH_TOKEN") == "minted-in-shell"
    assert not result.mentions("GH_TOKEN_APP")


def test_shell_app_name_overrides_a_file_declared_pat_and_says_so(kit):
    """The same rule in the other direction: GH_TOKEN_APP exported in the shell
    beats the PAT declared in .env. Also an override, not a conflict — but never
    a silent one: the notice must name the variable being dropped and the file
    that declared it, exactly like the mirror case above prints its own."""
    _pretend_macos(kit)
    _install_host_minter(kit)

    # The default .env declares GH_TOKEN="token-from-env-file".
    result = kit.launch("--shell", "-c", "true", GH_TOKEN_APP="acme")
    assert result.status == 0, result.output
    assert result.forwarded_bare("GH_TOKEN_APP")
    assert result.resolved("GH_TOKEN_APP") == "acme"
    assert not result.mentions("GH_TOKEN"), "App mode must forward no PAT"
    assert "overrides GH_TOKEN" in result.output
    assert ".env" in result.output


def test_app_mode_without_the_host_script_refuses_to_launch(kit):
    """Every `gh` call in that session would fail; failing at the door names the
    fix (`./setup.sh`) instead of surfacing as an unauthenticated container."""
    _pretend_macos(kit)
    kit.write_env(APP_ENV_FILE.format(ws=kit.workspace))

    result = kit.launch("--shell", "-c", "true")
    assert result.status != 0
    assert "multiplai-gh-token" in result.output
    assert result.argv == [], "a container was launched with no way to authenticate"


def test_app_mode_off_darwin_refuses_to_launch(kit):
    """Minting needs the macOS host bridge; there is no other route to the key."""
    _pretend_linux(kit)
    kit.write_env(APP_ENV_FILE.format(ws=kit.workspace))
    result = kit.launch("--shell", "-c", "true")
    assert result.status != 0
    assert "macOS" in result.output
    assert result.argv == []


# --- removed flags ----------------------------------------------------------


@pytest.mark.parametrize("flag", ["--gcp", "--net"])
def test_removed_flags_are_no_longer_consumed(kit, flag):
    """They now pass through to the container command like any unknown argument,
    rather than being silently swallowed with their argument."""
    result = kit.launch("--shell", flag, "prod", "-c", "true")
    assert result.argv.count(flag) == 1


@pytest.mark.parametrize("value", ["restricted", "bogus"])
def test_network_profile_validation_survives_the_flag_removal(kit, value):
    result = kit.launch("--shell", "-c", "true", MULTIPLAI_NET=value)
    assert result.status != 0


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")
def test_launcher_parses():
    """Cheap backstop so a syntax error reports here, not as 30 opaque failures."""
    proc = subprocess.run(["bash", "-n", str(LAUNCHER)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


# --- The same decision on every launch path (#23) -----------------------------
#
# `exec` replaces the process, so a check placed after the bare-mode `exec_bare`
# call sites never runs on `--local`, inside a container, or when Docker is
# missing. The GH auth block used to sit there, which meant three launch paths
# got no precedence resolution, no preflight, and no Keychain lookup — and a
# `.env` declaring both identities handed the session both, with `gh` silently
# preferring the environment PAT over the App credential the hooks store.
#
# These pin the block's effects on the bare path specifically. The container
# path is already covered above; what must not regress is that the two agree.

def test_local_mode_still_forwards_the_pat(kit):
    """The baseline: a bare launch is authenticated at all."""
    result = kit.launch("--local")
    assert result.status == 0, result.output
    assert result.bare_env.get("GH_TOKEN") == "token-from-env-file"
    assert result.argv == [], "bare mode must not reach docker"


def test_local_mode_refuses_two_declared_identities(kit):
    """Previously this launched happily with both in the environment, and gh
    picked the PAT over the App credential with nothing said."""
    _pretend_macos(kit)
    _install_host_minter(kit)
    kit.append_env('GH_TOKEN_APP="acme"\n')

    result = kit.launch("--local")
    assert result.status != 0, result.output
    assert "GH_TOKEN_APP" in result.output and "GH_TOKEN" in result.output
    assert result.bare_env == {}, "claude was launched despite the conflict"


def test_local_mode_app_mode_drops_the_pat(kit):
    """App mode forwards the profile name and no token — on the bare path too.
    A GH_TOKEN in the environment beats gh's credential store, so leaving one
    set would run the session as the PAT's identity, not the App's."""
    _pretend_macos(kit)
    _install_host_minter(kit)
    kit.write_env(APP_ENV_FILE.format(ws=kit.workspace))

    result = kit.launch("--local")
    assert result.status == 0, result.output
    assert result.bare_env.get("GH_TOKEN_APP") == "acme"
    assert "GH_TOKEN" not in result.bare_env


def test_local_mode_preflights_the_missing_minter(kit):
    """Without the host minter every gh call in the session fails. Failing at
    launch with the reason beats failing at hook time with a backoff."""
    _pretend_macos(kit)
    kit.write_env(APP_ENV_FILE.format(ws=kit.workspace))

    result = kit.launch("--local")
    assert result.status != 0
    assert "multiplai-gh-token" in result.output
    assert result.bare_env == {}


def test_local_mode_mints_from_the_keychain(kit):
    """The `GH_TOKEN_KEYCHAIN` path never ran bare, so a profile relying on it
    launched unauthenticated."""
    _pretend_macos(kit)
    security = kit.stub_dir / "security"
    security.write_text("#!/bin/sh\nprintf 'token-from-keychain\\n'\n")
    security.chmod(0o755)
    kit.write_env(
        APP_ENV_FILE.format(ws=kit.workspace).replace(
            'GH_TOKEN_APP="acme"', 'GH_TOKEN_KEYCHAIN="gh-acme"'))

    result = kit.launch("--local")
    assert result.status == 0, result.output
    assert result.bare_env.get("GH_TOKEN") == "token-from-keychain"


def test_app_mode_on_a_non_mac_names_the_platform(kit):
    """The App's private key is in the Mac Keychain; nothing on Linux can mint.
    Bare or containerised, refusing at launch beats a session that cannot
    authenticate."""
    _pretend_linux(kit)
    _install_host_minter(kit)
    kit.write_env(APP_ENV_FILE.format(ws=kit.workspace))

    result = kit.launch("--local")
    assert result.status != 0
    assert "macOS" in result.output
    assert result.bare_env == {}
