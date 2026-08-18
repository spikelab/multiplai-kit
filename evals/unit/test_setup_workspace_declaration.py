"""Pins the host-bridge workspace declaration setup.sh writes (mktplace#15),
and the path normalization that decides *which* directory gets declared.

The gateway on the Mac confines path-taking commands (swift, xcodebuild, xcrun,
mlx-whisper, qmd) to one directory, and it **fails closed**: with no declaration
it denies them outright. It cannot take that directory from the container —
a boundary supplied by the side being confined is not a boundary — so it reads
`~/.local/state/multiplai/workspace`, which only the host can write. setup.sh is
the writer, because it already knows `$WORKSPACE` and already installs the
gateway that reads it.

**Two things are under test, and they are not separable.** The declaration is
only as good as the value it carries, and `$WORKSPACE` used to reach it through
`WORKSPACE=$(eval echo "$WORKSPACE")` — which re-parses a path as shell source.
`/tmp/Work #2` silently became `/tmp/Work`, i.e. the declared jail was the
*parent* of the configured workspace. So these tests drive the real
`normalize_workspace` / `canonicalize_workspace` functions and hand their output
to the real `declare_workspace_to_host_bridge`, in that order — the order
setup.sh itself runs them in. An earlier version of this file assigned
`WORKSPACE` directly and skipped normalization entirely, which is how it came to
certify a round trip (`my knowhere (main)`) that the shipped script aborted on.

**Why functions are extracted rather than run in place.** The declaration lives
inside setup.sh's `if [ "$(uname -s)" = "Darwin" ]` arm, so nothing on Linux
reaches it: not this suite, and not the three `Linux e2e` CI jobs that run
`./setup.sh` end to end. Faking `uname` would drag in every other Darwin path in
the script. The two early-exit cases *are* driven through a real `./setup.sh`
(they abort at the top, before anything platform-specific), which is what proves
the normalization is actually wired in rather than merely present.

What a Linux box still cannot tell you: whether `sandbox-exec` accepts the
shipped profile, and whether each bridge tool still works under it. That is a
smoke test on the Mac, once, per tool.

Note on the profile itself: `confine.sb` denies *writes* outside the declared
workspace. It does not confine reads, and nothing here should be read as saying
it does.
"""

import os
import shlex
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from conftest import KIT_ROOT
SETUP_SH = KIT_ROOT / "setup.sh"

# Matching on source text is deliberate: a rewrite should make these tests fail
# to find the code rather than pass against a stale copy. Functions are the
# anchor now (not a line range) because a function has an unambiguous end — the
# previous line-range extraction had already swept in the wrong `mkdir` once.
_INDENT = "  "


def _extract_function(name: str) -> str:
    """A shell function, lifted verbatim from setup.sh and dedented.

    `install_host_state` sits two spaces in (inside the Docker step) while the
    workspace helpers are at column 0, so the closing brace is matched at the
    definition's own indent rather than at column 0.
    """
    lines = SETUP_SH.read_text().splitlines()
    # A trailing `# …` comment on the definition line is allowed.
    opens = [i for i, ln in enumerate(lines) if ln.strip().startswith(f"{name}() {{")]
    assert len(opens) == 1, (
        f"expected exactly one `{name}()` in setup.sh, found {len(opens)}"
    )
    start = opens[0]
    indent = " " * (len(lines[start]) - len(lines[start].lstrip()))
    for end in range(start + 1, len(lines)):
        if lines[end] == indent + "}":
            body = lines[start:end + 1]
            return "\n".join(
                ln[len(indent):] if ln.startswith(indent) else ln for ln in body
            )
    raise AssertionError(f"could not find the closing brace of {name}()")


def _normalization() -> str:
    return "\n\n".join(
        _extract_function(n)
        for n in ("normalize_workspace", "canonicalize_workspace")
    )


def _run(
    raw_workspace: str,
    *,
    home: Path,
    scaffold: bool = True,
    umask: str | None = None,
) -> subprocess.CompletedProcess:
    """Drive setup.sh's real path handling, in setup.sh's own order.

    `raw_workspace` is what `.env` supplies — unexpanded, unnormalized. The
    `mkdir -p` stands in for Step 1 of setup.sh, which is what makes the second
    `canonicalize_workspace` able to resolve anything at all.
    """
    script = [
        "set -euo pipefail",
        f"HOME={shlex.quote(str(home))}",
        *([f"umask {umask}"] if umask else []),
        _normalization(),
        _extract_function("declare_workspace_to_host_bridge"),
        f"WORKSPACE={shlex.quote(raw_workspace)}",
        "normalize_workspace",
        "canonicalize_workspace",
        *(['mkdir -p "$WORKSPACE"', "canonicalize_workspace"] if scaffold else []),
        "declare_workspace_to_host_bridge",
    ]
    return subprocess.run(
        ["bash", "-c", "\n".join(script)],
        capture_output=True, text=True,
        env={"PATH": "/usr/bin:/bin", "HOME": str(home)},
    )


