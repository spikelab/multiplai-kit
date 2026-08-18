"""Pins the fleet board's renderer — `dotfiles/scripts/fleet-render.py`.

`fleet-watch` redraws this in a terminal on a timer. The renderer is tested as
a pure function over a `fleet.json` document: it takes a line count and a
column width and returns exactly that many lines, so nothing here needs a
terminal.

The budget is inherited from the tmux status bar this was written for, and the
bar is gone. What is *not* inherited is the reason the budget is enforced — a
terminal cuts at the last column just as silently as tmux did.

Four properties this file exists to keep:

* **Exactly N lines, each within W columns.** Anything over the budget is cut
  at the right edge without a word, which is how a board loses its rightmost
  field — the staleness marker — without anyone noticing.
* **Nothing is hidden silently.** What does not fit becomes `+N more`. A board
  that dropped the last two agents is worse than no board.
* **Not-collected never prints as none.** `null` is *nobody looked*, `[]` is
  *looked, found nothing*. "0 PRs open" when nothing asked is a lie the board
  states confidently and repeatedly.
* **Untrusted text cannot carry control characters into the screen.**
  Checkpoint contents are LLM-written from session transcripts, and this
  repaints every few seconds — one stray escape sequence corrupts every
  subsequent frame.

It must also stay **stdlib-only and plugin-free**: it runs on the host, and the
plugin's manifest and cache are container-writable. A test reads its imports.
"""

import ast
import importlib.util
import json
import re
import unicodedata
from datetime import datetime, timedelta, timezone

import pytest

from conftest import KIT_ROOT
RENDERER = KIT_ROOT / "dotfiles" / "scripts" / "fleet-render.py"

NOW = datetime(2026, 8, 7, 12, 0, 0, tzinfo=timezone.utc)


