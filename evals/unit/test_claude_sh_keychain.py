"""Pins the `FOO_KEYCHAIN` convention: any variable, not just `GH_TOKEN`.

`FOO_KEYCHAIN=<item>` means "look `<item>` up in the login Keychain and export
the result as `FOO`". `GH_TOKEN_KEYCHAIN` is now one instance of that rule
rather than a hand-wired case, and the four things below are the four ways the
generalisation could have been wrong:

* **Precedence.** An explicitly set `FOO` wins; `FOO_KEYCHAIN` is consulted only
  when `FOO` is empty. That also keeps the lookup explicit-only — `security`
  never runs for a variable that already has a value.
* **Forwarding.** A resolved `FOO` was named by no env file (the file named
  `FOO_KEYCHAIN`) and is not on the keep-list, so it reaches the container only
  because the resolver adds it to the sweep. Without that it is looked up on the
  host and dropped at the boundary — `GH_TOKEN` escaped that fate only by being
  hand-listed in `_ENV_KEEP`, which is exactly the hand-wiring this replaces.
* **One warning, not N.** Over SSH the login keychain is locked and every lookup
  fails at once. Five secrets must produce one message listing five names, not
  five walls of identical text.
* **App mode still forbids a PAT fallback.** `GH_TOKEN` is the one target the
  resolver skips when `GH_TOKEN_APP` is in play; every other variable resolves
  normally, because that exclusion is about GitHub identity, not about the
  Keychain.

The Keychain-unavailable messages (non-Mac, and a Mac with `security` off
`PATH`) live in `test_claude_sh_crossplatform.py`, which owns the platform
split; this file owns the convention.

Same technique as `test_claude_sh_env.py`, whose `kit` fixture this reuses: a
stub `docker` records the composed argv and the environment docker would resolve
a value-less `-e NAME` against, and a stub `security` answers per item.
"""

from _platform_stubs import _pretend_macos
from test_claude_sh_env import kit  # noqa: F401 — `kit` is a fixture

BASE = """\
WORKSPACE="{ws}"
GIT_AUTHOR_NAME="Env File Name"
GIT_AUTHOR_EMAIL="envfile@example.com"
"""


def _security(kit, items, log=None):
    """Stub `security` as a per-item table.

    A single fixed secret would not distinguish "resolved the right item" from
    "resolved something", and the failure cases need items that are absent while
    others are present — the mixed case is where a per-variable warning loop and
    a collected one diverge.
    """
    body = ["#!/bin/sh"]
    if log is not None:
        body.append(f'printf \'%s\\n\' "$@" >> "{log}"')
    # argv is: find-generic-password -a <user> -s <item> -w
    body.append('item=""')
    body.append('while [ $# -gt 0 ]; do')
    body.append('  [ "$1" = "-s" ] && { item="$2"; shift; }')
    body.append('  shift')
    body.append('done')
    body.append('case "$item" in')
    for name, value in items.items():
        body.append(f"  {name}) printf '{value}\\n'; exit 0 ;;")
    body.append("  *) exit 44 ;;")
    body.append("esac")
    stub = kit.stub_dir / "security"
    stub.write_text("\n".join(body) + "\n")
    stub.chmod(0o755)


# --- the convention ---------------------------------------------------------


def test_any_variable_resolves_from_the_keychain(kit):
    """The rule is the suffix, not a list of blessed names."""
    _pretend_macos(kit)
    _security(kit, {"anthropic-key": "sk-ant-from-keychain"})
    kit.write_env(BASE.format(ws=kit.workspace)
                  + 'ANTHROPIC_API_KEY_KEYCHAIN="anthropic-key"\n')

    result = kit.launch("--shell", "-c", "true")

    assert result.status == 0, result.output
    assert result.resolved("ANTHROPIC_API_KEY") == "sk-ant-from-keychain"


