"""Pins the host-bridge workspace declaration setup.sh writes (mktplace#15).

The gateway on the Mac confines path-taking commands (swift, xcodebuild, xcrun,
mlx-whisper, qmd) to one directory, and it **fails closed**: with no declaration
it denies them outright. It cannot take that directory from the container —
a boundary supplied by the side being confined is not a boundary — so it reads
`~/.local/state/multiplai/workspace`, which only the host can write. setup.sh is
the writer, because it already knows `$WORKSPACE` and already installs the
gateway that reads it.

**Why the block is extracted rather than run in place.** It lives inside
setup.sh's `if [ "$(uname -s)" = "Darwin" ]` arm, so nothing on Linux reaches
it: not this suite, and not the three `Linux e2e` CI jobs that do run
`./setup.sh` end to end. Faking `uname` would drag in every other Darwin path in
the script. So the test reads the real lines out of the real file and runs those
— the coupling that matters (a rename or a logic change lands here) is kept,
without pretending a Linux runner is a Mac.

What a Linux box still cannot tell you: whether `sandbox-exec` accepts the
shipped profile, and whether each bridge tool still works under it. That is six
smoke tests on the Mac, once, per tool.
"""

import subprocess
from pathlib import Path

import pytest

KIT_ROOT = Path(__file__).resolve().parents[2]
SETUP_SH = KIT_ROOT / "setup.sh"

# Anchored on the `if` that opens the block, not on the `mkdir` above it — the
# same `mkdir` line appears inside `install_host_state`, and matching the first
# one silently extracted the wrong function. Matching on source text at all is
# deliberate: a rewrite should make this test fail to find the block rather than
# pass against a stale copy.
_BLOCK_OPEN = 'if [ -n "${WORKSPACE:-}" ] && [ -d "$WORKSPACE" ]; then'


def _declaration_block() -> str:
    """The workspace-declaring lines, lifted verbatim from setup.sh."""
    lines = SETUP_SH.read_text().splitlines()
    starts = [i for i, ln in enumerate(lines) if _BLOCK_OPEN in ln]
    assert len(starts) == 1, (
        f"expected exactly one workspace-declaration block, found {len(starts)} "
        "— if it moved or was rewritten, update _BLOCK_OPEN here to match"
    )
    start = starts[0]
    indent = len(lines[start]) - len(lines[start].lstrip())
    closer = " " * indent + "fi"
    for end in range(start + 1, len(lines)):
        if lines[end] == closer:
            return "\n".join(lines[start:end + 1])
    raise AssertionError("could not find the `fi` closing the declaration block")


def _run(block: str, *, home: Path, workspace: str | None) -> subprocess.CompletedProcess:
    script = ["set -u", f'HOME={home!s}']
    if workspace is None:
        script.append("unset WORKSPACE 2>/dev/null || true")
    else:
        script.append(f'WORKSPACE="{workspace}"')
    script.append(block)
    return subprocess.run(
        ["bash", "-c", "\n".join(script)],
        capture_output=True, text=True, env={"PATH": "/usr/bin:/bin", "HOME": str(home)},
    )


def test_the_block_is_still_where_the_test_thinks_it_is():
    block = _declaration_block()
    assert "local/state/multiplai/workspace" in block
    assert "$WORKSPACE" in block
    # The `mkdir` inside install_host_state must not have been swept in — that
    # is exactly the mis-extraction this anchor was chosen to avoid.
    assert "local/bin" not in block


def test_declares_an_existing_workspace(tmp_path):
    ws = tmp_path / "knowhere"
    ws.mkdir()
    home = tmp_path / "home"
    home.mkdir()

    result = _run(_declaration_block(), home=home, workspace=str(ws))
    assert result.returncode == 0, result.stderr

    decl = home / ".local" / "state" / "multiplai" / "workspace"
    assert decl.is_file()
    # Exactly one line, the absolute path — the gateway reads `head -n 1` and
    # refuses anything that is not an existing absolute path.
    assert decl.read_text() == f"{ws}\n"


def test_rewrites_a_stale_declaration(tmp_path):
    """A workspace that moved must move its declaration, or the gateway keeps
    confining builds to a directory the user no longer works in."""
    home = tmp_path / "home"
    decl_dir = home / ".local" / "state" / "multiplai"
    decl_dir.mkdir(parents=True)
    (decl_dir / "workspace").write_text("/old/workspace\n")

    ws = tmp_path / "new-place"
    ws.mkdir()
    result = _run(_declaration_block(), home=home, workspace=str(ws))
    assert result.returncode == 0, result.stderr
    assert (decl_dir / "workspace").read_text() == f"{ws}\n"


def test_warns_and_writes_nothing_when_workspace_is_unset(tmp_path):
    home = tmp_path / "home"
    home.mkdir()

    result = _run(_declaration_block(), home=home, workspace=None)
    assert result.returncode == 0, result.stderr

    decl = home / ".local" / "state" / "multiplai" / "workspace"
    assert not decl.exists(), "an undeclared workspace must not be declared as empty"
    assert "WARNING" in result.stdout
    # The warning has to name what stops working, or it reads as noise.
    assert "swift" in result.stdout and "xcodebuild" in result.stdout


def test_warns_when_workspace_does_not_exist(tmp_path):
    home = tmp_path / "home"
    home.mkdir()

    result = _run(_declaration_block(), home=home, workspace=str(tmp_path / "nope"))
    assert result.returncode == 0, result.stderr
    assert not (home / ".local" / "state" / "multiplai" / "workspace").exists()
    assert "WARNING" in result.stdout


def test_a_workspace_with_spaces_survives_the_round_trip(tmp_path):
    ws = tmp_path / "my knowhere (main)"
    ws.mkdir()
    home = tmp_path / "home"
    home.mkdir()

    result = _run(_declaration_block(), home=home, workspace=str(ws))
    assert result.returncode == 0, result.stderr
    decl = home / ".local" / "state" / "multiplai" / "workspace"
    assert decl.read_text() == f"{ws}\n"


def test_confine_profile_is_installed_alongside_the_gateway():
    """The gateway references `confine.sb`; a release where the gateway ships
    and the profile does not is the version skew install_host_state exists to
    prevent."""
    text = SETUP_SH.read_text()
    darwin = text[text.find('if [ "$(uname -s)" = "Darwin" ]'):]
    assert "install_host_tool container-build-gateway.sh" in darwin
    assert "install_host_state confine.sb" in darwin


@pytest.mark.parametrize("mode_line", ['chmod 644 "$HOME/.local/state/multiplai/workspace"'])
def test_declaration_is_not_group_or_world_writable(mode_line):
    """A world-writable declaration would let any local process retarget the
    jail, which is the one thing the host-owned location is for."""
    assert mode_line in SETUP_SH.read_text()
