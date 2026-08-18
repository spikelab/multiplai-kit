"""Pins the two GitHub-App hooks that keep a session authenticated.

`gh-app-auth.sh` (SessionStart) mints an App installation token and stores it in
gh's own credential store; `gh-app-refresh.sh` (PreToolUse on Bash) re-mints when
the cached one has run out. Together they are the reason a session needs no
token prefix and no manual mint — which is exactly why they need tests: nothing
in an ordinary session *looks* different when they silently stop working. The
symptom arrives an hour later as `Bad credentials (HTTP 401)`.

Five properties are worth pinning, and all five are one-line-edit fragile:

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
  * **Nothing assumes the container's toolchain.** The kit also runs bare on a
    Mac: /bin/bash 3.2 (no $EPOCHSECONDS, no printf '%(...)T'), no GNU
    coreutils (no `timeout`), BSD date. The store-call bound falls back to a
    perl alarm, the clock to a single `date` fork, and `gh-tok` mints via the
    local `multiplai-gh-token` instead of ssh'ing to a bridge hostname that
    only resolves inside a container.

Everything is driven by stubs: a fake `gh-tok` in the hooks directory and a fake
`gh` on `PATH`, both recording their invocations. No network, no bridge, no
`gh` install required.

`GH_STUB` is deliberately forgiving (it `cat`s whatever it gets and exits 0),
which is what let the hang ship green. `GH_STUB_REALISTIC` models the real
thing, including the block, and the tests that matter use it with a hard
subprocess timeout so a regression fails the suite instead of wedging it.
"""

import os
import shutil
import signal
import subprocess

import pytest

from conftest import KIT_ROOT
HOOKS_DIR = KIT_ROOT / "dotfiles" / "hooks"
AUTH_HOOK = HOOKS_DIR / "gh-app-auth.sh"
REFRESH_HOOK = HOOKS_DIR / "gh-app-refresh.sh"
# The mint+store block both hooks source — the emptiness check, the backoff
# pre-write and the bounded store live here, once.
STORE_HELPER = HOOKS_DIR / "gh-store-token"
GH_TOK = HOOKS_DIR / "gh-tok"
BOUNDED_LIB = HOOKS_DIR / "gh-bounded"

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

