"""Pins the session network: every session and hub driver joins `multiplai`.

On Docker's default `bridge`, OrbStack resolves `<container>.orb.local` but
connections from the Mac hang, so a dev server inside a session could not be
previewed. The launcher now creates a user-defined network once and passes
`--network multiplai` on the interactive and driver runs.

Same technique as `test_claude_sh_env.py`, whose `kit` fixture this reuses: a
stub `docker` first on `PATH`, here extended to log its `network` calls and to
report the network as present or absent per test.
"""

from test_claude_sh_crossplatform import _driver_launch
from test_claude_sh_env import kit  # noqa: F401 — `kit` is a fixture

# DOCKER_STUB from test_claude_sh_env.py, plus a `network` verb. `inspect`
# succeeds once the marker file exists; `create` makes it exist unless the test
# says creation fails. Every `network` call is appended to a log.
DOCKER_STUB_TEMPLATE = """\
#!/bin/bash
case "$1" in
    image) exit 0 ;;
    network)
        echo "$*" >> "{log}"
        case "$2" in
            inspect) [ -e "{marker}" ] && exit 0; exit 1 ;;
            create) {create} ;;
        esac
        exit 0
        ;;
    run)
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


def _docker(kit, *, exists, create_works=True):
    log = kit.root / "network.log"
    marker = kit.root / "network.exists"
    if exists:
        marker.write_text("")
    create = f'touch "{marker}"; exit 0' if create_works else "exit 1"
    stub = kit.stub_dir / "docker"
    stub.write_text(DOCKER_STUB_TEMPLATE.format(log=log, marker=marker, create=create))
    stub.chmod(0o755)
    return log


def _network_arg(argv):
    for i, a in enumerate(argv):
        if a == "--network":
            return argv[i + 1]
        if a.startswith("--network="):
            return a.partition("=")[2]
    return None


def test_session_joins_the_multiplai_network(kit):
    _docker(kit, exists=True)

    result = kit.launch("--shell", "-c", "true")

    assert result.status == 0, result.output
    assert _network_arg(result.argv) == "multiplai"


def test_hub_driver_joins_the_multiplai_network(kit):
    """The driver composes its own `docker run` at a separate call site."""
    _docker(kit, exists=True)

    result = _driver_launch(kit)

    assert result.status == 0, result.output
    assert result.argv[result.argv.index("--name") + 1].startswith("claude-drv-")
    assert _network_arg(result.argv) == "multiplai"


def test_existing_network_is_not_recreated(kit):
    log = _docker(kit, exists=True)

    kit.launch("--shell", "-c", "true")

    assert "network create multiplai" not in log.read_text()


def test_missing_network_is_created_then_joined(kit):
    log = _docker(kit, exists=False)

    result = kit.launch("--shell", "-c", "true")

    assert result.status == 0, result.output
    assert "network create multiplai" in log.read_text()
    assert _network_arg(result.argv) == "multiplai"


def test_a_lost_create_race_still_launches(kit):
    """Another launcher created the network between our inspect and create:
    our create fails, but the network exists, so the launch must go ahead."""
    log = _docker(kit, exists=False, create_works=False)
    marker = kit.root / "network.exists"
    # First inspect fails; create fails; by the second inspect it exists.
    stub = kit.stub_dir / "docker"
    stub.write_text(stub.read_text().replace(
        "create) exit 1 ;;", f'create) touch "{marker}"; exit 1 ;;'))

    result = kit.launch("--shell", "-c", "true")

    assert result.status == 0, result.output
    assert "network create multiplai" in log.read_text()
    assert _network_arg(result.argv) == "multiplai"


def test_create_failure_refuses_to_launch(kit):
    _docker(kit, exists=False, create_works=False)

    result = kit.launch("--shell", "-c", "true")

    assert result.status != 0
    assert "could not create the Docker network 'multiplai'" in result.output
    assert result.argv == [], "a container was launched without its network"