def test_a_resolved_variable_actually_reaches_the_container(kit):
    """The failure this exists for: resolved on the host, dropped at the
    boundary. It is in no env file (the file named the _KEYCHAIN variable) and
    on no keep-list, so nothing else would carry it across."""
    _pretend_macos(kit)
    _security(kit, {"tavily-key": "tvly-from-keychain"})
    kit.write_env(BASE.format(ws=kit.workspace)
                  + 'TAVILY_API_KEY_KEYCHAIN="tavily-key"\n')

    result = kit.launch("--shell", "-c", "true")

    assert result.forwarded_bare("TAVILY_API_KEY"), \
        "resolved on the host and then dropped — the whole point of the forward list"
    assert result.resolved("TAVILY_API_KEY") == "tvly-from-keychain"


def test_the_value_never_reaches_argv(kit):
    """Value-less `-e NAME`, like every other forwarded secret: docker resolves
    it from this process's environment, so it stays out of `ps`."""
    _pretend_macos(kit)
    _security(kit, {"tavily-key": "tvly-from-keychain"})
    kit.write_env(BASE.format(ws=kit.workspace)
                  + 'TAVILY_API_KEY_KEYCHAIN="tavily-key"\n')

    result = kit.launch("--shell", "-c", "true")

    assert result.forwarded_with_value("TAVILY_API_KEY") is None
    assert "tvly-from-keychain" not in " ".join(result.argv)


def test_the_keychain_variable_itself_is_never_forwarded(kit):
    """It names an item in a Keychain the container cannot reach — a pointer to
    nowhere. Denied dynamically now, rather than one hardcoded name."""
    _pretend_macos(kit)
    _security(kit, {"tavily-key": "tvly-from-keychain"})
    kit.write_env(BASE.format(ws=kit.workspace)
                  + 'TAVILY_API_KEY_KEYCHAIN="tavily-key"\n')

    result = kit.launch("--shell", "-c", "true")

    assert not result.mentions("TAVILY_API_KEY_KEYCHAIN")


def test_several_variables_resolve_in_one_launch(kit):
    """Each to its own item — a shared loop variable would give them all the
    last value, and one lookup for all of them is the obvious wrong shortcut."""
    _pretend_macos(kit)
    _security(kit, {"a-item": "value-a", "b-item": "value-b"})
    kit.write_env(BASE.format(ws=kit.workspace)
                  + 'ALPHA_KEY_KEYCHAIN="a-item"\nBETA_KEY_KEYCHAIN="b-item"\n')

    result = kit.launch("--shell", "-c", "true")

    assert result.resolved("ALPHA_KEY") == "value-a"
    assert result.resolved("BETA_KEY") == "value-b"


# --- precedence -------------------------------------------------------------


def test_an_explicit_value_wins(kit):
    """Today's rule for GH_TOKEN, now the rule for everything: it is what keeps
    `FOO=x ./claude.sh` working as a per-launch override."""
    _pretend_macos(kit)
    _security(kit, {"a-item": "from-keychain"})
    kit.write_env(BASE.format(ws=kit.workspace)
                  + 'ALPHA_KEY="from-the-file"\nALPHA_KEY_KEYCHAIN="a-item"\n')

    result = kit.launch("--shell", "-c", "true")

    assert result.resolved("ALPHA_KEY") == "from-the-file"


def test_security_is_not_run_for_a_variable_that_is_already_set(kit, tmp_path):
    """Precedence is not just about which value wins. An explicit value means
    the Keychain has no business being touched at all — the same explicit-only
    rule the implicit `gh-token` probe was removed for."""
    _pretend_macos(kit)
    log = tmp_path / "security-argv"
    _security(kit, {"a-item": "from-keychain"}, log)
    kit.write_env(BASE.format(ws=kit.workspace)
                  + 'ALPHA_KEY="from-the-file"\nALPHA_KEY_KEYCHAIN="a-item"\n')

    result = kit.launch("--shell", "-c", "true")

    assert result.status == 0, result.output
    assert not log.exists(), "`security` ran for a variable that already had a value"


# --- failure reporting ------------------------------------------------------


