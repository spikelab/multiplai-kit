"""Pins the two GitHub-App hooks that keep a session authenticated.

`gh-app-auth.sh` (SessionStart) mints an App installation token and stores it in
gh's own credential store; `gh-app-refresh.sh` (PreToolUse on Bash) re-mints when
the cached one has run out. Together they are the reason a session needs no
token prefix and no manual mint — which is exactly why they need tests: nothing
in an ordinary session *looks* different when they silently stop working. The
symptom arrives an hour later as `Bad credentials (HTTP 401)`.

Four properties are worth pinning, and all four are one-line-edit fragile:

  * **Inert without `GH_TOKEN_APP`.** PAT-mode users and marketplace-only users
    must pay one test and see no behaviour change.
  * **Staleness is decided at the moment of use**, and anything unreadable
    counts as stale. A session can idle for hours; a cache that cannot be parsed
    must never be mistaken for a live token.
  * **Neither hook can break the session.** A dead bridge degrades to an
    unauthenticated `gh`, never to a failing SessionStart or a blocked Bash
    call. So both exit 0 on every path, and the refresh hook emits no permission
    decision at all.
  * **A failed mint never reaches `gh` at all.** This one is here because the
    original design got it wrong and shipped (2026-07-30). `gh auth login
    --with-token` does not fail on empty stdin — gh 2.96.0 falls through to the
    interactive OAuth *device flow*, prints a one-time code and blocks forever.
    So `gh-tok | gh auth login --with-token` converted every failed mint into a
    HUNG SessionStart and a hung PreToolUse hook: no session would start, and
    the reverting fix was to tear both hooks out of settings.json. "Exit 0 on
    every path" is not enough — a hook that hangs never reaches its exit.

Everything is driven by stubs: a fake `gh-tok` in the hooks directory and a fake
`gh` on `PATH`, both recording their invocations. No network, no bridge, no
`gh` install required.

`GH_STUB` is deliberately forgiving (it `cat`s whatever it gets and exits 0),
which is what let the hang ship green. `GH_STUB_REALISTIC` models the real
thing, including the block, and the tests that matter use it with a hard
subprocess timeout so a regression fails the suite instead of wedging it.
"""

import os
import subprocess
from pathlib import Path

import pytest

KIT_ROOT = Path(__file__).resolve().parents[2]
HOOKS_DIR = KIT_ROOT / "dotfiles" / "hooks"
AUTH_HOOK = HOOKS_DIR / "gh-app-auth.sh"
REFRESH_HOOK = HOOKS_DIR / "gh-app-refresh.sh"

SKEW = 120  # both hooks re-mint this many seconds before the real expiry

GH_TOK_STUB = """\
#!/bin/bash
echo "$@" >> "$GH_TOK_CALLS"
printf 'ghs_stub_token\\n'
"""

GH_TOK_FAILING_STUB = """\
#!/bin/bash
echo "$@" >> "$GH_TOK_CALLS"
printf 'gh-tok: bridge unreachable\\n' >&2
exit 1
"""

GH_STUB = """\
#!/bin/bash
echo "$@" >> "$GH_CALLS"
cat > "$GH_STDIN"
"""

# What `gh auth login --with-token` actually does, measured on gh 2.96.0: an
# empty token on stdin is not an error, it is a cue to start the interactive
# device flow — which prints a code and then waits on a terminal forever.
GH_STUB_REALISTIC = """\
#!/bin/bash
echo "$@" >> "$GH_CALLS"
tok=$(cat)
printf '%s' "$tok" > "$GH_STDIN"
if [ -z "$tok" ]; then
    printf '! First copy your one-time code: 89DC-8B53\\n'
    printf 'Open this URL to continue in your web browser: https://github.com/login/device\\n'
    sleep 60
    exit 1
fi
"""

# Long enough that a real bridge call would finish, far shorter than the 60s
# block in the realistic stub: a hang fails, a working hook passes.
HANG_BUDGET = 15