# A mint that never returns — what a black-hole bridge (SYN drop, no RST) looks
# like. Used to model the outer settings.json "timeout": 30 killing the hook.
GH_TOK_HANGING_STUB = """\
#!/bin/bash
echo "$@" >> "$GH_TOK_CALLS"
sleep 60
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

        # The hooks under test, verbatim from the kit — plus the shared
        # mint/store helper they source, and the bound helper *it* sources.
        for src in (AUTH_HOOK, REFRESH_HOOK, STORE_HELPER, BOUNDED_LIB):
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

    def run(self, hook, app="acme", timeout=None, path=None, **extra):
        env = {
            "PATH": path or f"{self.bin}:{os.environ.get('PATH', '/usr/bin:/bin')}",
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
        # Popen + killpg, not subprocess.run: run() only kills the direct child
        # on timeout, and an orphaned stub (the realistic gh's device-flow
        # `sleep 60`) then holds the captured pipes open — the post-kill read
        # blocks until the stub exits, turning a 15s regression failure into a
        # ~75s one. A fresh session group lets one kill take out the whole tree.
        proc = subprocess.Popen(
            ["bash", str(self.hooks / hook)],
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        try:
            out, err = proc.communicate(input="", timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
            raise
        return subprocess.CompletedProcess(proc.args, proc.returncode, out, err)

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


def test_auth_hook_skips_the_mint_while_the_cached_token_is_fresh(session):
    """SessionStart also fires on resume and after a compaction, when the token
    minted at the real start is usually still live — re-minting there costs a
    bridge round-trip for nothing. Same freshness check as the refresh hook."""
    session.write_sidecar("acme", str(_now() + 3600))
    result = session.run("gh-app-auth.sh")
    assert result.returncode == 0
    assert session.mint_attempts == 0
    assert session.gh_invocations == []
    assert not session.fail_marker().exists(), (
        "the skip path must not leave a backoff marker behind"
    )


def test_auth_hook_still_mints_inside_the_skew_window(session):
    """Fresh means comfortably fresh: a token dying in under the skew window is
    renewed at SessionStart, not handed to the session."""
    session.write_sidecar("acme", str(_now() + SKEW - 30))
    session.run("gh-app-auth.sh")
    assert session.mint_attempts == 1


@pytest.mark.parametrize("hook", ["gh-app-auth.sh", "gh-app-refresh.sh"])
def test_child_sessions_still_refresh_tokens(session, hook):
    """No _HOOK_CHILD_SESSION skip here, deliberately: SDK children run git
    and gh legitimately and need the freshness path, and both hooks are
    already cheap on the common path (builtins guard / sidecar skip). The
    child guard exists to stop recursive heavy work, and a stale token in a
    child is real work to fix. Briefly shipped and reverted, 2026-08-10."""
    session.write_sidecar("acme", "0")  # stale — a child must still renew
    result = session.run(hook, _HOOK_CHILD_SESSION="1")
    assert result.returncode == 0
    assert session.mint_attempts == 1
    assert session.gh_invocations == ["auth login --with-token --hostname github.com"]


@pytest.mark.parametrize("hook", ["gh-app-auth.sh", "gh-app-refresh.sh"])
@pytest.mark.parametrize("app", ["../evil", "a/b", "acme$(x)", "acme evil"])
def test_a_malformed_app_name_never_reaches_the_filesystem(session, hook, app):
    """The app name becomes a cache filename. gh-tok validates it, but the
    backoff marker is written before gh-tok runs — the shared helper must
    refuse first, or `../evil` writes outside the cache directory."""
    result = session.run(hook, app=app)
    assert result.returncode == 0
    assert session.mint_attempts == 0, "a malformed name reached the minter"
    assert session.gh_invocations == []
    outside = session.home / ".cache" / "multiplai" / "evil.json.fail"
    assert not outside.exists(), "a traversal in the app name escaped the cache dir"


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


@pytest.mark.parametrize("hook", ["gh-app-auth.sh", "gh-app-refresh.sh"])
def test_a_killed_hook_leaves_the_backoff_marker_behind(session, hook):
    """The hook entries in settings.json carry "timeout": 30, and a slow bridge
    plus a slow store can exceed it. A hook Claude Code kills mid-mint never
    reaches any failure branch — so the marker must be written BEFORE the mint,
    or the next Bash call re-pays the very stall the marker exists to prevent."""
    session.set_minter(GH_TOK_HANGING_STUB)
    session.write_sidecar("acme", "0")
    with pytest.raises(subprocess.TimeoutExpired):
        session.run(hook, timeout=3)
    assert session.fail_marker().exists(), (
        "no backoff marker after a mid-mint kill: the marker is being written "
        "on the failure branch, which a killed hook never reaches"
    )


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
def test_hooks_source_the_shared_store_helper(hook):
    """Both hooks run the ONE copy of the mint/store block. A hook that grows
    its own inline copy re-opens the drift that let the 2026-07-30 hang ship."""
    code = [
        ln for ln in hook.read_text().splitlines()
        if ln.strip() and not ln.lstrip().startswith("#")
    ]
    sourcing = [ln for ln in code if "hooks/gh-store-token" in ln]
    assert len(sourcing) == 1, "hook does not source gh-store-token exactly once"
    assert sourcing[0].lstrip().startswith(". "), sourcing[0]


@pytest.mark.parametrize("hook", [STORE_HELPER])
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


@pytest.mark.parametrize("hook", [STORE_HELPER])
def test_the_store_call_is_bounded(hook):
    """Belt-and-braces behind the emptiness check: whatever `gh` decides to do
    with its stdin in some future version, it cannot stall a session. The bound
    goes through `bounded` (GNU timeout / perl alarm), never bare `timeout` —
    macOS ships no coreutils, and `timeout: command not found` there turned a
    valid mint into a failed store."""
    body = hook.read_text()
    for line in body.splitlines():
        if "gh auth login" in line and not line.lstrip().startswith("#"):
            assert "bounded " in line, f"unbounded store call: {line}"
            break
    else:
        pytest.fail("no `gh auth login` call found")
    assert "hooks/gh-bounded" in body, "the store helper must source gh-bounded"
    lib = BOUNDED_LIB.read_text()
    assert "command -v timeout" in lib and "alarm" in lib, (
        "bounded() must try GNU timeout and fall back to a perl alarm"
    )


# --- the kit also runs bare on a Mac -----------------------------------------
#
# No container means: /bin/bash 3.2 (no $EPOCHSECONDS, no printf '%(...)T'),
# no GNU coreutils (no `timeout`), BSD date. The functional tests below run the
# hooks against a PATH that models the missing-coreutils half; the static test
# pins the bash-3.2 constructs, which CI's bash 5 cannot exercise directly.


def _restricted_path(session):
    """A PATH carrying everything the hooks legitimately need EXCEPT GNU
    `timeout` — the shape of a bare Mac, where coreutils is not installed."""
    nobin = session.root / "nobin"
    nobin.mkdir(exist_ok=True)
    for tool in ("bash", "mkdir", "rm", "date", "perl", "sleep", "cat", "dirname"):
        src = shutil.which(tool)
        assert src, f"{tool} not found on the real PATH"
        dst = nobin / tool
        if not dst.exists():
            dst.symlink_to(src)
    return f"{session.bin}:{nobin}"


@pytest.mark.parametrize("hook", ["gh-app-auth.sh", "gh-app-refresh.sh"])
def test_store_works_without_gnu_timeout(session, hook):
    """The regression the perl fallback exists for: an unguarded `timeout 20
    gh ...` on a Mac is `command not found` (exit 127) — a perfectly good mint
    turned into a failed store, and gh silently unauthenticated."""
    session.write_sidecar("acme", "0")
    result = session.run(hook, timeout=HANG_BUDGET, path=_restricted_path(session))
    assert result.returncode == 0
    assert session.gh_invocations == ["auth login --with-token --hostname github.com"]
    assert session.gh_stdin.read_text().strip() == "ghs_stub_token"
    assert not session.fail_marker().exists(), "success must clear the backoff marker"


@pytest.mark.parametrize("hook", ["gh-app-auth.sh", "gh-app-refresh.sh"])
def test_failed_mint_does_not_hang_without_gnu_timeout(session, hook):
    """The device-flow protection must not itself depend on GNU timeout."""
    session.set_minter(GH_TOK_FAILING_STUB)
    session.set_gh(GH_STUB_REALISTIC)
    session.write_sidecar("acme", "0")
    result = session.run(hook, timeout=HANG_BUDGET, path=_restricted_path(session))
    assert result.returncode == 0
    assert session.gh_invocations == []


def _bounded_fn():
    # The one definition both callers source (gh-store-token and gh-tok).
    lines = BOUNDED_LIB.read_text().splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith("bounded()"))
    end = next(i for i, ln in enumerate(lines) if i > start and ln.rstrip() == "}")
    return "\n".join(lines[start : end + 1])


@pytest.mark.parametrize("with_gnu_timeout", [True, False])
def test_bounded_actually_bounds(session, with_gnu_timeout):
    """Both branches of `bounded` must genuinely kill a stuck command —
    otherwise the fallback is decoration and a Mac regains the hang. (The perl
    alarm(2) survives exec(2), which is what makes the fallback a real bound.)"""
    probe = session.root / "probe.sh"
    probe.write_text(f"{_bounded_fn()}\nbounded 1 sleep 30\n")
    path = (
        os.environ.get("PATH", "/usr/bin:/bin")
        if with_gnu_timeout
        else _restricted_path(session)
    )
    result = subprocess.run(
        ["bash", str(probe)],
        env={"PATH": path},
        capture_output=True,
        text=True,
        timeout=10,  # TimeoutExpired here means the bound did nothing
    )
    assert result.returncode != 0, "a stuck store call survived its bound"


@pytest.mark.parametrize("hook", [AUTH_HOOK, REFRESH_HOOK, STORE_HELPER])
def test_hooks_carry_no_bash5_only_constructs(hook):
    """A bare Mac runs these under /bin/bash 3.2. Bare $EPOCHSECONDS is silently
    empty there (the guard would compare against nothing), and printf '%(...)T'
    is a hard printf error. CI's bash can't exercise 3.2, so pin the constructs
    themselves; the clock must go through the documented fallback idiom."""
    code = [
        ln for ln in hook.read_text().splitlines() if not ln.lstrip().startswith("#")
    ]
    joined = "\n".join(code)
    assert "%(" not in joined, "printf '%(...)T' is bash 4.2+; a bare Mac has 3.2"
    stripped = joined.replace("${EPOCHSECONDS:-$(date +%s)}", "")
    assert "EPOCHSECONDS" not in stripped, (
        "bare $EPOCHSECONDS is bash 5+; use ${EPOCHSECONDS:-$(date +%s)}"
    )


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
    assert "EPOCHSECONDS" in joined, "guard does not use the builtin clock"
    assert ".exp" in joined, "guard does not read the bare-integer sidecar"
    # The ONE sanctioned fork is the bash-3.2 clock fallback (a bare Mac has no
    # $EPOCHSECONDS), and only as this exact idiom — on the container's bash 5
    # the parameter expansion short-circuits and nothing forks.
    joined = joined.replace("${EPOCHSECONDS:-$(date +%s)}", "<clock>")
    for forker in ("$(", "`", "jq", "date ", "stat ", "openssl"):
        assert forker not in joined, f"{forker!r} in the hot path:\n{joined}"


# --- shape ------------------------------------------------------------------


@pytest.mark.parametrize("hook", [AUTH_HOOK, REFRESH_HOOK, STORE_HELPER])
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


# --- gh-tok picks its route: local host script, or the SSH bridge -------------
#
# Bare on a Mac, `multiplai-gh-token` sits on PATH (setup.sh installs it) and
# `host.docker.internal` does not resolve — ssh'ing to a bridge would fail every
# mint. Inside the container it is the exact opposite. `command -v` decides.

HOST_MINTER_STUB = """\
#!/bin/bash
echo "$@" >> "$HOST_MINTER_CALLS"
printf '{"token":"ghs_local_token","expires_at":"2099-01-01T00:00:00Z"}\\n'
"""

SSH_JSON_STUB = """\
#!/bin/bash
echo "$@" >> "$SSH_CALLS"
printf '{"token":"ghs_bridge_token","expires_at":"2099-01-01T00:00:00Z"}\\n'
"""


def _run_gh_tok(tmp_path, with_host_minter):
    bin_dir = tmp_path / "bin"
    home = tmp_path / "home"
    bin_dir.mkdir()
    home.mkdir()
    ssh_calls = tmp_path / "ssh-calls.txt"
    minter_calls = tmp_path / "minter-calls.txt"
    ssh = bin_dir / "ssh"
    ssh.write_text(SSH_JSON_STUB)
    ssh.chmod(0o755)
    if with_host_minter:
        minter = bin_dir / "multiplai-gh-token"
        minter.write_text(HOST_MINTER_STUB)
        minter.chmod(0o755)
    result = subprocess.run(
        [str(HOOKS_DIR / "gh-tok"), "acme"],
        env={
            "PATH": f"{bin_dir}:{os.environ.get('PATH', '/usr/bin:/bin')}",
            "HOME": str(home),
            "SSH_CALLS": str(ssh_calls),
            "HOST_MINTER_CALLS": str(minter_calls),
        },
        capture_output=True,
        text=True,
        timeout=HANG_BUDGET,
    )
    return result, ssh_calls, minter_calls


def test_gh_tok_mints_locally_when_the_host_script_is_present(tmp_path):
    """Bare on a Mac the script is right there — no ssh, no bridge hostname."""
    result, ssh_calls, minter_calls = _run_gh_tok(tmp_path, with_host_minter=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ghs_local_token"
    assert not ssh_calls.exists(), "gh-tok ssh'd to the bridge despite a local script"
    assert minter_calls.read_text().strip() == "--json acme"


def test_gh_tok_uses_the_bridge_without_the_host_script(tmp_path):
    """Inside the container the App key stays on the Mac: ssh is the only route."""
    result, ssh_calls, _ = _run_gh_tok(tmp_path, with_host_minter=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ghs_bridge_token"
    assert "multiplai-gh-token --json acme" in ssh_calls.read_text()


def test_gh_tok_bounds_both_mint_routes():
    """`ConnectTimeout` bounds only the TCP connect: a bridge that accepts and
    then stalls held the mint forever, and the bare-Mac route had no bound at
    all. Both routes must go through `bounded` (GNU timeout / perl alarm)."""
    body = GH_TOK.read_text()
    code = [
        ln for ln in body.splitlines()
        if ln.strip() and not ln.lstrip().startswith("#")
    ]
    # Rejoin backslash continuations — the ssh route spans two physical lines.
    logical, buf = [], ""
    for ln in code:
        buf += ln.rstrip("\\") if ln.rstrip().endswith("\\") else ln
        if not ln.rstrip().endswith("\\"):
            logical.append(buf)
            buf = ""
    mints = [s for s in logical if "multiplai-gh-token --json" in s]
    assert len(mints) == 2, "expected exactly the local and the bridge route"
    for stmt in mints:
        assert "bounded " in stmt, f"unbounded mint route: {stmt}"
    assert "gh-bounded" in body, "gh-tok must source the shared gh-bounded helper"
    lib = BOUNDED_LIB.read_text()
    assert "command -v timeout" in lib and "alarm" in lib, (
        "bounded() must try GNU timeout and fall back to a perl alarm"
    )
