"""Pins the three-way Docker state the launcher and `setup.sh` must agree on.

Whether `docker` is **installed** is a durable property of the host. Whether the
**daemon is running** is not. Collapsing the two produced a contradiction
between the two scripts a user runs minutes apart:

* `setup.sh` tested `command -v docker` AND `docker info`, so a stopped daemon
  read as "no Docker" and it printed "setting up for bare mode".
* `claude.sh` tested `command -v docker` alone, so the same host went to
  container mode anyway, failed `docker image inspect`, and said
  `Docker image not found. Build it first: cd container && ./build.sh` — which
  is not the problem, and a ten-minute build cannot fix it.

The contract now:

* **No docker binary** → bare mode. A host with no Docker has chosen the lower
  rung of the install ladder and the launch says so, not an error.
* **Binary present, daemon down** → refuse, and name the daemon. Silently
  dropping to bare mode here would be a sandbox downgrade nobody asked for, so
  the message carries both exits: start Docker, or `--local` on purpose.
* **Daemon up, image missing** → the old message, which is correct only here.

`docker info` is asked ONLY after `docker image inspect` has already failed, so
a healthy launch still pays a single daemon round-trip. Driver mode has no bare
fallback for either cause and so must separate them at the door.

Same technique as `test_claude_sh_env.py`, whose `kit` fixture this reuses: a
stub `docker` first on `PATH`, with its `info` and `image` exit statuses driven
per test.
"""

import os
from pathlib import Path

from test_claude_sh_env import kit  # noqa: F401 — `kit` is a fixture

# Mirrors DOCKER_STUB in test_claude_sh_env.py, with `info` and `image` made
# failable. `run` still records argv so a test can assert a container was never
# launched, which is the difference between "refused" and "refused loudly".
DOCKER_STUB_TEMPLATE = """\
#!/bin/bash
case "$1" in
    info) exit {info_status} ;;
    image) exit {image_status} ;;
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


def _docker(kit, *, daemon_up=True, image_present=True):
    stub = kit.stub_dir / "docker"
    stub.write_text(DOCKER_STUB_TEMPLATE.format(
        info_status=0 if daemon_up else 1,
        image_status=0 if image_present else 1,
    ))
    stub.chmod(0o755)


def _path_without_docker(kit, tmp_path):
    """A PATH carrying everything the launcher needs and no `docker` at all.

    Deleting the stub is not enough: the developer's own docker is further down
    the inherited PATH, so on a machine with Docker installed this case would
    quietly become the daemon-down case instead. Mirror every other binary into
    a shadow directory and leave that one out.
    """
    (kit.stub_dir / "docker").unlink()
    shadow = tmp_path / "path-without-docker"
    shadow.mkdir(exist_ok=True)
    for directory in os.environ.get("PATH", "/usr/bin:/bin").split(os.pathsep):
        source = Path(directory)
        if not source.is_dir():
            continue
        for entry in source.iterdir():
            if entry.name == "docker":
                continue
            link = shadow / entry.name
            if link.exists() or link.is_symlink():
                continue
            try:
                link.symlink_to(entry)
            except OSError:
                pass
    return f"{kit.stub_dir}{os.pathsep}{shadow}"


# --- container mode ---------------------------------------------------------


def test_a_stopped_daemon_names_the_daemon_not_a_missing_image(kit):
    """The build it used to recommend cannot fix a daemon that is not running,
    and sends the reader ten minutes in the wrong direction."""
    _docker(kit, daemon_up=False, image_present=False)

    result = kit.launch("--shell", "-c", "true")

    assert result.status != 0
    assert "daemon is not reachable" in result.output
    assert "build.sh" not in result.output, "told to build an image it may already have"
    assert result.argv == [], "a container was launched with no daemon to run it"


def test_a_stopped_daemon_offers_both_ways_out(kit):
    """Starting Docker and running unsandboxed on purpose are both valid — a
    message naming neither leaves the reader stuck."""
    _docker(kit, daemon_up=False, image_present=False)

    result = kit.launch("--shell", "-c", "true")

    assert "--local" in result.output
    assert "systemctl start docker" in result.output or "Docker Desktop" in result.output


def test_a_stopped_daemon_does_not_fall_back_to_bare_mode(kit):
    """Bare mode is a rung you choose. Dropping to it because Docker Desktop was
    still starting would swap the sandbox out from under a session silently."""
    _docker(kit, daemon_up=False, image_present=False)

    result = kit.launch("--shell", "-c", "true")

    assert result.status != 0
    assert result.bare_env == {}, "fell through to a bare launch"


def test_a_missing_image_on_a_live_daemon_still_says_build_it(kit):
    """The old message is right for exactly this case and must survive."""
    _docker(kit, daemon_up=True, image_present=False)

    result = kit.launch("--shell", "-c", "true")

    assert result.status != 0
    assert "not found" in result.output
    assert "build.sh" in result.output
    assert "daemon is not reachable" not in result.output


def test_a_healthy_launch_never_asks_docker_info(kit, tmp_path):
    """`docker info` is a daemon round-trip on every launch if it is asked up
    front. It is only ever a diagnosis, so it runs after the failure."""
    log = tmp_path / "docker-calls.txt"
    stub = kit.stub_dir / "docker"
    stub.write_text(
        "#!/bin/bash\n"
        f'printf \'%s\\n\' "$1" >> "{log}"\n'
        + DOCKER_STUB_TEMPLATE.format(info_status=0, image_status=0).split("\n", 1)[1]
    )
    stub.chmod(0o755)

    result = kit.launch("--shell", "-c", "true")

    assert result.status == 0, result.output
    assert "info" not in log.read_text().split(), "paid a daemon round-trip to diagnose nothing"


# --- bare mode --------------------------------------------------------------


def test_no_docker_binary_still_selects_bare_mode(kit, tmp_path):
    """The other half of the split. A host with no Docker has chosen the lower
    rung; saying so is not an error and must not become one."""
    path = _path_without_docker(kit, tmp_path)

    result = kit.launch("--shell", "-c", "true", PATH=path)

    assert result.status == 0, result.output
    assert "Bare mode (no Docker)" in result.output
    assert result.bare_env != {}, "no bare launch happened"


# --- driver mode ------------------------------------------------------------


def test_driver_mode_names_a_missing_binary(kit, tmp_path):
    """Driver mode has no bare fallback, so both causes are fatal — but they
    still send the reader to different fixes."""
    path = _path_without_docker(kit, tmp_path)

    result = kit.launch("driver", "--sid", "new", "--port", "8080", PATH=path)

    assert result.status != 0
    assert "no docker binary" in result.output


def test_driver_mode_names_a_stopped_daemon(kit):
    _docker(kit, daemon_up=False)

    result = kit.launch("driver", "--sid", "new", "--port", "8080")

    assert result.status != 0
    assert "daemon is not reachable" in result.output
    assert "no docker binary" not in result.output
