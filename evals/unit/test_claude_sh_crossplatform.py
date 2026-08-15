"""Pins the launcher behaviour that differs — or must NOT differ — per platform.

Two contracts, both born from the native-Linux (docker-ce) port:

* **The host alias.** In-container code addresses the host as
  `host.docker.internal` (the SSH build bridge, CLAUDE_CODE_IDE_HOST_OVERRIDE,
  an ANTHROPIC_BASE_URL proxy). Docker Desktop and OrbStack resolve that name
  natively; native Linux docker-ce does not — the name only exists when the
  `docker run` carries `--add-host host.docker.internal:host-gateway`. The
  launcher passes the flag unconditionally (harmless on macOS engines, required
  on Linux), so the assertion is platform-independent: the composed argv always
  carries it.

* **GitHub warning hygiene.** A GitHub credential is optional. A launch with
  nothing GitHub-related configured anywhere — no GH_TOKEN, no GH_TOKEN_APP, no
  GH_TOKEN_KEYCHAIN, in the environment or in any env file — must print nothing
  about it. Half-configured states keep their noise: a Keychain name that does
  not resolve, or a Keychain name on a host with no Keychain, is a
  misconfiguration worth naming, and the two have separate messages because a
  Mac with a trimmed PATH is not a non-Mac. The Keychain probe itself is
  explicit-only: the old implicit probe of a default `gh-token` item is gone,
  and these tests fail if it comes back. Nothing replaces it — with no item
  named, `security` does not run at all, and the launch is silent.

Same technique as `test_claude_sh_env.py` (whose `kit` fixture and stubs this
file reuses): stub `docker` / `claude` first on `PATH` record the composed argv
and environment, so no daemon and no image are needed.
"""

import platform

import pytest

from test_claude_sh_env import (  # noqa: F401 — `kit` is a fixture
    _pretend_macos,
    kit,
)

# The launcher's GitHub-silence rule is about what was *configured*, so the
# fixture .env (which declares GH_TOKEN) can't be used here: silence is only
# meaningful against a file with no GitHub entries at all.
NO_GITHUB_ENV_FILE = """\
WORKSPACE="{ws}"
GIT_AUTHOR_NAME="Env File Name"
GIT_AUTHOR_EMAIL="envfile@example.com"
"""


def _pretend_linux(kit):
    """Pin `uname` to Linux so the non-Darwin branch is taken on any dev host."""
    stub = kit.stub_dir / "uname"
    stub.write_text("#!/bin/sh\nprintf 'Linux\\n'\n")
    stub.chmod(0o755)


def _security(kit, argv_log=None, *, found=True, secret="token-from-keychain"):
    """Stub `security`, optionally logging every argv it is called with.

    Only the log can answer the question that matters: WHETHER the Keychain was
    touched at all. With no item named, the answer must be no.
    """
    body = ["#!/bin/sh"]
    if argv_log is not None:
        body.append(f'printf \'%s\\n\' "$@" >> "{argv_log}"')
    if found:
        body.append(f"printf '{secret}\\n'")
        body.append("exit 0")
    else:
        body.append("exit 44")
    stub = kit.stub_dir / "security"
    stub.write_text("\n".join(body) + "\n")
    stub.chmod(0o755)


def _no_keychain_at_all(kit):
    """The honest 'nothing is configured' host: `security` finds no item.

    Pinned rather than left to the real tool, so the silence tests below cannot
    depend on whether the DEVELOPER happens to have a `gh-token` item in their
    own Keychain.
    """
    _security(kit, found=False)


# --- the host alias ----------------------------------------------------------


def test_container_argv_carries_the_host_gateway_alias(kit):
    """Without this flag, `host.docker.internal` resolves on Docker Desktop and
    OrbStack but NOT on native Linux docker-ce — where the SSH bridge, the IDE
    override, and any host-side proxy URL all silently stop resolving."""
    result = kit.launch("--shell", "-c", "true")
    assert "--add-host" in result.argv
    flag_value = result.argv[result.argv.index("--add-host") + 1]
    assert flag_value == "host.docker.internal:host-gateway"


def test_claude_mode_argv_carries_the_host_gateway_alias_too(kit):
    """The default (claude) container launch, not just --shell."""
    result = kit.launch()
    assert "--add-host" in result.argv
    flag_value = result.argv[result.argv.index("--add-host") + 1]
    assert flag_value == "host.docker.internal:host-gateway"


def _driver_launch(kit, *extra):
    """A hub driver launch — the OTHER `docker run` in the launcher.

    Both tests above go through `kit.launch(...)`, which lands on the
    interactive `docker run`. The driver composes its own argv at a separate
    call site reached only via the `driver` subcommand, so an alias added to
    one and not the other passes every test above — and the driver is the
    container most dependent on host reachability, since the hub is on the
    host.
    """
    runner = kit.workspace / "driver_runner.py"
    runner.write_text("# stands in for the hub's driver_runner.py\n")
    return kit.launch(
        "driver",
        "--sid", "new",
        "--port", "8123",
        "--runner", str(runner),
        *extra,
        MULTIPLAI_DRIVER_TOKEN="driver-token-for-tests",
    )


def test_driver_container_argv_carries_the_host_gateway_alias(kit):
    result = _driver_launch(kit)
    assert result.status == 0, result.output
    # Prove it is the driver's `docker run` that was captured, not another.
    assert "--name" in result.argv
    assert result.argv[result.argv.index("--name") + 1].startswith("claude-drv-")

    assert "--add-host" in result.argv
    flag_value = result.argv[result.argv.index("--add-host") + 1]
    assert flag_value == "host.docker.internal:host-gateway"