def test_every_failed_lookup_is_reported_in_one_warning(kit):
    """Over SSH the login keychain is locked and they all fail together. One
    message listing the names; not one message per variable."""
    _pretend_macos(kit)
    _security(kit, {})  # every item missing
    kit.write_env(BASE.format(ws=kit.workspace)
                  + 'ALPHA_KEY_KEYCHAIN="a-item"\nBETA_KEY_KEYCHAIN="b-item"\n')

    result = kit.launch("--shell", "-c", "true")

    assert result.status == 0, "a missing optional secret must not stop a launch"
    assert result.output.count("did not resolve") == 1, \
        f"one warning per variable, not one warning:\n{result.output}"
    assert "ALPHA_KEY_KEYCHAIN" in result.output
    assert "BETA_KEY_KEYCHAIN" in result.output
    assert "a-item" in result.output and "b-item" in result.output


def test_a_partial_failure_reports_only_what_failed(kit):
    """The mixed case, where a per-variable loop and a collected one diverge:
    naming a variable that resolved fine sends the reader after a non-problem."""
    _pretend_macos(kit)
    _security(kit, {"a-item": "value-a"})
    kit.write_env(BASE.format(ws=kit.workspace)
                  + 'ALPHA_KEY_KEYCHAIN="a-item"\nBETA_KEY_KEYCHAIN="b-item"\n')

    result = kit.launch("--shell", "-c", "true")

    assert result.resolved("ALPHA_KEY") == "value-a"
    assert "BETA_KEY_KEYCHAIN" in result.output
    assert "ALPHA_KEY_KEYCHAIN" not in result.output


def test_a_failed_lookup_never_prints_a_value(kit):
    """The warning names the ITEM, which is what the reader has to go and fix.
    A resolved sibling's value has no business in that message."""
    _pretend_macos(kit)
    _security(kit, {"a-item": "secret-value-a"})
    kit.write_env(BASE.format(ws=kit.workspace)
                  + 'ALPHA_KEY_KEYCHAIN="a-item"\nBETA_KEY_KEYCHAIN="b-item"\n')

    result = kit.launch("--shell", "-c", "true")

    assert "secret-value-a" not in result.output


# --- the one exclusion ------------------------------------------------------


def test_app_mode_does_not_resolve_gh_token_from_the_keychain(kit):
    """`unset GH_TOKEN` in App mode exists so a PAT can never silently swap the
    session's GitHub identity. A general resolver running afterwards would put
    it straight back."""
    _pretend_macos(kit)
    _security(kit, {"gh-item": "pat-from-keychain"})
    minter = kit.home / ".local" / "bin"
    minter.mkdir(parents=True, exist_ok=True)
    (minter / "multiplai-gh-token").write_text("#!/bin/sh\nexit 0\n")
    (minter / "multiplai-gh-token").chmod(0o755)
    # GH_TOKEN_APP from the SHELL: the one path that reaches App mode with
    # GH_TOKEN_KEYCHAIN still set (declaring both in files is a hard error).
    kit.write_env(BASE.format(ws=kit.workspace) + 'GH_TOKEN_KEYCHAIN="gh-item"\n')

    result = kit.launch("--shell", "-c", "true", GH_TOKEN_APP="acme")

    assert result.status == 0, result.output
    assert result.resolved("GH_TOKEN") is None, "App mode grew a PAT fallback"
    assert not result.mentions("GH_TOKEN")


def test_app_mode_still_resolves_every_other_variable(kit):
    """The exclusion is about GitHub identity, not about Keychain lookups. A
    blanket skip would take every unrelated secret down with it."""
    _pretend_macos(kit)
    _security(kit, {"gh-item": "pat-from-keychain", "a-item": "value-a"})
    minter = kit.home / ".local" / "bin"
    minter.mkdir(parents=True, exist_ok=True)
    (minter / "multiplai-gh-token").write_text("#!/bin/sh\nexit 0\n")
    (minter / "multiplai-gh-token").chmod(0o755)
    kit.write_env(BASE.format(ws=kit.workspace)
                  + 'GH_TOKEN_KEYCHAIN="gh-item"\nALPHA_KEY_KEYCHAIN="a-item"\n')

    result = kit.launch("--shell", "-c", "true", GH_TOKEN_APP="acme")

    assert result.status == 0, result.output
    assert result.resolved("ALPHA_KEY") == "value-a"
    assert result.resolved("GH_TOKEN") is None
