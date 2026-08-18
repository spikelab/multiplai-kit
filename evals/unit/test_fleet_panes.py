"""Pins `dotfiles/scripts/fleet-panes.sh` — which pane holds which container.

The `multiplai-context` plugin can never observe this. `record_event()` runs
*inside* the container and tmux runs on the Mac, so `$TMUX_PANE` there is not
merely absent — it is unknowable. Every tmux fact has to be written host-side
and joined at render time, which is the shape `live_containers.json` already
has.

**This used to live in `claude.sh` and used to be a launch-time record**, and
that is the change this file exists to pin. `write_pane_map` wrote the entry for
the pane it was launching in, then carried every other tab forward by `grep`-ing
the file it had written last time. A map built that way is a chain: an entry can
be preserved but never *acquired*, so a container already running when the file
was created could never appear in it — nothing left alive knew which pane it was
in. Three of four live containers were in that state on 2026-08-08.

The launcher now stamps the container name onto the pane as a pane-scoped tmux
user option (`@cc`), so the whole fleet is one `tmux list-panes -a` away and the
map became a cache of a current reading. What that buys, and what each of these
tests is protecting:

* a pane missing yesterday appears the moment this runs again — no migration,
  no repair path, and `fleet-watch` re-runs it every redraw;
* a **renamed tab keeps its identity**, because the stamp is on the pane and not
  on its name. A convention (`cc-` prefixes on tab names) could not do this, and
  degrades silently the one time someone types `scratch`;
* an empty `@cc` *is* the definition of a shell pane, so there is nothing to
  pattern-match and nothing to remember to honour.

The invariants a future edit breaks at its peril:

* **an entry survives only while `docker ps` lists its container.** The stamp
  outlives the session — the pane is still there — so this is the only thing
  that retires a tab whose work is over;
* **the argument is the exception to that**, and it is what the pre-run call
  from the launcher passes: at that instant the container does not exist yet;
* **another tmux server's entries are carried forward untouched.** Pane ids are
  recycled per server, so `%12` means nothing without the socket path that
  issued it. Dropping them lets a board on one server retire the other's tabs;
  relabelling them credits one server's `%12` to another's;
* **no `$TMUX`, no write.** `list-panes -a` enumerates one server, and a
  process outside tmux has no claim on which — writing what it saw would empty
  the map for every reader;
* **it never prints.** It runs on the launch path and inside a redraw loop.

`TestOnARealTmuxServer` is the half a stub cannot pin, because a stub answers
`list-panes` with whatever the test staged and so exercises the parsing while
never touching the format string that produced it: that `set-option -p`
round-trips through `#{@cc}` at all, that the stamp survives `rename-window`,
that a `|` in a stamp cannot shift the fields after it, and that
`#{automatic-rename}` renders as `0`/`1` in a format rather than `off`/`on`.
Verified against tmux 3.4.
"""

import json
import os
import shutil
import subprocess
import time

import pytest

from conftest import KIT_ROOT
SCRIPT = KIT_ROOT / "dotfiles" / "scripts" / "fleet-panes.sh"

# Answers the two questions the script asks, and records them. `list-panes`
# returns whatever the test staged, one record per line, in the field order the
# script's own `-F` requests: pane | @cc | automatic-rename | window | session.
TMUX_STUB = """\
#!/bin/bash
printf '%s\\n' "$*" >> "$TMUX_LOG"
[ -n "${TMUX_FAIL_STUB:-}" ] && exit 1
case "$1" in
    display-message) printf '%s\\n' "${TMUX_SERVER_STUB-/private/tmp/tmux-501/default}" ;;
    list-panes)      [ -n "${TMUX_PANES_STUB:-}" ] && printf '%s\\n' "$TMUX_PANES_STUB" ;;
esac
exit 0
"""

DOCKER_STUB = """\
#!/bin/bash
case "$1" in
    ps)
        [ -n "${PS_NAMES:-}" ] && printf '%s\\n' "$PS_NAMES"
        exit "${PS_STATUS:-0}"
        ;;
esac
exit 0
"""