class Session:
    """One fake container session: a HOME, a hooks dir, and recording stubs."""

    def __init__(self, root):
        self.root = root
        self.home = root / "home"
        self.config = root / "config"
        self.hooks = self.config / "hooks"
        self.bin = root / "bin"
        for d in (self.home, self.hooks, self.bin):
            d.mkdir(parents=True, exist_ok=True)

        # The hooks under test, verbatim from the kit.
        for src in (AUTH_HOOK, REFRESH_HOOK):
            dst = self.hooks / src.name
            dst.write_text(src.read_text())
            dst.chmod(0o755)

        self.gh_tok_calls = root / "gh-tok-calls.txt"
        self.gh_calls = root / "gh-calls.txt"
        self.gh_stdin = root / "gh-stdin.txt"
        self.set_minter(GH_TOK_STUB)

        self.set_gh(GH_STUB)

        self.cache_dir = self.home / ".cache" / "multiplai" / "gh"

    def set_minter(self, body):
        stub = self.hooks / "gh-tok"
        stub.write_text(body)
        stub.chmod(0o755)

    def set_gh(self, body):
        gh = self.bin / "gh"
        gh.write_text(body)
        gh.chmod(0o755)

    def write_sidecar(self, app, text):
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        (self.cache_dir / f"{app}.json.exp").write_text(text)

    def write_fail_marker(self, app, text):
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        (self.cache_dir / f"{app}.json.fail").write_text(text)

    def fail_marker(self, app="acme"):
        return self.cache_dir / f"{app}.json.fail"

    def run(self, hook, app="acme", timeout=None, **extra):
        env = {
            "PATH": f"{self.bin}:{os.environ.get('PATH', '/usr/bin:/bin')}",
            "HOME": str(self.home),
            "CLAUDE_CONFIG_DIR": str(self.config),
            "CLAUDE_MULTIPLAI_HOME": str(self.home),
            "GH_TOK_CALLS": str(self.gh_tok_calls),
            "GH_CALLS": str(self.gh_calls),
            "GH_STDIN": str(self.gh_stdin),
        }
        if app is not None:
            env["GH_TOKEN_APP"] = app
        env.update(extra)
        return subprocess.run(
            ["bash", str(self.hooks / hook)],
            env=env,
            input="",
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    @property
    def mint_attempts(self):
        if not self.gh_tok_calls.exists():
            return 0
        return len(self.gh_tok_calls.read_text().splitlines())

    @property
    def gh_invocations(self):
        if not self.gh_calls.exists():
            return []
        return self.gh_calls.read_text().splitlines()


@pytest.fixture
def session(tmp_path):
    return Session(tmp_path)


def _now():
    return int(subprocess.run(["date", "+%s"], capture_output=True, text=True).stdout.strip())


# --- inert unless the session is in App mode ---------------------------------


@pytest.mark.parametrize("hook", ["gh-app-auth.sh", "gh-app-refresh.sh"])
def test_hook_is_inert_without_an_app_profile(session, hook):
    """PAT-mode and marketplace-only users must see no behaviour change at all."""
    result = session.run(hook, app=None)
    assert result.returncode == 0
    assert session.mint_attempts == 0
    assert session.gh_invocations == []


@pytest.mark.parametrize("hook", ["gh-app-auth.sh", "gh-app-refresh.sh"])
def test_hook_first_line_is_the_app_mode_guard(hook):
    """The guard has to be the FIRST executable line: everything below it costs
    something on a path most users never want to be on."""
    body = (HOOKS_DIR / hook).read_text().splitlines()
    first = next(ln for ln in body if ln.strip() and not ln.lstrip().startswith("#"))
    assert "GH_TOKEN_APP" in first and "exit 0" in first, first


# --- SessionStart: mint into gh's credential store ---------------------------


def test_auth_hook_stores_the_token_through_a_pipe(session):
    """`gh auth login --with-token` reads stdin. The token must never be an
    argument — argv is visible in `ps` and in any transcript that shows it."""
    result = session.run("gh-app-auth.sh")
    assert result.returncode == 0
    assert session.mint_attempts == 1
    assert session.gh_invocations == ["auth login --with-token --hostname github.com"]
    assert session.gh_stdin.read_text().strip() == "ghs_stub_token"


def test_auth_hook_passes_the_app_name_to_the_minter(session):
    session.run("gh-app-auth.sh", app="other-app")
    assert session.gh_tok_calls.read_text().strip() == "other-app"


def test_auth_hook_survives_a_failed_mint(session):
    """A dead bridge must not stop the session from starting."""
    session.set_minter(GH_TOK_FAILING_STUB)
    result = session.run("gh-app-auth.sh")
    assert result.returncode == 0


def test_auth_hook_never_stores_an_empty_credential(session):
    """`gh-tok` prints nothing on failure, so the store call must never happen —
    a truncated or stale credential that *looks* valid is worse than none, and
    handing `gh` an empty token is worse still (see the device-flow tests)."""
    session.set_minter(GH_TOK_FAILING_STUB)
    session.run("gh-app-auth.sh")
    assert session.gh_invocations == []
    if session.gh_stdin.exists():
        assert session.gh_stdin.read_text().strip() == ""


def test_auth_hook_clears_an_inherited_environment_token(session):
    """With GH_TOKEN set, `gh auth login --with-token` refuses outright. App mode
    forwards none, but a stray one must not silently block the store."""
    result = session.run("gh-app-auth.sh", GH_TOKEN="ghp_stray")
    assert result.returncode == 0
    assert session.gh_invocations == ["auth login --with-token --hostname github.com"]


# --- PreToolUse: renew only when the cached token has run out ----------------


@pytest.mark.parametrize("terminator", ["\n", ""])
def test_no_remint_while_the_cached_token_is_valid(session, terminator):
    """The common case, and it runs before every single Bash call.

    Both terminators, because `read` returns non-zero at EOF-without-newline: an
    earlier `|| exp=0` form discarded a valid expiry from an unterminated
    sidecar and re-minted on every Bash call — a fork storm that still *worked*,
    so nothing would have surfaced it but this test.
    """
    session.write_sidecar("acme", f"{_now() + 3600}{terminator}")
    result = session.run("gh-app-refresh.sh")
    assert result.returncode == 0
    assert session.mint_attempts == 0


def test_remint_when_the_expiry_has_passed(session):
    """Including "passed seven hours ago" — an idle session is the case a
    timer-driven scheme misses, so staleness is decided here, at use."""
    session.write_sidecar("acme", str(_now() - 25_000))
    result = session.run("gh-app-refresh.sh")
    assert result.returncode == 0
    assert session.mint_attempts == 1
    assert session.gh_invocations == ["auth login --with-token --hostname github.com"]


def test_remint_inside_the_skew_window(session):
    """A token that dies in four minutes is renewed now, not handed to a command
    that will still be running when it expires."""
    session.write_sidecar("acme", str(_now() + SKEW - 30))
    session.run("gh-app-refresh.sh")
    assert session.mint_attempts == 1


@pytest.mark.parametrize("sidecar", [None, "", "not-a-number", "  ", "99999999999999999999x"])
def test_unreadable_sidecar_counts_as_expired(session, sidecar):
    """Never treat an unparseable cache as valid — that is a live 401 waiting to
    happen, and the failure is silent until someone runs a `gh` command."""
    if sidecar is not None:
        session.write_sidecar("acme", sidecar)
    result = session.run("gh-app-refresh.sh")
    assert result.returncode == 0
    assert session.mint_attempts == 1


def test_refresh_hook_survives_a_failed_mint(session):
    """A broken bridge degrades to "the gh call gets a 401" — never to "Bash
    stopped working"."""
    session.set_minter(GH_TOK_FAILING_STUB)
    session.write_sidecar("acme", "0")
    result = session.run("gh-app-refresh.sh")
    assert result.returncode == 0


def test_refresh_hook_emits_no_permission_decision(session):
    """It is a PreToolUse hook on Bash: anything it prints to stdout is parsed as
    a decision. It must never deny, allow, or ask."""
    session.write_sidecar("acme", "0")
    for setup in (lambda: None, lambda: session.set_minter(GH_TOK_FAILING_STUB)):
        setup()
        result = session.run("gh-app-refresh.sh")
        assert result.stdout == "", result.stdout


# --- a dead bridge must not stall every Bash call ----------------------------
#
# The mint path pays an SSH connect timeout (up to 10s) when the bridge is down.
# Without a backoff, a dead bridge plus an expired cache re-enters that path on
# EVERY Bash call — a per-call stall inside a PreToolUse hook. One failed mint
# writes a short-lived marker; the guard honours it; success removes it.


def test_failed_mint_writes_a_backoff_marker(session):
    session.set_minter(GH_TOK_FAILING_STUB)
    session.write_sidecar("acme", "0")
    session.run("gh-app-refresh.sh")
    assert session.mint_attempts == 1
    until = session.fail_marker().read_text().strip()
    assert until.isdigit() and int(until) > _now(), until


def test_no_retry_while_the_backoff_marker_is_fresh(session):
    """The second call must not reach the minter at all — reaching it is the
    stall this marker exists to prevent."""
    session.set_minter(GH_TOK_FAILING_STUB)
    session.write_sidecar("acme", "0")
    session.run("gh-app-refresh.sh")
    result = session.run("gh-app-refresh.sh")
    assert result.returncode == 0
    assert session.mint_attempts == 1


@pytest.mark.parametrize("marker", ["expired", "not-a-number", ""])
def test_stale_or_unreadable_backoff_marker_does_not_block_the_retry(session, marker):
    """The marker self-expires by timestamp, and an unparseable one counts as
    absent — backoff must never turn into a permanent lockout."""
    session.write_sidecar("acme", "0")
    session.write_fail_marker("acme", str(_now() - 1) if marker == "expired" else marker)
    session.run("gh-app-refresh.sh")
    assert session.mint_attempts == 1


def test_successful_mint_clears_the_backoff_marker(session):
    session.write_sidecar("acme", "0")
    session.write_fail_marker("acme", str(_now() - 1))
    session.run("gh-app-refresh.sh")
    assert session.mint_attempts == 1
    assert not session.fail_marker().exists()


def test_auth_hook_failure_spares_the_first_bash_call_the_same_stall(session):
    """A failed SessionStart mint already proved the bridge dead; it writes the
    marker too, so the refresh hook's first run skips straight past the mint."""
    session.set_minter(GH_TOK_FAILING_STUB)
    session.run("gh-app-auth.sh")
    assert session.fail_marker().exists()
    result = session.run("gh-app-refresh.sh")
    assert result.returncode == 0
    assert session.mint_attempts == 1, "the refresh hook re-entered the mint path"


# --- a failed mint must never reach `gh` ------------------------------------
#
# The regression these pin shipped in multiplai-kit#21 and made every session
# unstartable. `gh auth login --with-token` treats empty stdin as "no token
# supplied" and starts the interactive OAuth device flow, which blocks forever.
# Piping a failed `gh-tok` straight into it therefore hangs the hook — at
# SessionStart that is "Claude will not start", and on PreToolUse it is "every
# Bash call stalls". Both hooks now mint into a variable and test it first.


@pytest.mark.parametrize("hook", ["gh-app-auth.sh", "gh-app-refresh.sh"])
def test_failed_mint_never_invokes_gh(session, hook):
    """The emptiness check is the fix: with nothing to store, `gh` is not run."""
    session.set_minter(GH_TOK_FAILING_STUB)
    session.write_sidecar("acme", "0")
    result = session.run(hook, timeout=HANG_BUDGET)
    assert result.returncode == 0
    assert session.gh_invocations == [], "a failed mint was handed to gh anyway"


@pytest.mark.parametrize("hook", ["gh-app-auth.sh", "gh-app-refresh.sh"])
def test_failed_mint_does_not_hang_against_a_realistic_gh(session, hook):
    """The whole bug, end to end, with a `gh` that behaves like the real one.

    A `subprocess.TimeoutExpired` here IS the regression — it means the hook is
    sitting in a device flow. Before the fix this hung indefinitely; the harness
    timeout converts that into a failing test instead of a wedged suite.
    """
    session.set_minter(GH_TOK_FAILING_STUB)
    session.set_gh(GH_STUB_REALISTIC)
    session.write_sidecar("acme", "0")
    result = None
    try:
        result = session.run(hook, timeout=HANG_BUDGET)
    except subprocess.TimeoutExpired:
        pass
    assert result is not None, (
        f"{hook} hung: a failed mint reached gh and started a device flow"
    )
    assert result.returncode == 0
    combined = result.stdout + result.stderr
    assert "login/device" not in combined, combined


@pytest.mark.parametrize("hook", ["gh-app-auth.sh", "gh-app-refresh.sh"])
def test_successful_mint_still_stores_against_a_realistic_gh(session, hook):
    """The realistic stub must not be passing the tests above for the wrong
    reason: given a real token it accepts it exactly like the forgiving one."""
    session.set_gh(GH_STUB_REALISTIC)
    session.write_sidecar("acme", "0")
    result = session.run(hook, timeout=HANG_BUDGET)
    assert result.returncode == 0
    assert session.gh_invocations == ["auth login --with-token --hostname github.com"]
    assert session.gh_stdin.read_text().strip() == "ghs_stub_token"


@pytest.mark.parametrize("hook", [AUTH_HOOK, REFRESH_HOOK])
def test_the_minter_is_never_piped_straight_into_gh(hook):
    """Shape guard on the exact construct that broke. The token must be captured
    and tested before it goes anywhere near `gh`; a pipe straight off the minter
    reintroduces the hang no matter what the surrounding logic says."""
    code = [
        ln for ln in hook.read_text().splitlines()
        if ln.strip() and not ln.lstrip().startswith("#")
    ]
    # Rejoin backslash continuations: the broken form spanned two physical lines,
    # so a per-physical-line check would have missed it.
    logical, buf = [], ""
    for ln in code:
        buf += ln.rstrip("\\") if ln.rstrip().endswith("\\") else ln
        if not ln.rstrip().endswith("\\"):
            logical.append(buf)
            buf = ""
    joined = "\n".join(logical)

    assert "gh-tok" in joined, "the minter call vanished"
    assert '[ -n "$tok" ]' in joined, "the emptiness check is gone"
    for stmt in logical:
        if "gh-tok" in stmt and "gh auth login" in stmt:
            pytest.fail(f"minter piped straight into gh auth login:\n{stmt}")


@pytest.mark.parametrize("hook", [AUTH_HOOK, REFRESH_HOOK])
def test_the_store_call_is_bounded(hook):
    """Belt-and-braces behind the emptiness check: whatever `gh` decides to do
    with its stdin in some future version, it cannot stall a session."""
    for line in hook.read_text().splitlines():
        if "gh auth login" in line and not line.lstrip().startswith("#"):
            assert "timeout " in line, f"unbounded store call: {line}"
            break
    else:
        pytest.fail("no `gh auth login` call found")


# --- the log is for debugging, so it must stay readable ----------------------


def test_missing_sidecars_produce_no_stderr_noise(session):
    """`read -r x < missing 2>/dev/null` does NOT silence the shell: bash applies
    redirections left to right, so the failing `<` is reported before the stderr
    redirect takes effect. That spammed hook-errors.log with "No such file or
    directory" on exactly the missing-cache path you go to the log to debug."""
    result = session.run("gh-app-refresh.sh", timeout=HANG_BUDGET)
    assert result.returncode == 0
    assert "No such file or directory" not in result.stderr, result.stderr


# --- the hot path must fork nothing -----------------------------------------


def test_refresh_guard_forks_zero_processes():
    """This runs before EVERY Bash call, and the kit already pays for one Python
    hook there. The guard is three builtins against $EPOCHSECONDS and the
    bare-integer sidecar; a `date`, a `jq` or a `$( )` here is a fork on every
    single tool call, and removing that cost is why the sidecar exists at all.
    """
    body = REFRESH_HOOK.read_text()
    # Sliced on the renew banner, which is the actual semantic boundary. (It used
    # to slice on the first "gh-tok" occurrence, which broke the moment the mint
    # became `tok=$(... gh-tok ...)` — the `$(` then landed inside the slice.)
    assert "--- renew" in body, "renew section banner is gone; the slice is wrong"
    guard = body.split("--- renew")[0]
    code = [
        ln for ln in guard.splitlines() if ln.strip() and not ln.lstrip().startswith("#")
    ]
    joined = "\n".join(code)
    for forker in ("$(", "`", "jq", "date ", "stat ", "openssl"):
        assert forker not in joined, f"{forker!r} in the hot path:\n{joined}"
    assert "EPOCHSECONDS" in joined, "guard does not use the builtin clock"
    assert ".exp" in joined, "guard does not read the bare-integer sidecar"


# --- shape ------------------------------------------------------------------


@pytest.mark.parametrize("hook", [AUTH_HOOK, REFRESH_HOOK])
def test_hooks_are_shell_and_parse(hook):
    assert hook.read_text().splitlines()[0].startswith("#!"), "no shebang"
    assert "bash" in hook.read_text().splitlines()[0], "container has bash, not zsh"
    proc = subprocess.run(["bash", "-n", str(hook)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


@pytest.mark.parametrize("hook", [AUTH_HOOK, REFRESH_HOOK, HOOKS_DIR / "gh-tok"])
def test_scripts_are_executable(hook):
    assert os.access(hook, os.X_OK), f"{hook.name} is not executable"


def test_gh_tok_never_prints_a_token_on_a_failure_path():
    """Its stdout is piped straight into `gh auth login`, so every failure exit
    must leave stdout empty — the hooks' abort signal is "nothing came out"."""
    body = (HOOKS_DIR / "gh-tok").read_text()
    assert "die()" in body and ">&2" in body
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("die()"):
            assert ">&2" in stripped, "die() must write to stderr, not stdout"