def _run_setup_sh(tmp_path: Path, env_body: str) -> subprocess.CompletedProcess:
    """The real ./setup.sh against a throwaway `.env`.

    setup.sh reads `.env` from its own directory, so the script is copied to a
    temp dir rather than pointed at one — writing a `.env` into the checkout
    would clobber the developer's. Only usable for cases that abort at the top,
    before setup.sh touches anything else it ships with.
    """
    root = tmp_path / "kit"
    root.mkdir()
    shutil.copy2(SETUP_SH, root / "setup.sh")
    (root / ".env").write_text(env_body)
    return subprocess.run(
        [str(root / "setup.sh")],
        capture_output=True, text=True, cwd=str(root),
        env={**os.environ, "HOME": str(tmp_path / "home")},
    )


def _decl(home: Path) -> Path:
    return home / ".local" / "state" / "multiplai" / "workspace"


# --------------------------------------------------------------------------
# The code is still where these tests think it is
# --------------------------------------------------------------------------

def test_the_functions_are_still_where_the_test_thinks_they_are():
    decl = _extract_function("declare_workspace_to_host_bridge")
    assert ".local/state/multiplai" in decl
    assert '"$dir/workspace"' in decl
    assert "$WORKSPACE" in decl
    # `install_host_state`'s own mkdir must not have been swept in — mis-
    # extraction is exactly what the function anchor exists to prevent.
    assert "local/bin" not in decl
    # Not a bare `"eval" not in …` — the explanatory text says the word.
    code = [ln.split("#", 1)[0] for ln in _normalization().splitlines()]
    assert not any("eval " in ln for ln in code), (
        "a path is data; running it through eval is the bug these tests exist for"
    )


# --------------------------------------------------------------------------
# The declaration itself
# --------------------------------------------------------------------------

def test_declares_an_existing_workspace(tmp_path):
    ws = tmp_path / "knowhere"
    ws.mkdir()
    home = tmp_path / "home"
    home.mkdir()

    result = _run(str(ws), home=home)
    assert result.returncode == 0, result.stderr

    assert _decl(home).is_file()
    # Exactly one line, the absolute path — the gateway reads `head -n 1` and
    # refuses anything that is not an existing absolute path.
    assert _decl(home).read_text() == f"{ws}\n"


def test_rewrites_a_stale_declaration_and_says_so(tmp_path):
    """A workspace that moved must move its declaration, or the gateway keeps
    confining builds to a directory the user no longer works in.

    It must also *say* it retargeted: one declaration serves every kit checkout
    on the machine, so this same write is how a second kit silently steals the
    jail from the first.
    """
    home = tmp_path / "home"
    decl_dir = home / ".local" / "state" / "multiplai"
    decl_dir.mkdir(parents=True)
    (decl_dir / "workspace").write_text("/old/workspace\n")

    ws = tmp_path / "new-place"
    ws.mkdir()
    result = _run(str(ws), home=home)
    assert result.returncode == 0, result.stderr
    assert _decl(home).read_text() == f"{ws}\n"
    assert "/old/workspace" in result.stdout
    assert "different workspace" in result.stdout


def test_a_rewrite_to_the_same_path_says_nothing_alarming(tmp_path):
    ws = tmp_path / "knowhere"
    ws.mkdir()
    home = tmp_path / "home"
    decl_dir = home / ".local" / "state" / "multiplai"
    decl_dir.mkdir(parents=True)
    (decl_dir / "workspace").write_text(f"{ws}\n")

    result = _run(str(ws), home=home)
    assert result.returncode == 0, result.stderr
    assert "different workspace" not in result.stdout


# --------------------------------------------------------------------------
# Normalization — the value that reaches the declaration (and sandbox-exec)
# --------------------------------------------------------------------------

def test_a_comment_character_is_rejected_rather_than_truncating_the_path(tmp_path):
    """`eval echo "/tmp/Work #2"` returned `/tmp/Work`, exit 0, no warning — the
    `#` opened a comment. The declared jail was then the *parent* of the
    configured workspace, one level wider than anyone asked for."""
    parent = tmp_path / "ws"
    (parent / "Work #2").mkdir(parents=True)
    home = tmp_path / "home"
    home.mkdir()

    result = _run(str(parent / "Work #2"), home=home)
    assert result.returncode != 0
    assert "shell metacharacter" in result.stdout
    assert not _decl(home).exists(), "a rejected path must not be declared"