SERVER = "/private/tmp/tmux-501/default"


class Panes:
    """A copy of the script, with stub `tmux` and `docker` in front of it.

    Copied rather than run in place because the workspace fallback it reads is
    `../.workspace` *relative to the script* — the point of that path is that it
    travels with the install, so a test pointing at the real checkout would be
    testing this machine.
    """

    def __init__(self, tmp_path):
        self.scripts = tmp_path / "dotfiles" / "scripts"
        self.scripts.mkdir(parents=True)
        shutil.copy(SCRIPT, self.scripts / "fleet-panes.sh")
        self.marker = tmp_path / "dotfiles" / ".workspace"

        self.stub_dir = tmp_path / "bin"
        self.stub_dir.mkdir()
        for name, body in (("tmux", TMUX_STUB), ("docker", DOCKER_STUB)):
            (self.stub_dir / name).write_text(body)
            (self.stub_dir / name).chmod(0o755)

        self.workspace = tmp_path / "ws"
        self.data = self.workspace / ".multiplai" / "data"
        self.data.mkdir(parents=True)
        self.panes = self.data / "tmux" / "panes.json"
        self.log = tmp_path / "tmux.log"
        self.log.write_text("")

    def run(self, *args, panes=(), names=(), inside=True, **extra):
        env = {
            "PATH": f"{self.stub_dir}:{os.environ.get('PATH', '/usr/bin:/bin')}",
            "HOME": str(self.scripts),
            "WORKSPACE": str(self.workspace),
            "TMUX_LOG": str(self.log),
            "TMUX_PANES_STUB": "\n".join(panes),
            "PS_NAMES": "\n".join(names),
        }
        if inside:
            env["TMUX"] = f"{SERVER},1234,0"
        env.update({k: v for k, v in extra.items() if v is not None})
        return subprocess.run(
            ["bash", str(self.scripts / "fleet-panes.sh"), *args],
            capture_output=True, text=True, env=env, timeout=20,
        )

    def map(self):
        return json.loads(self.panes.read_text())

    def entries(self):
        return self.map()["panes"]

    def seed(self, *entries, server=SERVER):
        """Pre-existing entries, in the shape this script writes.

        One line per entry is not cosmetic: the foreign-server merge re-reads
        this file with nothing but `grep`, because `jq` is optional on a Mac and
        this runs on the launch path.
        """
        self.panes.parent.mkdir(parents=True, exist_ok=True)
        lines = ",\n".join(
            f'    "{name}": {{"pane": "{pane}", "server": "{server}", '
            f'"window": "{window}", "session": "work", '
            f'"at": "2026-08-06T21:00:00Z"}}'
            for name, pane, window in entries
        )
        self.panes.write_text(
            '{\n  "version": 1,\n  "observed_at": "2026-08-06T21:00:00Z",\n'
            '  "observer": "host",\n  "kind": "tmux",\n'
            f'  "server": "{SERVER}",\n'
            f'  "panes": {{\n{lines}\n  }}\n}}\n'
        )


@pytest.fixture
def panes(tmp_path):
    return Panes(tmp_path)


def rec(pane, cc="", auto="0", window="", session="work"):
    """One `list-panes -a` record, in the script's own field order."""
    return f"{pane}|{cc}|{auto}|{window}|{session}"


# --- what makes a pane an agent -----------------------------------------------

def test_a_stamped_pane_whose_container_runs_is_an_entry(panes):
    """The load-bearing one. Everything else here is a way of not writing this."""
    panes.run(panes=[rec("%12", cc="cc-p-08015414", window="inbox-cleanup")],
              names=["cc-p-08015414"])

    entry = panes.entries()["cc-p-08015414"]

    assert entry["pane"] == "%12"
    assert entry["window"] == "inbox-cleanup"
    assert entry["session"] == "work"
    assert entry["at"].endswith("Z")