def _load():
    spec = importlib.util.spec_from_file_location("fleet_render", RENDERER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


board = _load()


def agent(**kw):
    base = {
        "session_id": "abcdef1234",
        "project": "mktplace",
        "hostname": "claude-a-01",
        "tmux_window": "pi-eval",
        "group": "Working",
        "seen": False,
        "age_seconds": 60,
        "intent": "doing a thing",
        "next_action": "",
    }
    base.update(kw)
    return base


def doc(agents=(), *, generated=NOW, **kw):
    base = {
        "version": 1,
        "generated_at": generated.isoformat(),
        "counts": {"agents": len(agents), "live": len(agents),
                   "fronts": len(agents), "needs_you": 0, "collisions": 0},
        "agents": list(agents),
        "collisions": [],
        "prs": None,
        "collected_at": {},
    }
    base.update(kw)
    return base


# --- shape --------------------------------------------------------------------

@pytest.mark.parametrize("lines", [1, 2, 3, 4, 5])
def test_it_never_returns_more_lines_than_it_was_given(lines):
    """A budget, not a shape. With more agents than rows the board fills every
    line it is allowed; the guarantee is that it never exceeds them."""
    out = board.render(doc([agent(session_id=f"s{i}") for i in range(9)]),
                       lines, 120, NOW)

    assert len(out) == lines


def test_the_tail_follows_the_list_rather_than_the_window():
    """The regression, stated directly: with room for 30 lines and 2 agents,
    the tail sat on line 30 with 26 blank rows above it — a footer far enough
    from its list to read as an unrelated line."""
    out = board.render(doc([agent(session_id="a"), agent(session_id="b")]),
                       30, 120, NOW)

    assert len(out) == 4
    assert "" not in out


def _cols(text):
    """Display columns, computed here independently of the renderer.

    Deliberately not `board.cols` — a width test that measured with the same
    function the renderer truncates with would pass no matter what either of
    them believed a column was.
    """
    return sum(0 if unicodedata.combining(c)
               else 2 if unicodedata.east_asian_width(c) in ("W", "F")
               else 1
               for c in text)


@pytest.mark.parametrize("width", [20, 40, 80, 120])
def test_no_line_exceeds_the_width(width):
    """In **columns**, not characters. The board's own markers are the reason:
    `✋` and `👀` are East_Asian_Wide, so a line 40 characters long is 41
    columns wide and the terminal cuts the rightmost field — which is where the
    staleness marker lives, the one field whose loss changes what the numbers
    to its left mean."""
    out = board.render(doc([agent(next_action="a very long next action " * 5)] * 4),
                       4, width, NOW)

    assert all(_cols(line) <= width for line in out), out


@pytest.mark.parametrize("marker,group,seen", [("✋", "Needs you", False),
                                               ("👀", "Working", True)])
def test_a_wide_marker_does_not_push_the_line_over(marker, group, seen):
    """The regression, stated directly: at width 40 these lines measured 41
    columns and lost their last character off the right edge."""
    out = board.render(doc([agent(group=group, seen=seen,
                                  next_action="x" * 60)]), 3, 40, NOW)

    assert marker in out[1]
    assert _cols(out[1]) <= 40


def test_the_fields_line_up_across_a_wide_label():
    """Padding is in columns too. A label holding a wide character padded with
    `str.ljust` would sit one column right of every other row's project
    field, which is the kind of drift that makes a board unglanceable."""
    out = board.render(doc([agent(tmux_window="ab", session_id="s1"),
                            agent(tmux_window="七", session_id="s2")]), 4, 120, NOW)

    assert _cols(out[1].split("mktplace")[0]) == _cols(out[2].split("mktplace")[0])


def test_the_markers_line_up_despite_being_different_widths():
    """`✋`/`👀` are two columns and `●`/`⚠` are one, so joined without padding
    every working row sat one column left of every needs-you row and the board
    sheared down its whole length. The marker is a column, not a prefix."""
    out = board.render(doc([agent(session_id="n", group="Needs you"),
                            agent(session_id="w", group="Working"),
                            agent(session_id="s", group="Working", seen=True)]),
                       5, 120, NOW)

    starts = {_cols(line.split("mktplace")[0]) for line in out[1:4]}
    assert len(starts) == 1, out


def test_zero_lines_is_no_lines_not_a_crash():
    assert board.render(doc([agent()]), 0, 120, NOW) == []


def test_a_missing_document_renders_nothing_not_an_error():
    """Saying nothing claims nothing about the fleet — and a traceback
    repainting a few times a second is the worst output available."""
    assert board.render(None, 3, 120, NOW) == []


def test_a_malformed_fleet_json_loads_as_none(tmp_path):
    (tmp_path / "fleet.json").write_text("{not json")

    assert board.load(tmp_path) is None


def test_a_missing_fleet_json_loads_as_none(tmp_path):
    assert board.load(tmp_path) is None


def test_the_header_is_always_the_first_line():
    out = board.render(doc([agent()]), 3, 120, NOW)

    assert out[0].startswith("FLEET")


# --- ordering -----------------------------------------------------------------

def test_needs_you_comes_before_unseen_comes_before_seen():
    agents = [
        agent(session_id="seen", tmux_window="seen-tab", seen=True),
        agent(session_id="work", tmux_window="work-tab"),
        agent(session_id="need", tmux_window="need-tab", group="Needs you"),
    ]

    out = board.render(doc(agents), 5, 120, NOW)

    assert "need-tab" in out[1]
    assert "work-tab" in out[2]
    assert "seen-tab" in out[3]


def test_idle_agents_never_reach_the_board():
    """`Idle` is a guess at death and is already excluded from `AGENTS.md`.
    A board and a report that disagree about who is alive is how you stop
    trusting both."""
    agents = [agent(session_id="i", tmux_window="idle-tab", group="Idle"),
              agent(session_id="w", tmux_window="work-tab")]

    out = board.render(doc(agents), 4, 120, NOW)

    assert "idle-tab" not in "\n".join(out)
    assert "work-tab" in out[1]


def test_within_a_tier_the_documents_own_order_is_kept():
    """`fleet.json` is already ordered by recency. Re-deriving that here is how
    a board and a digest start disagreeing about the same fleet."""
    agents = [agent(session_id=f"s{i}", tmux_window=f"tab{i}") for i in range(3)]

    out = board.render(doc(agents), 5, 120, NOW)

    assert [line.split()[1] for line in out[1:4]] == ["tab0", "tab1", "tab2"]


# --- overflow -----------------------------------------------------------------

def test_what_does_not_fit_becomes_a_count():
    agents = [agent(session_id=f"s{i}", tmux_window=f"tab{i}") for i in range(9)]

    out = board.render(doc(agents), 4, 120, NOW)

    # Four lines: header, two agents, tail.
    assert "+7 more" in out[-1]


def test_nothing_overflows_when_everything_fits():
    out = board.render(doc([agent()]), 5, 120, NOW)

    assert "more" not in out[-1]


def test_an_empty_fleet_still_renders_its_header_and_tail():
    out = board.render(doc([]), 3, 120, NOW)

    assert out[0].startswith("FLEET")
    assert out[-1] != ""


# --- staleness ----------------------------------------------------------------

def test_a_fresh_document_shows_its_age_without_a_marker():
    out = board.render(doc([], generated=NOW - timedelta(seconds=12)), 2, 120, NOW)

    assert "upd 12s" in out[0]
    assert "stale" not in out[0]


def test_a_document_past_ten_minutes_is_marked_stale():
    """The board must never look confident about data it knows is old."""
    out = board.render(doc([], generated=NOW - timedelta(minutes=14)), 2, 120, NOW)

    assert "upd 14m" in out[0]
    assert "stale" in out[0]


def test_an_unparseable_stamp_says_so_rather_than_guessing():
    out = board.render(doc([], generated=NOW) | {"generated_at": "nonsense"},
                       2, 120, NOW)

    assert "upd ?" in out[0]


def test_ages_keep_moving_between_scans():
    """Recomputed from `generated_at`, not read off `age_seconds` — otherwise
    every age freezes at the last scan while the clock ticks."""
    scanned = NOW - timedelta(minutes=5)
    out = board.render(doc([agent(age_seconds=120)], generated=scanned),
                       3, 120, NOW)

    assert " 7m" in out[1]


# --- honest gaps --------------------------------------------------------------

def test_a_null_section_renders_not_collected():
    out = board.render(doc([], prs=None), 2, 120, NOW)

    assert "PRs not collected" in out[-1]


def test_an_empty_section_renders_none():
    out = board.render(doc([], prs=[]), 2, 120, NOW)

    assert "PRs none" in out[-1]


def test_a_carried_section_shows_when_somebody_looked():
    """"3 open" from an hour ago is a useful reading only if it says so."""
    stamp = (NOW - timedelta(minutes=14)).isoformat()
    out = board.render(doc([], prs=[{"n": 1}, {"n": 2}, {"n": 3}],
                           collected_at={"prs": stamp}), 2, 120, NOW)

    assert "PRs 3 14m" in out[-1]


def test_a_collision_is_named_not_just_counted():
    out = board.render(doc([], collisions=[{"path": "/w/lib/fleet.py"}]),
                       2, 120, NOW)

    assert "fleet.py" in out[-1]


def test_the_seen_count_reaches_the_tail():
    agents = [agent(session_id="a", seen=True), agent(session_id="b", seen=True),
              agent(session_id="c")]

    out = board.render(doc(agents), 5, 120, NOW)

    assert "2 seen" in out[-1]


# --- sanitization -------------------------------------------------------------

def test_a_checkpoint_is_flattened_to_one_line():
    """A multi-line intent must come out as one row, not push the layout down.

    The tmux `#(...)` / `#[...]` strip that used to be asserted here went with
    the status bar — nothing reads this output as a tmux format any more, and
    it was defence in depth even then (tmux 3.4 substitutes `status-format` in
    a single pass, so data arriving that way was printed, never executed). A
    `#` is now ordinary text, which is what it should be in a terminal.
    """
    hostile = "own me #(id) then #[fg=red] red\nand a second line"

    out = board.render(doc([agent(next_action=hostile)]), 3, 200, NOW)
    line = out[1]

    assert "\n" not in line
    assert "red and a" in line, "the newline becomes a space, not a row break"
    assert "#(id)" in line, "sanitizing must not silently swallow the text"


def test_a_count_that_is_not_a_number_cannot_reach_the_header():
    """The header interpolated `counts` raw, on the assumption that a field
    named `fronts` holds an integer. `fleet.json` is assembled from LLM-written
    checkpoints, so that is exactly the assumption this file does not get to
    make — it is the one path by which unfiltered text reaches the header
    without passing `clean()`. There is no legitimate non-numeric count, so a
    bad one is 0 rather than truncated prose."""
    out = board.render(doc([], counts={"fronts": "#(id)", "needs_you": None,
                                       "collisions": {"x": 1}}), 3, 200, NOW)

    assert "#(" not in out[0]
    assert "0 fronts" in out[0]
    assert "0 need you" in out[0]
    assert "collision" not in out[0]


def test_control_characters_never_reach_the_screen():
    """This repaints every few seconds. One escape sequence through data
    repositions the cursor or clears the screen on every subsequent frame —
    the corruption outlives the field it arrived in."""
    out = board.render(doc([agent(next_action="a\x1b[2Jb\x07c\x00d")]), 3, 200, NOW)

    assert not re.search(r"[\x00-\x1f\x7f-\x9f]", out[1])


def test_the_fixed_fields_are_capped_independently():
    """One runaway *fixed* field must not eat the line and push everything else
    off the right edge, where the terminal would cut it without a word. The
    summary is the deliberate exception — it is what the leftover is for."""
    out = board.render(
        doc([agent(tmux_window="w" * 200, project="p" * 200,
                   next_action="n" * 500)]), 3, 400, NOW)

    assert _cols(out[1]) <= 400
    # marker + label + project + age, and the two spaces before the summary.
    assert out[1].index("n") == board.MARKER_COLS + 1 + board.MAX_LABEL + 1 \
        + board.MAX_PROJECT + 1 + 4 + 2


def test_the_summary_grows_with_the_terminal():
    """The bug Spike hit: a 165-column terminal drew 44 columns of summary and
    the rest blank, because the cap was a status bar's and outlived it."""
    long = "n" * 500
    narrow = board.render(doc([agent(next_action=long)]), 3, 100, NOW)[1]
    wide = board.render(doc([agent(next_action=long)]), 3, 200, NOW)[1]

    assert _cols(narrow) == 100
    assert _cols(wide) == 200


def test_a_window_too_narrow_for_a_summary_drops_it_rather_than_stubbing_it():
    """Three characters and an ellipsis is not a reading. The row keeps the
    fields a narrow window can still use."""
    out = board.render(doc([agent(next_action="n" * 500)]), 3, 50, NOW)

    assert "n" not in out[1]


def test_truncation_is_marked():
    assert board.clean("abcdefghij", 5).endswith("…")
    assert board.fit("abcdefghij", 5).endswith("…")


# --- the live tab name ---------------------------------------------------------
#
# `fleet.json` is a cache the plugin writes at SessionStart, in a container.
# Nothing on this side recomputes it, so between sessions a board on a timer
# re-renders the same document forever. The tab name is the one field that can
# be recovered here, from two files the *kit* writes on the host — and the
# server check is what keeps that recovery from being worse than the staleness.

def _tmux(tmp_path, panes, markers, server="/tmp/tmux-501/default", **doc_kw):
    root = tmp_path / "tmux"
    (root / "viewed").mkdir(parents=True)
    payload = {"version": 1, "kind": "tmux", "observer": "host",
               "server": server, "panes": panes}
    payload.update(doc_kw)
    (root / "panes.json").write_text(json.dumps(payload))
    for pane, (window, sock) in markers.items():
        (root / "viewed" / pane).write_text(f"2026-08-07T23:59:21Z\n{window}\n{sock}\n")
    return tmp_path


def test_a_renamed_tab_relabels_without_waiting_for_a_scan(tmp_path):
    """Spike's report: a tab renamed at 23:59 still read `zsh` minutes later,
    because `fleet.json` was generated at 23:54 and nothing had recomputed it.
    The rename hook had recorded it correctly all along."""
    sock = "/tmp/tmux-501/default"
    _tmux(tmp_path, {"claude-a-01": {"pane": "%478", "server": sock, "window": "zsh"}},
          {"478": ("inbox cleanup", sock)})

    windows = board.live_windows(tmp_path)
    out = board.render(doc([agent(tmux_window="zsh")]), 3, 120, NOW, windows=windows)

    assert windows == {"claude-a-01": "inbox cleanup"}
    assert "inbox cleanup" in out[1]


def test_a_marker_from_another_tmux_server_is_refused(tmp_path):
    """tmux recycles pane ids per server, so `%478` on yesterday's server says
    nothing about `%478` on today's. Labelling one agent with another's tab is
    worse than labelling it with a container name — degrade to the map."""
    _tmux(tmp_path, {"claude-a-01": {"pane": "%478", "server": "/tmp/now",
                                     "window": "from-the-map"}},
          {"478": ("from-a-dead-server", "/tmp/yesterday")})

    assert board.live_windows(tmp_path) == {"claude-a-01": "from-the-map"}


def test_the_pane_maps_own_name_is_used_when_no_marker_exists(tmp_path):
    sock = "/tmp/tmux-501/default"
    _tmux(tmp_path, {"claude-a-01": {"pane": "%478", "server": sock, "window": "named"}}, {})

    assert board.live_windows(tmp_path) == {"claude-a-01": "named"}


def test_an_agent_with_no_pane_keeps_what_the_document_gave_it(tmp_path):
    """Only two of eleven agents were in the pane map; the rest must not be
    blanked by a join that has nothing to say about them."""
    _tmux(tmp_path, {}, {})

    out = board.render(doc([agent(tmux_window="from-the-scan")]), 3, 120, NOW,
                       windows=board.live_windows(tmp_path))

    assert "from-the-scan" in out[1]


@pytest.mark.parametrize("payload", [
    '{"kind": "pids", "observer": "host", "panes": {}}',
    '{"kind": "tmux", "observer": "container", "panes": {}}',
    '{"kind": "tmux", "observer": "host", "panes": []}',
    "{not json",
])
def test_a_document_it_cannot_interpret_yields_no_labels(tmp_path, payload):
    """A roster of pids in a file called `panes.json` is not a pane map, and a
    reader that shrugged and used it anyway would join a pid to a pane id."""
    (tmp_path / "tmux").mkdir()
    (tmp_path / "tmux" / "panes.json").write_text(payload)

    assert board.live_windows(tmp_path) == {}


def test_no_tmux_data_at_all_is_not_an_error(tmp_path):
    assert board.live_windows(tmp_path) == {}


def test_a_hostile_tab_name_is_cleaned_like_every_other_field(tmp_path):
    """The marker is written from tmux's `#{window_name}`, which is whatever a
    person typed — and it is painted into a terminal every few seconds."""
    sock = "/tmp/tmux-501/default"
    _tmux(tmp_path, {"claude-a-01": {"pane": "%1", "server": sock}},
          {"1": ("a\x1b[2Jb", sock)})

    assert "\x1b" not in board.live_windows(tmp_path)["claude-a-01"]


# --- the host boundary ---------------------------------------------------------

def test_the_renderer_imports_nothing_outside_the_standard_library():
    """It runs on the host. The plugin's manifest and cache are
    container-writable, so a host process that resolved plugin code would
    execute whatever a container could write — the same reasoning that keeps
    `claude.sh`'s drain path host-side.

    Parsed, not grepped. A line-anchored regex over the source reads prose as
    code — a docstring wrapping onto `from the \\`multiplai-context\\` plugin`
    failed this — and the same looseness runs the other way: an indented import
    inside a function is a real one the regex never sees. `ast` sees exactly
    the imports and exactly nothing else."""
    stdlib = {"argparse", "json", "re", "sys", "unicodedata", "datetime", "pathlib"}
    tree = ast.parse(RENDERER.read_text(encoding="utf-8"))

    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            # A relative import has no module and is a package this file is
            # not part of; record it as itself so it can never pass silently.
            imported.add((node.module or ".").split(".")[0])

    assert imported <= stdlib, f"non-stdlib import: {imported - stdlib}"


def _code_only():
    """The renderer's source with comments and string literals removed.

    The docstrings *name* the things this file must not do, and must go on
    naming them — a rule with no stated reason is a rule someone deletes. So
    the assertion is about executable code, not about the text of the file.
    """
    import io
    import tokenize

    src = RENDERER.read_text(encoding="utf-8")
    kept = []
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type not in (tokenize.COMMENT, tokenize.STRING):
            kept.append(tok.string)
    return " ".join(kept)


@pytest.mark.parametrize("forbidden", [
    "multiplai-context", "multiplai_context", "uv", "fleet_status",
    "subprocess", "importlib", "exec", "eval",
])
def test_the_renderer_never_reaches_for_plugin_code_or_a_subprocess(forbidden):
    assert forbidden not in _code_only().split()


def test_it_writes_its_cache_atomically(tmp_path):
    """Up to five callers read this file per tick. A half-written cache would
    flicker the board."""
    (tmp_path / "fleet.json").write_text(json.dumps(doc([agent()])))
    out = tmp_path / "board.txt"

    board.main(["--data-dir", str(tmp_path), "--lines", "3",
                "--width", "80", "--out", str(out)])

    assert len(out.read_text(encoding="utf-8").splitlines()) == 3
    assert not list(tmp_path.glob("*.tmp"))
