"""Pins the launch-time overlay staleness warning in `claude.sh`.

Overlay images (built by multiplai-container's `build-overlay.sh`) carry the
base image's name and ID as labels; the launcher compares the recorded ID
against the current base and warns — warn-only, never fatal — when the overlay
was built on an older base. The contract pinned here:

* A stale overlay prints the warning and the launch still proceeds.
* An up-to-date overlay, a label-less base image, and an image whose labels
  map lacks the overlay labels all stay silent — and never print Go's
  literal `<no value>`.
* Both labels are required. A recorded base ID with no recorded base *name*
  is label-schema drift; comparing that ID against a guessed default name
  would produce a spurious or missed warning, so the launcher must skip the
  check entirely — and never look the default name up.
* A recorded base name that no longer resolves locally stays silent (the
  warn-only design: never cost a launch).
* The two label reads are one combined `docker image inspect` call.

Same technique as `test_claude_sh_env.py`, whose `kit` fixture this reuses: a
stub `docker` first on `PATH`. This stub additionally answers
`image inspect -f`: the combined-template read returns the configured label
line, and the `{{.Id}}` read on the recorded base name returns the configured
current ID (or fails), recording which name was asked about.
"""

from test_claude_sh_env import kit  # noqa: F401 — `kit` is a fixture

# Mirrors DOCKER_STUB in test_claude_sh_env.py, with `image inspect -f` made
# answerable. The combined label template is recognised by its
# `base-image-id` literal; any other `-f` on `image inspect` is the launcher
# resolving the current base ID from the recorded name, so the stub records
# that name to $BASE_LOOKUPS_OUT — a test can then assert the lookup used the
# label (or never happened). `run` still records argv so a test can assert
# the warning never cost the launch.
DOCKER_STUB_TEMPLATE = """\
#!/bin/bash
if [ "$1" = "image" ] && [ "$2" = "inspect" ]; then
    if [ "$3" = "-f" ]; then
        case "$4" in
            *base-image-id*)
                printf '%s\\n' "{labels}"
                exit 0 ;;
            *)
                printf '%s\\n' "$5" >> "$BASE_LOOKUPS_OUT"
                if [ "{base_present}" = "1" ]; then
                    printf '%s\\n' "{current_base_id}"
                    exit 0
                fi
                exit 1 ;;
        esac
    fi
    exit 0
fi
case "$1" in
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

OVERLAY_IMAGE = "claude-multiplai-myproject:local"


def _docker(kit, *, labels, base_present=True, current_base_id=""):
    """Configure the stub: `labels` is the combined `id|name` line the
    launcher's label read returns ('' for an image with no labels map)."""
    stub = kit.stub_dir / "docker"
    stub.write_text(DOCKER_STUB_TEMPLATE.format(
        labels=labels,
        base_present="1" if base_present else "0",
        current_base_id=current_base_id,
    ))
    stub.chmod(0o755)


def _launch_overlay(kit):
    kit.append_env(f'IMAGE_NAME="{OVERLAY_IMAGE}"\n')
    lookups = kit.root / "base-lookups.txt"
    lookups.write_text("")
    result = kit.launch("--shell", "-c", "true", BASE_LOOKUPS_OUT=str(lookups))
    return result, lookups.read_text().splitlines()


def test_stale_overlay_warns_and_still_launches(kit):
    """Behind-the-base is a nudge, not an error: the overlay still works."""
    _docker(kit, labels="sha256:old|claude-multiplai:local",
            current_base_id="sha256:new")

    result, _ = _launch_overlay(kit)

    assert "WARNING" in result.output
    assert result.status == 0
    assert result.argv != [], "the warning cost the launch"


def test_warning_names_the_overlay_and_the_remediation(kit):
    """The reader needs which image is behind and the one command that fixes
    every registered overlay at once."""
    _docker(kit, labels="sha256:old|claude-multiplai:local",
            current_base_id="sha256:new")

    result, _ = _launch_overlay(kit)

    assert OVERLAY_IMAGE in result.output
    assert "build.sh" in result.output
    assert "overlays.conf" in result.output


def test_current_overlay_stays_silent(kit):
    _docker(kit, labels="sha256:same|claude-multiplai:local",
            current_base_id="sha256:same")

    result, lookups = _launch_overlay(kit)

    assert "WARNING" not in result.output
    assert lookups == ["claude-multiplai:local"], \
        "the current-base lookup must use the recorded name, exactly once"


def test_label_less_base_image_is_skipped(kit):
    """Base images carry no overlay labels; the check must be a no-op for
    them, and the nil-Labels guard must never leak Go's `<no value>`."""
    _docker(kit, labels="")

    result, lookups = _launch_overlay(kit)

    assert "WARNING" not in result.output
    assert "<no value>" not in result.output
    assert lookups == [], "looked up a base for an image with no labels"


def test_other_labels_without_overlay_labels_are_skipped(kit):
    """A non-nil labels map missing both overlay keys renders as a bare
    separator — still not an overlay."""
    _docker(kit, labels="|")

    result, lookups = _launch_overlay(kit)

    assert "WARNING" not in result.output
    assert lookups == []


def test_missing_name_label_skips_instead_of_guessing(kit):
    """A recorded base ID with no recorded base name is label-schema drift.
    Comparing that ID against a guessed default name would fabricate a
    spurious (or mask a real) warning, so the launcher must not look the
    default up at all."""
    _docker(kit, labels="sha256:old|", current_base_id="sha256:new")

    result, lookups = _launch_overlay(kit)

    assert "WARNING" not in result.output
    assert lookups == [], "guessed a base name the overlay never recorded"


def test_deleted_base_image_stays_silent(kit):
    """The recorded base no longer exists locally: nothing to compare, and
    warn-only means this can never block or noise up a launch."""
    _docker(kit, labels="sha256:old|claude-multiplai:renamed",
            base_present=False)

    result, lookups = _launch_overlay(kit)

    assert "WARNING" not in result.output
    assert result.status == 0
    assert result.argv != []
    assert lookups == ["claude-multiplai:renamed"]