# --- GitHub silence when nothing is configured -------------------------------


def test_no_github_config_launches_bare_in_silence(kit):
    _no_keychain_at_all(kit)
    kit.write_env(NO_GITHUB_ENV_FILE.format(ws=kit.workspace))
    result = kit.launch("--local")
    assert result.status == 0, result.output
    assert "GH_TOKEN" not in result.output


def test_no_github_config_launches_container_in_silence(kit):
    """The auth block runs before mode selection, so both paths must agree."""
    _no_keychain_at_all(kit)
    kit.write_env(NO_GITHUB_ENV_FILE.format(ws=kit.workspace))
    result = kit.launch("--shell", "-c", "true")
    assert result.status == 0, result.output
    assert "GH_TOKEN" not in result.output
    assert not result.mentions("GH_TOKEN")


# --- the removed implicit probe ----------------------------------------------


def test_keychain_is_not_probed_when_no_item_is_named(kit, tmp_path):
    """Explicit-only, with no exceptions: with no GitHub config at all the
    launcher does not touch the Keychain, even when a `gh-token` item is
    sitting right there. The old behaviour read exactly that item on every
    macOS launch; a user who wants it back sets GH_TOKEN_KEYCHAIN=gh-token.

    `security` is not run at all — not to read a value, and not to look. The
    launcher has no business in the Keychain it was never pointed at."""
    _pretend_macos(kit)
    log = tmp_path / "security-argv"
    _security(kit, log)
    kit.write_env(NO_GITHUB_ENV_FILE.format(ws=kit.workspace))

    result = kit.launch("--local")
    assert result.status == 0, result.output
    assert not log.exists(), "`security` ran with no GH_TOKEN_KEYCHAIN naming an item"
    assert "GH_TOKEN" not in result.bare_env, "an unnamed Keychain item authenticated the session"
    assert "GH_TOKEN" not in result.output, "absence is not a misconfiguration — it stays silent"


# --- half-configured states keep their noise ---------------------------------


def test_named_keychain_item_that_does_not_resolve_still_warns(kit):
    """A name that resolves to nothing is a misconfiguration (wrong item name,
    or a locked login keychain over SSH) — worth naming, unlike plain absence.
    The launch itself still proceeds: gh is simply unauthenticated."""
    _pretend_macos(kit)
    stub = kit.stub_dir / "security"
    stub.write_text("#!/bin/sh\nexit 1\n")
    stub.chmod(0o755)
    kit.write_env(NO_GITHUB_ENV_FILE.format(ws=kit.workspace))
    kit.append_env('GH_TOKEN_KEYCHAIN="gh-missing"\n')

    result = kit.launch("--local")
    assert result.status == 0, result.output
    assert "gh-missing" in result.output
    assert "GH_TOKEN_KEYCHAIN" in result.output


def test_keychain_name_on_a_non_mac_warns_and_launches(kit):
    """GH_TOKEN_KEYCHAIN on a host with no Keychain can never resolve — say so
    and point at GH_TOKEN, rather than launching silently unauthenticated."""
    _pretend_linux(kit)
    kit.write_env(NO_GITHUB_ENV_FILE.format(ws=kit.workspace))
    kit.append_env('GH_TOKEN_KEYCHAIN="gh-somewhere"\n')

    result = kit.launch("--local")
    assert result.status == 0, result.output
    assert "gh-somewhere" in result.output
    assert "GH_TOKEN_KEYCHAIN" in result.output
    # Name the host. The diagnosis IS the platform, so a message that leaves it
    # implicit is the one a Mac user reads and disbelieves (see below).
    assert "Linux" in result.output


@pytest.mark.skipif(
    platform.system() == "Darwin",
    reason="needs a host where `security` is absent; trimming it off PATH would "
           "take every other tool the launcher needs with it",
)
def test_a_mac_without_security_on_path_is_not_told_it_is_not_a_mac(kit):
    """These two failures shared a branch (`Darwin` AND `security`), so a Mac
    launched with a trimmed PATH — cron, an SSH forced command — was told that
    Keychain lookups "need macOS". A diagnosis that contradicts the host sends
    the reader after the wrong problem; separate branches, separate messages."""
    _pretend_macos(kit)  # ...but no `security` stub: the tool is missing.
    kit.write_env(NO_GITHUB_ENV_FILE.format(ws=kit.workspace))
    kit.append_env('GH_TOKEN_KEYCHAIN="gh-somewhere"\n')

    result = kit.launch("--local")
    assert result.status == 0, result.output
    assert "gh-somewhere" in result.output
    lowered = result.output.lower()
    assert "'security' is not on path" in lowered, "the message must name the actual cause"
    assert "needs macos" not in lowered, "told a Mac that Keychain lookups need macOS"


def test_named_keychain_item_that_resolves_stays_silent(kit):
    """The configured-and-working case: token found, nothing printed."""
    _pretend_macos(kit)
    stub = kit.stub_dir / "security"
    stub.write_text("#!/bin/sh\nprintf 'token-from-keychain\\n'\n")
    stub.chmod(0o755)
    kit.write_env(NO_GITHUB_ENV_FILE.format(ws=kit.workspace))
    kit.append_env('GH_TOKEN_KEYCHAIN="gh-present"\n')

    result = kit.launch("--local")
    assert result.status == 0, result.output
    assert result.bare_env.get("GH_TOKEN") == "token-from-keychain"
    assert "Warning" not in result.output