def test_an_unstamped_pane_is_a_shell_and_is_not_an_entry(panes):
    """The whole test for "is this an agent" — no prefix to honour, no window
    name to pattern-match. Most panes on a machine are this one."""
    panes.run(panes=[rec("%1", cc=""), rec("%2", cc="cc-p-01")],
              names=["cc-p-01"])

    assert list(panes.entries()) == ["cc-p-01"]


def test_a_stamp_naming_a_container_that_is_gone_is_dropped(panes):
    """`--rm` reaps the container when the session ends; the pane and its stamp
    stay. `docker ps` is what retires the tab, and without this check the board
    would go on labelling a session that no longer exists."""
    panes.run(panes=[rec("%1", cc="cc-p-dead"), rec("%2", cc="cc-p-01")],
              names=["cc-p-01"])

    assert list(panes.entries()) == ["cc-p-01"]


def test_a_pane_with_no_usable_id_records_nothing(panes):
    """The map answers "which pane". A record that cannot is worse than a
    missing one — it would join to whatever a blank pane id matched."""
    panes.run(panes=[rec("", cc="cc-p-01"), rec("nonsense", cc="cc-p-02")],
              names=["cc-p-01", "cc-p-02"])

    assert panes.entries() == {}


def test_a_stamp_that_could_break_the_json_is_dropped_not_escaped(panes):
    """`@cc` is a tmux user option and anyone can set it to anything, and it
    becomes a JSON *key*. A lossy map beats an unparseable one, which disables
    the board for every reader rather than for one tab."""
    panes.run(panes=[rec("%1", cc='ev"il'), rec("%2", cc="cc-p-01")],
              names=['ev"il', "cc-p-01"])

    assert list(panes.entries()) == ["cc-p-01"]


# --- the label ----------------------------------------------------------------

def test_an_auto_named_window_is_not_recorded_as_a_label(panes):
    """With `automatic-rename` on, `#{window_name}` is whatever tmux derived
    from the running process — `bash` in a fresh window, `docker` mid-session.
    Recording it would put `project@docker` on the board; empty is honest and
    lets the reader fall back to the label it already knows how to build."""
    panes.run(panes=[rec("%1", cc="cc-p-01", auto="1", window="docker")],
              names=["cc-p-01"])

    assert panes.entries()["cc-p-01"]["window"] == ""


def test_the_off_spelling_is_accepted_as_well_as_the_numeric_one(panes):
    """tmux renders the option as `0`/`1` inside a format (verified on 3.4), but
    `off` is what every other read in the kit sees. Both mean pinned."""
    panes.run(panes=[rec("%1", cc="cc-p-01", auto="off", window="kit-review")],
              names=["cc-p-01"])

    assert panes.entries()["cc-p-01"]["window"] == "kit-review"


def test_an_unrecognised_rename_flag_declines_the_label(panes):
    """The safe direction for a value this script did not expect. No label falls
    back to the container name; a wrong one puts `zsh` on the board with the
    same confidence as a handle someone chose."""
    panes.run(panes=[rec("%1", cc="cc-p-01", auto="???", window="zsh")],
              names=["cc-p-01"])

    assert panes.entries()["cc-p-01"]["window"] == ""


def test_a_window_name_that_could_break_the_json_is_stripped(panes):
    """Unlike a container name, a window name is arbitrary user text. Stripped
    rather than escaped: this is a label, and a lossy label beats a file no
    reader can parse."""
    panes.run(panes=[rec("%1", cc="cc-p-01", window='ev"il\\one')],
              names=["cc-p-01"])

    assert panes.entries()["cc-p-01"]["window"] == "evilone"


# --- the container that does not exist yet ------------------------------------

