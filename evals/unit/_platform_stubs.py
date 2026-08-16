"""`uname` stubs shared by the launcher tests.

`claude.sh` branches on `$(uname)` in several places — App mode is macOS-only,
the Keychain warnings split Mac from non-Mac — so a test that means to exercise
one branch has to pin the answer. Left unpinned, the test asserts whatever the
developer's laptop happens to be: green on Linux CI, red on a Mac, and neither
result says anything about the code.

These two functions used to live in the two test modules that needed them, one
each. `test_claude_sh_crossplatform.py` already imports from
`test_claude_sh_env.py` (for the `kit` fixture), so the reverse import would
close a cycle — which is why `test_claude_sh_env.py` could not reach
`_pretend_linux` and two of its tests were passing on Linux for the wrong
reason. A third module both can import breaks the cycle.
"""


def _pretend_macos(kit):
    """Pin `uname` to Darwin so the macOS branch is taken on any dev host."""
    stub = kit.stub_dir / "uname"
    stub.write_text("#!/bin/sh\nprintf 'Darwin\\n'\n")
    stub.chmod(0o755)


def _pretend_linux(kit):
    """Pin `uname` to Linux so the non-Darwin branch is taken on any dev host."""
    stub = kit.stub_dir / "uname"
    stub.write_text("#!/bin/sh\nprintf 'Linux\\n'\n")
    stub.chmod(0o755)