def test_a_semicolon_is_rejected_and_its_tail_is_never_executed(tmp_path):
    """`eval` both truncated at the `;` and ran what followed it."""
    ws = tmp_path / "ws"
    ws.mkdir()
    sentinel = tmp_path / "PWNED"
    home = tmp_path / "home"
    home.mkdir()

    result = _run(f"{ws};touch {sentinel}", home=home, scaffold=False)
    assert result.returncode != 0
    assert "shell metacharacter" in result.stdout
    assert not sentinel.exists(), "the tail after `;` was executed"
    assert not _decl(home).exists()


def test_a_workspace_with_spaces_survives_the_round_trip(tmp_path):
    """Single spaces were the one metacharacter `eval` let through intact, so
    this is the case that must keep working. (Doubled spaces did not: `eval`
    collapsed them and the path then failed `-d`. They work now.)"""
    ws = tmp_path / "my  knowhere is here"
    ws.mkdir()
    home = tmp_path / "home"
    home.mkdir()

    result = _run(str(ws), home=home)
    assert result.returncode == 0, result.stderr
    assert _decl(home).read_text() == f"{ws}\n"


def test_a_parenthesised_path_is_rejected_with_a_clear_error(tmp_path):
    """This fixture used to be asserted as a *successful* round trip, which the
    shipped script could never do — `eval` died on it with `syntax error near
    unexpected token '('`, exit 2, long before the declaration block. Nobody can
    be running such a workspace today, so refusing it by name is strictly better
    than the bash parse error, and cheaper than proving every consumer quotes."""
    ws = tmp_path / "my knowhere (main)"
    ws.mkdir()
    home = tmp_path / "home"
    home.mkdir()

    result = _run(str(ws), home=home)
    assert result.returncode != 0
    assert "shell metacharacter" in result.stdout
    assert not _decl(home).exists()


@pytest.mark.parametrize("bad", ["a&b", "a|b", "a`b`", "a*b", "a{b}b", "a'b", 'a"b'])
def test_shell_metacharacters_are_refused_by_name(tmp_path, bad):
    home = tmp_path / "home"
    home.mkdir()
    result = _run(f"{tmp_path}/{bad}", home=home, scaffold=False)
    assert result.returncode != 0
    assert "shell metacharacter" in result.stdout


def test_an_unexpanded_variable_gets_its_own_error(tmp_path):
    """`.env` is sourced, so `WORKSPACE="$HOME/knowhere"` has already expanded.
    Only the single-quoted form arrives literal — it used to work by accident,
    through eval, and now needs a message that says what to write instead."""
    home = tmp_path / "home"
    home.mkdir()
    result = _run("$HOME/knowhere", home=home, scaffold=False)
    assert result.returncode != 0
    assert "unexpanded variable" in result.stdout