def test_the_named_container_is_recorded_before_it_is_running(panes):
    """What the argument is for. The launcher's pre-run call happens *before*
    `docker run`, so the cross-check above would drop the one entry that write
    exists to create — the session whose SessionStart is seconds away."""
    panes.run("cc-p-new", panes=[rec("%12", cc="cc-p-new", window="kit")],
              names=["cc-p-other"])

    assert panes.entries()["cc-p-new"]["pane"] == "%12"


def test_an_unstamped_launcher_falls_back_to_its_own_pane(panes):
    """The degradation path for a tmux too old for `set-option -p`, or a stamp
    that failed for any other reason. The launcher still knows `$TMUX_PANE`, so
    it does not vanish from its own map — this is exactly today's behaviour, and
    the reason an old tmux loses nothing it already had."""
    panes.run("cc-p-new",
              panes=[rec("%7", cc="", auto="off", window="kit-review")],
              names=[], TMUX_PANE="%7")

    entry = panes.entries()["cc-p-new"]

    assert entry["pane"] == "%7"
    assert entry["window"] == "kit-review"


def test_the_fallback_does_not_fire_when_the_stamp_landed(panes):
    """One entry, not two. The stamped record is the real one — it carries the
    pane the stamp is actually on, which on a take-back relaunch need not be
    `$TMUX_PANE` at all."""
    panes.run("cc-p-new",
              panes=[rec("%3", cc="cc-p-new", window="kit")],
              names=[], TMUX_PANE="%7")

    assert list(panes.entries()) == ["cc-p-new"]
    assert panes.entries()["cc-p-new"]["pane"] == "%3"


# --- more than one tmux server ------------------------------------------------

def test_the_query_replaces_everything_this_server_said_before(panes):
    """The point of the rewrite. The old map carried entries forward by `grep`,
    so it could only ever preserve — a pane it had never seen could not be
    acquired, and a pane that had gone away could only be retired by `docker ps`
    noticing. A live query is the current truth about this server, whole."""
    panes.seed(("cc-p-old", "%3", "stale-label"))

    panes.run(panes=[rec("%3", cc="cc-p-old", window="fresh-label")],
              names=["cc-p-old"])

    assert panes.entries()["cc-p-old"]["window"] == "fresh-label"


def test_another_servers_entry_is_carried_forward_untouched(panes):
    """`list-panes -a` only ever sees its own server. Dropping what it cannot
    see would let a board on one tmux server retire every tab belonging to the
    other — which is worse than the launch-time map it replaced."""
    other = "/private/tmp/tmux-501/second"
    panes.seed(("cc-w-99", "%3", "their-tab"), server=other)

    panes.run(panes=[rec("%1", cc="cc-p-01")], names=["cc-p-01", "cc-w-99"])

    entry = panes.entries()["cc-w-99"]

    assert entry["pane"] == "%3"
    assert entry["window"] == "their-tab"
    assert entry["server"] == other, "a carried entry was relabelled as ours"


def test_a_carried_entry_is_still_bound_by_docker_ps(panes):
    """The other server's entries get no special exemption — the rule that
    bounds the file is the same one."""
    other = "/private/tmp/tmux-501/second"
    panes.seed(("cc-w-99", "%3", "their-tab"), server=other)

    panes.run(panes=[rec("%1", cc="cc-p-01")], names=["cc-p-01"])

    assert list(panes.entries()) == ["cc-p-01"]


def test_our_own_stale_entry_is_not_resurrected_as_a_foreign_one(panes):
    """The merge reads the file it is replacing, so it has to tell "written by
    another server" from "written by us, last time". A pane of ours that is gone
    from the query is gone — carrying it back would restore precisely the
    can-never-be-corrected staleness this rewrite removes."""
    panes.seed(("cc-p-ghost", "%3", "old-tab"))

    panes.run(panes=[rec("%1", cc="cc-p-01")], names=["cc-p-01", "cc-p-ghost"])

    assert list(panes.entries()) == ["cc-p-01"]


# --- the reading itself -------------------------------------------------------

def test_the_reading_says_what_it_is_and_which_server_issued_it(panes):
    """`kind` and `observer` for the reason the roster carries them: a reader
    must be able to refuse a payload it cannot interpret. `server` for a sharper
    one — pane ids are recycled per tmux server, so a `viewed` marker written
    against one must not be applied to a pane id from another."""
    panes.run(panes=[rec("%1", cc="cc-p-01")], names=["cc-p-01"])

    m = panes.map()

    assert m["version"] == 1
    assert m["kind"] == "tmux"
    assert m["observer"] == "host"
    assert m["server"] == SERVER
    assert m["observed_at"].endswith("Z") and len(m["observed_at"]) == 20
    assert m["panes"]["cc-p-01"]["server"] == SERVER


def test_the_write_is_atomic():
    """A reader in another container must never see a half-written file, so the
    map is built in a scratch file and renamed into place."""
    body = SCRIPT.read_text()

    assert "mv -f" in body
    assert '> "$tmp"' in body
    assert '> "$data_dir/tmux/panes.json"' not in body


def test_the_whole_server_is_read_in_one_call(panes):
    """The board runs this every redraw, so the cost is a per-tick cost. One
    `list-panes -a` answers it for every pane at once; a `display-message` per
    pane would put the fleet's size into the redraw budget."""
    panes.run(panes=[rec("%1", cc="cc-p-01"), rec("%2", cc="cc-p-02")],
              names=["cc-p-01", "cc-p-02"])

    assert sum(1 for ln in panes.log.read_text().splitlines()
               if ln.startswith("list-panes")) == 1


# --- when it must not act -----------------------------------------------------

def test_outside_tmux_nothing_is_written(panes):
    """The guard `fleet-watch` needs most: a board in a plain terminal has no
    claim on which tmux server `list-panes -a` would find, and writing what it
    saw would empty the map for every reader."""
    panes.seed(("cc-p-01", "%3", "keep-me"))

    result = panes.run(panes=[rec("%1", cc="cc-p-01")], names=["cc-p-01"],
                       inside=False)

    assert panes.entries()["cc-p-01"]["window"] == "keep-me"
    assert result.returncode == 0


def test_no_data_dir_means_no_map_and_no_complaint(panes):
    """No plugin, no registry, nothing to join a pane id to."""
    shutil.rmtree(panes.data)

    result = panes.run(panes=[rec("%1", cc="cc-p-01")], names=["cc-p-01"])

    assert not panes.data.exists()
    assert result.returncode == 0


def test_an_unresolvable_workspace_is_a_silent_no_op(panes):
    """Unlike `fleet-watch`, which a person runs and reads. This one runs on the
    launch path and inside a redraw loop, so it has nowhere to complain to."""
    result = panes.run(panes=[rec("%1", cc="cc-p-01")], names=["cc-p-01"],
                       WORKSPACE="")

    assert result.returncode == 0
    assert result.stdout == "" and result.stderr == ""


def test_the_marker_beside_the_script_resolves_the_workspace(panes):
    """A board started from a plain terminal has no `$WORKSPACE` — same
    resolution order as `fleet-viewed.sh` and `statusline.sh`."""
    panes.marker.write_text(f"{panes.workspace}\n")

    panes.run(panes=[rec("%1", cc="cc-p-01")], names=["cc-p-01"], WORKSPACE="")

    assert list(panes.entries()) == ["cc-p-01"]


# --- when it cannot act -------------------------------------------------------

def test_a_failing_tmux_leaves_the_map_alone(panes):
    """A stale map is the behaviour we already have; an emptied one is a
    regression for every reader."""
    panes.seed(("cc-p-01", "%3", "keep-me"))

    result = panes.run(panes=[rec("%1", cc="cc-p-01")], names=["cc-p-01"],
                       TMUX_FAIL_STUB="1")

    assert panes.entries()["cc-p-01"]["window"] == "keep-me"
    assert result.returncode == 0