def test_a_leading_tilde_is_expanded_without_a_shell(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    result = _run("~/knowhere", home=home)
    assert result.returncode == 0, result.stderr
    assert _decl(home).read_text() == f"{home}/knowhere\n"


def test_a_bare_tilde_is_the_home_directory(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    result = _run("~", home=home)
    assert result.returncode == 0, result.stderr
    assert _decl(home).read_text() == f"{home}\n"


# --------------------------------------------------------------------------
# Canonicalization — SBPL `(subpath …)` is matched against kernel paths
# --------------------------------------------------------------------------

def test_trailing_and_doubled_slashes_are_canonicalized(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    home = tmp_path / "home"
    home.mkdir()

    result = _run(f"{ws}//", home=home)
    assert result.returncode == 0, result.stderr
    assert _decl(home).read_text() == f"{ws}\n"


def test_a_dotdot_component_is_resolved(tmp_path):
    """`-d` passes on a path with `..` and one trailing slash is all the old
    code stripped, so the declared string reached `(subpath …)` intact and
    matched nothing the kernel ever reports."""
    ws = tmp_path / "ws"
    ws.mkdir()
    (tmp_path / "other").mkdir()
    home = tmp_path / "home"
    home.mkdir()

    result = _run(f"{ws}/../other/../ws", home=home)
    assert result.returncode == 0, result.stderr
    assert _decl(home).read_text() == f"{ws}\n"


def test_a_symlinked_parent_is_resolved_to_the_real_path(tmp_path):
    """The macOS case this matters for is `/tmp` → `/private/tmp`, plus any
    workspace on an external volume or under a symlinked `~/Documents`: the
    declared path matches no canonical path, so the fail-closed profile denies
    every write inside the user's real workspace."""
    real = tmp_path / "real"
    real.mkdir()
    (tmp_path / "link").symlink_to(real, target_is_directory=True)
    home = tmp_path / "home"
    home.mkdir()

    result = _run(str(tmp_path / "link"), home=home)
    assert result.returncode == 0, result.stderr
    assert _decl(home).read_text() == f"{real}\n"


# --------------------------------------------------------------------------
# The write itself: permissions, atomicity
# --------------------------------------------------------------------------

def test_the_declaration_is_not_group_or_world_writable(tmp_path):
    """A world-writable declaration would let any local process retarget the
    jail, which is the one thing the host-owned location is for.

    Run under `umask 000`, so a missing `chmod` shows up as 0666 rather than
    being masked into looking correct. The previous version of this test grepped
    setup.sh for the literal chmod line and would have passed with that line
    commented out.
    """
    ws = tmp_path / "knowhere"
    ws.mkdir()
    home = tmp_path / "home"
    home.mkdir()

    result = _run(str(ws), home=home, umask="000")
    assert result.returncode == 0, result.stderr

    mode = stat.S_IMODE(_decl(home).stat().st_mode)
    assert mode == 0o644, f"declaration is mode {mode:o}"
    assert not mode & (stat.S_IWGRP | stat.S_IWOTH)


def test_a_restrictive_umask_still_leaves_it_readable(tmp_path):
    """The gateway runs as the same user, but an unreadable declaration would
    fail closed on every bridge command — pin both ends of the umask range."""
    ws = tmp_path / "knowhere"
    ws.mkdir()
    home = tmp_path / "home"
    home.mkdir()

    result = _run(str(ws), home=home, umask="077")
    assert result.returncode == 0, result.stderr
    assert stat.S_IMODE(_decl(home).stat().st_mode) == 0o644


def test_the_write_leaves_no_temporary_file_behind(tmp_path):
    """`printf … > file` truncates in place, so a bridge command reading the
    declaration mid-setup sees an empty first line. The fix is write-then-
    rename; the observable trace of it is that nothing else is left in the
    directory."""
    ws = tmp_path / "knowhere"
    ws.mkdir()
    home = tmp_path / "home"
    home.mkdir()

    assert _run(str(ws), home=home).returncode == 0
    state = home / ".local" / "state" / "multiplai"
    assert sorted(p.name for p in state.iterdir()) == ["workspace"]


def test_the_declaration_is_published_by_rename():
    """Complements the two mode tests above rather than standing in for them:
    no black-box assertion can observe the truncation window, so the mechanism
    is pinned directly — and the chmod must land on the temp file, before the
    name exists."""
    body = _extract_function("declare_workspace_to_host_bridge")
    assert "mv -f" in body
    assert '> "$tmp"' in body
    assert '> "$decl"' not in body, "the declaration is truncated in place"
    assert body.index('chmod 644 "$tmp"') < body.index("mv -f")


# --------------------------------------------------------------------------
# When it runs
# --------------------------------------------------------------------------

def test_the_declaration_is_not_gated_on_the_docker_daemon():
    """`HAS_DOCKER` comes from `docker info` — it says whether the daemon is up
    *right now*, which is why setup.sh keeps it apart from the durable
    `DOCKER_INSTALLED`. Writing the declaration under it meant editing WORKSPACE
    in `.env`, running ./setup.sh with Docker Desktop stopped, reading "Setup
    complete!", and getting a gateway that still points at the old path — whose
    own remedy text is "Re-run ./setup.sh on the Mac to rewrite it".
    """
    lines = SETUP_SH.read_text().splitlines()
    calls = [i for i, ln in enumerate(lines)
             if ln.strip() == "declare_workspace_to_host_bridge"]
    assert len(calls) == 1, "expected exactly one call site"
    call = calls[0]

    # Blocks are indented consistently in this file, so a bare `fi` at column 0
    # closes a bare `if` at column 0.
    for i, ln in enumerate(lines):
        if ln == "if $HAS_DOCKER; then":
            close = next(j for j in range(i + 1, len(lines)) if lines[j] == "fi")
            assert not (i < call < close), (
                f"the declaration (line {call + 1}) is inside the "
                f"`if $HAS_DOCKER` block at lines {i + 1}-{close + 1}"
            )


def test_setup_sh_refuses_an_empty_workspace_before_it_declares_anything(tmp_path):
    """The dead `else` arm that used to sit around the declaration warned about
    this case and could never run: `-z "$WORKSPACE"` exits at the top, and
    `mkdir -p "$WORKSPACE"` in Step 1 runs under `set -euo pipefail`. So the
    guarantee is pinned where it actually holds, on the real script."""
    result = _run_setup_sh(tmp_path, 'WORKSPACE=""\nGIT_AUTHOR_NAME="x"\n')
    assert result.returncode == 1
    assert "WORKSPACE not set" in result.stdout
    assert not _decl(tmp_path / "home").exists()


def test_setup_sh_itself_refuses_the_comment_path(tmp_path):
    """End-to-end proof that normalization is wired into the script, not merely
    present in it — the failure mode the extracted-function tests cannot see."""
    (tmp_path / "Work #2").mkdir()
    result = _run_setup_sh(
        tmp_path, f'WORKSPACE="{tmp_path}/Work #2"\nGIT_AUTHOR_NAME="x"\n'
    )
    assert result.returncode == 1
    assert "shell metacharacter" in result.stdout
    assert not (tmp_path / "Work").exists(), "the truncated parent was scaffolded"


# --------------------------------------------------------------------------
# The sandbox profile that reads the declaration
# --------------------------------------------------------------------------

def test_confine_profile_is_installed_alongside_the_gateway():
    """The gateway references `confine.sb`; a release where the gateway ships
    and the profile does not is the version skew install_host_state exists to
    prevent."""
    text = SETUP_SH.read_text()
    darwin = text[text.find('if [ "$(uname -s)" = "Darwin" ]'):]
    assert "install_host_tool container-build-gateway.sh" in darwin
    assert "install_host_state confine.sb" in darwin


def _run_install_host_state(
    *, kit: Path, home: Path, at_pin: str = "true", build_ok: str = "true"
) -> subprocess.CompletedProcess:
    script = [
        "set -euo pipefail",
        f"SCRIPT_DIR={shlex.quote(str(kit))}",
        f"HOME={shlex.quote(str(home))}",
        f"CONTAINER_AT_PIN={at_pin}",
        f"BUILD_OK={build_ok}",
        'CONTAINER_REF="v0.10"',
        _extract_function("install_host_state"),
        'install_host_state confine.sb "the host sandbox profile"',
    ]
    return subprocess.run(
        ["bash", "-c", "\n".join(script)],
        capture_output=True, text=True,
        env={"PATH": "/usr/bin:/bin", "HOME": str(home)},
    )


def test_a_container_tag_without_the_profile_says_so(tmp_path):
    """`CONTAINER_REF` still pins a tag that predates `confine.sb`, so on merge
    this installs no profile at all. Harmless — that gateway reads neither file
    — but it used to `return 0` in silence under a "Setup complete!"."""
    kit = tmp_path / "kit"
    (kit / "container").mkdir(parents=True)
    home = tmp_path / "home"
    home.mkdir()

    result = _run_install_host_state(kit=kit, home=home)
    assert result.returncode == 0, result.stderr
    assert "confine.sb" in result.stdout
    assert "NOT installed" in result.stdout


def test_a_profile_dropped_by_a_later_tag_is_removed(tmp_path):
    kit = tmp_path / "kit"
    (kit / "container").mkdir(parents=True)
    home = tmp_path / "home"
    state = home / ".local" / "state" / "multiplai"
    state.mkdir(parents=True)
    (state / "confine.sb").write_text("(version 1)\n")

    result = _run_install_host_state(kit=kit, home=home)
    assert result.returncode == 0, result.stderr
    assert not (state / "confine.sb").exists()
    assert "Removed" in result.stdout


def test_an_unverified_checkout_never_removes_an_installed_profile(tmp_path):
    """"container/ failed to fetch" and "this release dropped the file" look
    identical from the filesystem; only one of them may delete."""
    kit = tmp_path / "kit"
    kit.mkdir()
    home = tmp_path / "home"
    state = home / ".local" / "state" / "multiplai"
    state.mkdir(parents=True)
    (state / "confine.sb").write_text("(version 1)\n")

    result = _run_install_host_state(kit=kit, home=home, at_pin="false")
    assert result.returncode == 0, result.stderr
    assert (state / "confine.sb").exists()


def test_a_verified_profile_is_installed_mode_644(tmp_path):
    kit = tmp_path / "kit"
    (kit / "container").mkdir(parents=True)
    (kit / "container" / "confine.sb").write_text("(version 1)\n(deny default)\n")
    home = tmp_path / "home"
    home.mkdir()

    result = _run_install_host_state(kit=kit, home=home)
    assert result.returncode == 0, result.stderr
    installed = home / ".local" / "state" / "multiplai" / "confine.sb"
    assert installed.read_text() == "(version 1)\n(deny default)\n"
    assert stat.S_IMODE(installed.stat().st_mode) == 0o644