def test_a_failing_daemon_leaves_no_scratch_file(panes):
    """A reader treats a parse failure as "no map", so a truncated file silently
    disables the feature. Better to write nothing."""
    result = panes.run(panes=[rec("%1", cc="cc-p-01")], names=["cc-p-01"],
                       PS_STATUS="1")

    assert not panes.panes.exists()
    assert result.returncode == 0
    assert list((panes.data / "tmux").glob(".panes.json.*")) == []


def test_it_never_prints_on_any_path(panes):
    """It runs on the launch path, where a diagnostic lands in the middle of a
    session starting, and inside `fleet-watch`'s `board=$(draw)` — where stdout
    *is* the frame. Every path ends in a silent `exit 0`."""
    for kwargs in ({}, {"inside": False}, {"TMUX_FAIL_STUB": "1"},
                   {"PS_STATUS": "1"}, {"WORKSPACE": ""}):
        result = panes.run(panes=[rec("%1", cc="cc-p-01")], names=["cc-p-01"],
                           **kwargs)
        assert result.stdout == "", kwargs
        assert result.stderr == "", kwargs
        assert result.returncode == 0, kwargs


def test_no_tmux_and_no_docker_are_both_silent_no_ops(panes, tmp_path):
    """The launcher's exit path reaches this after a session that ran for hours;
    either binary can have gone away in between."""
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    # `/bin/bash` by absolute path: the point of the case is a `PATH` with
    # nothing on it, and resolving the interpreter through that same `PATH`
    # would fail before the script under test ever ran.
    result = subprocess.run(
        ["/bin/bash", str(panes.scripts / "fleet-panes.sh")],
        capture_output=True, text=True,
        env={"PATH": str(empty), "WORKSPACE": str(panes.workspace),
             "TMUX": f"{SERVER},1234,0"},
    )

    assert result.returncode == 0
    assert not panes.panes.exists()


def test_it_never_resolves_plugin_code():
    """The host boundary `test_fleet_render.py` and `test_fleet_watch.py` both
    assert. The plugin's manifest and cache are container-writable, so a host
    process that resolved plugin code would run whatever a container could
    write. This one shells out to `tmux` and `docker` and nothing else."""
    body = SCRIPT.read_text()

    for forbidden in ("uv ", "fleet_status", "multiplai-context", "plugins/"):
        assert forbidden not in body, forbidden


# --- the half a stub cannot answer --------------------------------------------

@pytest.mark.skipif(shutil.which("tmux") is None, reason="needs a real tmux")
class TestOnARealTmuxServer:
    """Three facts about tmux itself, which no stub can establish.

    A stub answers `list-panes -a` with whatever the test staged, so it pins the
    parsing and none of the premise. The premise is that a pane-scoped user
    option round-trips through a format at all, that it is genuinely attached to
    the *pane* rather than to its name, and that `#{automatic-rename}` resolves
    in a format — which it does, as `0`/`1`, not as the `off`/`on` every other
    read in the kit sees. All three were verified by hand on tmux 3.4 before the
    code was written; this is what keeps them verified.
    """

    @staticmethod
    def _server(tmp_path):
        # Short, because a unix socket path is capped around 104 bytes and a
        # pytest `tmp_path` plus a long test name gets close enough to matter.
        sock = str(tmp_path / "t.sock")

        def tm(*args, **kw):
            return subprocess.run(["tmux", "-S", sock, *args],
                                  capture_output=True, text=True, timeout=20, **kw)

        assert tm("new-session", "-d", "-s", "dev", "-n", "alpha",
                  "sleep 300").returncode == 0, "could not start a tmux server"
        return sock, tm

    @staticmethod
    def _docker_only(tmp_path, *running):
        """A `PATH` entry carrying a stub `docker` and **nothing else**.

        Deliberately not the fixture's stub dir: that one also holds a stub
        `tmux`, and putting it in front here would shadow the real binary —
        the script would interrogate the stub, the server under test would
        never be read, and the test would pass or fail on nothing at all.
        """
        d = tmp_path / "docker-only"
        d.mkdir()
        listed = "\\n".join(running)
        (d / "docker").write_text(
            f'#!/bin/bash\n[ "$1" = ps ] && printf "{listed}\\n"\nexit 0\n')
        (d / "docker").chmod(0o755)
        return d

    def _run_inside(self, panes, tm, bindir, arg=""):
        """The script, from a pane on that server — so it inherits `$TMUX`."""
        flag = panes.workspace / "done"
        flag.unlink(missing_ok=True)
        tm("new-window", "-d",
           f'PATH="{bindir}:$PATH" WORKSPACE="{panes.workspace}" '
           f'bash "{panes.scripts / "fleet-panes.sh"}" {arg}; touch "{flag}"')
        deadline = time.monotonic() + 20
        while not flag.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert flag.exists(), "the script never finished inside tmux"

    def test_the_stamp_round_trips_and_survives_a_rename(self, panes, tmp_path):
        """The premise of the whole design. A window name is a label and can be
        changed; the stamp is on the pane, so renaming the tab moves the label
        and not the identity — which is the one thing a `cc-` naming convention
        could never give, because a convention is a rule someone has to keep.

        It also pins the `automatic-rename` read: `rename-window` turns the
        option off, and the label is only recorded because the script reads
        tmux's `0` as "pinned".
        """
        sock, tm = self._server(tmp_path)
        pane = tm("list-panes", "-a", "-F", "#{pane_id}").stdout.strip()
        tm("set-option", "-p", "-t", pane, "@cc", "cc-p-08015414")
        tm("rename-window", "-t", pane, "inbox-cleanup")

        self._run_inside(panes, tm,
                         self._docker_only(tmp_path, "cc-p-08015414"))
        tm("kill-server")

        entry = panes.entries()["cc-p-08015414"]

        assert entry["pane"] == pane
        assert entry["window"] == "inbox-cleanup", \
            "the tab was renamed and the board did not follow"
        assert entry["server"] == sock

    def test_a_separator_in_the_stamp_cannot_shift_the_other_fields(
            self, panes, tmp_path):
        """`|` is the record separator, and `@cc` is arbitrary text.

        Only a real tmux can pin this: the stub answers `list-panes` with
        whatever the test staged, so it exercises the parsing and never the
        format string that produced it — which is where the defect was. With
        `#{@cc}` unstripped, a stamp of `cc-p-01|0|pwned` renders as
        `%0|cc-p-01|0|pwned|0|win|d` and parses as cc=`cc-p-01`, auto=`0`,
        window=`pwned`: a label smuggled past *both* the `automatic-rename`
        gate and the strip that the window name itself goes through. Verified
        against tmux 3.4 before the strip was added.

        The field is stripped rather than dropped for the same reason the
        window name is — this is a join key, and mangling it into something
        `docker ps` will not list is already the safe direction.
        """
        _sock, tm = self._server(tmp_path)
        pane = tm("list-panes", "-a", "-F", "#{pane_id}").stdout.strip()
        tm("set-option", "-p", "-t", pane, "@cc", "cc-p-01|0|pwned")

        self._run_inside(panes, tm, self._docker_only(tmp_path, "cc-p-01"))
        tm("kill-server")

        assert "cc-p-01" not in panes.entries(), \
            "a `|` in the stamp shifted the fields and forged an entry"
        assert not any(e["window"] == "pwned" for e in panes.entries().values())

    def test_a_plain_shell_pane_reports_an_empty_stamp(self, panes, tmp_path):
        """The other half: `#{@cc}` on an unstamped pane is empty rather than
        an error or a literal `#{@cc}`, which is what makes "non-empty" a usable
        definition of "this pane is an agent"."""
        _sock, tm = self._server(tmp_path)

        self._run_inside(panes, tm, self._docker_only(tmp_path, "cc-p-01"))
        tm("kill-server")

        assert panes.entries() == {}
