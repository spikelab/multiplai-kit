#!/usr/bin/env python3
"""Render the fleet board — a block of lines sized to the window, from data
files only.

Called by `fleet-watch`, which redraws it in a terminal on a timer. It was
written for the tmux status bar, and one piece of that shape survives on
purpose: it does not scroll, so overflow is `+N more`. The column budgets and
the padded-to-exactly-N-rows layout were the other two, and they went when the
bar did — a 44-column summary and a footer marooned twenty blank rows below its
list are status-bar constraints being paid for by a terminal that has neither.
Scrolling is still the fleet console's job, not a patch to this file.

**This file is host-side kit code and must stay stdlib-only.** It never imports
from the `multiplai-context` plugin, does not shell out to `fleet_status.py`,
and is never invoked through `uv run`. That is a security
boundary, not a packaging preference: the plugin's manifest and cache are
container-writable, so a host process that resolved plugin code would execute
whatever a container could write. The same reasoning already keeps
`claude.sh`'s drain path host-side.

It reads three things, all of them **data**: `fleet.json` for the fleet, and
`tmux/panes.json` + `tmux/viewed/*` for the one field that would otherwise be
as old as the last SessionStart — see :func:`live_windows`. The first is
written by the plugin, the other two by the kit's own host-side scripts; none
of them is code, and reading a file the plugin wrote is not the same act as
resolving one.

Three rules the rendering obeys:

**It never recommends.** Readings only. "2 need you" is a fact; "merge the PR"
is advice, and a board you glance at is the wrong surface to argue with.

**It never looks confident about stale data.** Every line's ages are recomputed
from `generated_at` on each render, so the clock stays live between scans, and
past ten minutes the header says so. Where a field can be re-read fresh rather
than aged — the tab name, and only the tab name — it is, and the header goes on
reporting the document's real age for everything else.

**It never hides silently.** Whatever does not fit becomes an explicit `+N
more`. A board that dropped the last two agents without saying so is worse than
no board.
"""

import argparse
import json
import re
import sys
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

FLEET_JSON = "fleet.json"
PANE_MAP = "tmux/panes.json"
VIEWED_DIR = "tmux/viewed"

# Past this, the board stops presenting its numbers as current. Ten minutes is
# chosen against what writes the file: every SessionStart re-renders it, and
# with tabs open that is minutes apart — so ten means "nothing has started or
# stopped in a while", not "the renderer is broken".
STALE_AFTER = timedelta(minutes=10)

# Per-field caps for the fixed columns. A tab name is a handle, not a sentence.
# 24 is the width of a container name (`claude-personal-08015414`), which is
# what the label falls back to when a session has no tmux tab — at 16 every one
# of them rendered as `claude-personal…`, which identifies nobody.
MAX_LABEL = 24
MAX_PROJECT = 12

# The checkpoint text has no cap: it takes whatever the fixed fields leave.
# There *was* one — 44 columns, a status bar's budget — and it survived the bar
# it was written for, so a 165-column terminal drew 44 columns of summary and
# 80 columns of nothing.
#
# Below `MIN_TEXT` the field is dropped rather than shown, because three
# characters and an ellipsis is not a reading; the row still carries its
# marker, label, project and age, which is the part a narrow window can use.
MIN_TEXT = 12

# Markers carry the signal instead of colour — they survive a pipe, a `less`,
# and a terminal with no colour, and they cost nothing to emit.
M_NEEDS = "✋"       # ✋ stopped to ask you something
M_LIVE = "●"        # ● working
M_SEEN = "\U0001f440"    # 👀 you have looked at it since it last acted
M_WARN = "⚠"        # ⚠ collision, or stale data

# The marker is a *column*, not a prefix, and it has to be padded to one.
# `✋` and `👀` are East_Asian_Wide and occupy two columns; `●` and `⚠` are
# ambiguous-width and occupy one. Joined raw, every working row sat one column
# left of every needs-you row and the whole board sheared down its length.
MARKER_COLS = 2

# Everything that is not printable text. A checkpoint is LLM-written from a
# session transcript, so its contents are untrusted (see the marketplace's
# `docs/untrusted-content.md`) and one escape sequence in a board that repaints
# every few seconds can reposition the cursor or corrupt the whole screen.
#
# The companion strip — a `#` opening a tmux format sequence (`#(shell)`,
# `#{var}`, `#[style]`) — went with the status bar in the same commit. Nothing
# reads this output as a tmux format any more, and it was already defence in
# depth: tmux 3.4 substitutes `status-format` in a single pass, so a `#(...)`
# arriving through *data* was printed, never executed. Bring it back with the
# consumer that needs it, not before.
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def cols(text):
    """Terminal columns *text* occupies — not how many characters it has.

    The board's own markers are the reason this exists: `✋` and `👀` are
    East_Asian_Wide and take **two** columns each, so a line `len()` called 40
    was really 41, and the field that fell off the right edge was the staleness
    marker — the one whose absence changes what the numbers beside it mean.

    Combining marks add nothing; ambiguous-width characters (`●`, `·`, `…`,
    all of which this file emits) are counted as one, which is what a terminal
    in a non-CJK locale does with them.
    """
    total = 0
    for char in text:
        if unicodedata.combining(char):
            continue
        total += 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
    return total


def _cut(text, width):
    """The longest prefix of *text* that fits in *width* columns.

    Never splits a wide character across the boundary: a half-printed `👀`
    is what a terminal renders as a replacement box.
    """
    total = 0
    for i, char in enumerate(text):
        total += cols(char)
        if total > width:
            return text[:i]
    return text


def ljust(text, width):
    """`str.ljust` in columns, so the board's fields actually line up."""
    return text + " " * max(0, width - cols(text))


def clean(text, limit):
    """One printable line, capped — safe to paint into a live terminal."""
    text = _CONTROL.sub(" ", str(text or ""))
    text = " ".join(text.split())
    if cols(text) <= limit:
        return text
    return _cut(text, max(1, limit - 1)).rstrip() + "…"


def fit(line, width):
    """Hard-truncate to *width* columns, ending in an ellipsis when cut.

    A terminal cuts at the last column and says nothing, which is how a board
    loses its rightmost field — the staleness marker — without anyone noticing.
    Truncating here makes the loss visible.
    """
    if width <= 0:
        return ""
    if cols(line) <= width:
        return line
    return _cut(line, max(0, width - 1)) + "…"


def _parse_ts(value):
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def age(delta):
    """Coarse age — the same buckets `AGENTS.md` uses, so they read alike."""
    secs = max(0, int(delta.total_seconds()))
    if secs >= 86400:
        return f"{secs // 86400}d"
    if secs >= 3600:
        return f"{secs // 3600}h"
    if secs >= 60:
        return f"{secs // 60}m"
    return f"{secs}s"


def load(data_dir):
    """The fleet document, or ``None`` if there isn't a usable one.

    Missing and malformed are the same answer on purpose. This is called once
    per redraw, on a timer, for as long as the terminal is open — a traceback
    would arrive a few times a second, and "no fleet data" is the honest
    reading either way. `fleet-watch` reports the failures a person can act on
    (no workspace, no renderer); this one is not among them.
    """
    try:
        raw = json.loads((Path(data_dir) / FLEET_JSON).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return raw if isinstance(raw, dict) else None


def live_windows(data_dir):
    """``{container name: tab name}``, read fresh on every redraw.

    This exists because `fleet.json` is a **cache with no writer on this
    side**. It is produced by the plugin's fleet scan, in a container, at
    SessionStart — so between sessions it does not move, and a board on a
    five-second timer re-renders the same document with only the clock
    advancing. Rename a tab and the label stayed wrong for as long as no
    session happened to start: not a stale render, a document nobody had
    recomputed.

    The tab name is the one field that can be recovered here, and cheaply,
    because both halves of the join are **host-side kit data**:
    `tmux/panes.json` is written by `claude.sh`, and `tmux/viewed/*` by
    `fleet-viewed.sh` from tmux's own hooks — including `after-rename-window`,
    which is what makes a marker fresher than the map it is joined to. Reading
    them keeps the stdlib-only host boundary in this module's docstring intact:
    these are data files, not plugin code, and nothing here is resolved or
    executed.

    It recovers the *name*, not the *fleet*. Every other field — who is
    waiting, on what, for how long — still ages with the document, and the
    header still says how old that is. An agent with no entry in the pane map
    has nothing to join to and keeps whatever `fleet.json` gave it.

    The join is `_window_of` from the plugin's `lib/fleet.py`, deliberately
    duplicated rather than imported (importing it is the boundary violation),
    so the two must be kept in step. Its one load-bearing rule: **tmux recycles
    pane ids per server**, so a marker is only usable when its socket matches
    the pane's. A mismatch degrades to the map's own name rather than
    borrowing an unrelated tab's — labelling one agent with another's tab is
    worse than labelling it with a container name.
    """
    root = Path(data_dir)
    try:
        raw = json.loads((root / PANE_MAP).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    # A roster of pids in a file called `panes.json` is not a pane map, and a
    # reader that shrugged and used it anyway would join a pid to a pane id.
    if not isinstance(raw, dict) or raw.get("kind") != "tmux":
        return {}
    if raw.get("observer") != "host":
        return {}
    entries = raw.get("panes")
    if not isinstance(entries, dict):
        return {}
    doc_server = str(raw.get("server") or "")

    out = {}
    for name, value in entries.items():
        if not isinstance(name, str) or not isinstance(value, dict):
            continue
        pane = value.get("pane")
        if not isinstance(pane, str) or not pane:
            continue
        # Per-entry socket first: the map merges tabs across launches, so the
        # document-level one describes only whoever wrote the file last.
        server = str(value.get("server") or doc_server)
        window = _marker_window(root, pane, server) or str(value.get("window") or "")
        if window:
            out[name] = window
    return out


def _marker_window(root, pane, server):
    """The tab name `fleet-viewed.sh` last recorded for *pane*, or ``""``.

    Three lines, written by a tmux hook: the timestamp, the window name at that
    moment, and the socket. A marker missing the socket cannot be checked
    against the pane, which is the same as not having one — that field is the
    whole defence against crediting one tmux server's `%12` to another's.
    """
    pane_id = pane.lstrip("%")
    if not pane_id.isdigit():
        return ""
    try:
        lines = (root / VIEWED_DIR / pane_id).read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    if len(lines) < 3 or lines[2].strip() != server or not server:
        return ""
    return clean(lines[1], MAX_LABEL)


def _rank(agent):
    """Sort tier. Lower comes first.

    Needs-you outranks everything: it is the only tier where nothing moves
    until a person acts. Unseen next — that is the question the board exists
    for. Seen last, because you have already dealt with it.

    Within a tier the order is whatever `fleet.json` already had, which is the
    fleet's own recency ordering. Re-deriving it here is how a board and a
    digest start disagreeing about the same fleet.
    """
    if agent.get("group") == "Needs you":
        return 0
    return 2 if agent.get("seen") else 1


def _agent_line(agent, now, generated, width, windows=None):
    """One agent: marker, tab, project, age, and what it is waiting on.

    The fixed fields are sized by constant and the last one takes the rest of
    the line, so widening the terminal buys summary rather than blank space.
    """
    mark = M_NEEDS if agent.get("group") == "Needs you" else M_LIVE
    if agent.get("seen"):
        mark = M_SEEN
    # A live tab name beats the document's, which was true whenever the fleet
    # scan last ran. Never the other way round, and never a blank: an agent
    # missing from the pane map keeps what it already had.
    fresh = (windows or {}).get(agent.get("hostname"))
    label = clean(
        fresh
        or agent.get("tmux_window")
        or agent.get("hostname")
        or agent.get("session_id", "")[:8],
        MAX_LABEL,
    )
    project = clean(agent.get("project"), MAX_PROJECT)
    # Recomputed from the scan stamp rather than read off `age_seconds`, so the
    # clock keeps moving between scans instead of freezing at the last one.
    seconds = agent.get("age_seconds")
    if isinstance(seconds, (int, float)) and generated is not None:
        shown = age(timedelta(seconds=seconds) + (now - generated))
    elif isinstance(seconds, (int, float)):
        shown = age(timedelta(seconds=seconds))
    else:
        shown = "?"
    bits = [ljust(mark, MARKER_COLS), ljust(label, MAX_LABEL),
            ljust(project, MAX_PROJECT), shown.rjust(4)]
    prefix = " ".join(bits)
    # Two columns rather than one, because the text is prose butting against a
    # right-aligned number and a single space reads as a run-on.
    budget = width - cols(prefix) - 2
    what = clean(agent.get("next_action") or agent.get("intent"), budget) if budget >= MIN_TEXT else ""
    if what:
        bits.append(f" {what}")
    return fit(" ".join(bits).rstrip(), width)


def _count(counts, key):
    """A count as a number, or ``0``.

    Every other string on the board goes through `clean()`; these were the one
    set interpolated raw, on the assumption that a field named `fronts` holds
    an integer. `fleet.json` is written by the plugin from LLM-authored
    checkpoints, so that assumption is exactly the kind this file does not get
    to make — a string there would put unfiltered text, escape sequences
    included, straight into the header. Coercing is also narrower than
    cleaning: there is no legitimate non-numeric count, so a bad one is `0`,
    not truncated prose.
    """
    try:
        return int(counts.get(key, 0))
    except (TypeError, ValueError):
        return 0


def _header(doc, now, generated, width):
    counts = doc.get("counts") if isinstance(doc.get("counts"), dict) else {}
    bits = [
        "FLEET",
        f"{_count(counts, 'fronts')} fronts",
        f"{_count(counts, 'needs_you')} need you",
    ]
    collisions = _count(counts, "collisions")
    if collisions:
        bits.append(f"{M_WARN}{collisions} collision")
    if generated is None:
        bits.append("upd ?")
    else:
        since = now - generated
        stale = f" {M_WARN}stale" if since > STALE_AFTER else ""
        bits.append(f"upd {age(since)}{stale}")
    return fit(bits[0] + " " + " · ".join(bits[1:]), width)


def _section(name, value, stamp, now):
    """One `name: reading` for the tail line, honouring not-collected.

    ``null`` is *nobody looked* and ``[]`` is *looked, found nothing*. Printing
    both as "none" is the one thing this line must not do — a board that says
    "0 PRs open" when it never asked is worse than one that admits it.
    """
    if value is None:
        return f"{name} not collected"
    if isinstance(value, list) and not value:
        return f"{name} none"
    if isinstance(value, list):
        count = len(value)
    elif isinstance(value, dict):
        count = len(value.get("prs", value)) if "prs" in value else len(value)
    else:
        return f"{name} {clean(value, 12)}"
    # A carried section states its own age, because "3 open" from an hour ago
    # is a useful reading only if it says when somebody looked.
    when = _parse_ts(stamp)
    return f"{name} {count}" + (f" {age(now - when)}" if when else "")


def _tail(doc, agents, shown, now, width):
    """The last line: what did not fit, plus the sections nobody else prints."""
    bits = []
    hidden = len(agents) - shown
    if hidden > 0:
        bits.append(f"+{hidden} more")
    seen = sum(1 for a in agents if a.get("seen"))
    if seen:
        bits.append(f"{M_SEEN}{seen} seen")
    collisions = doc.get("collisions")
    if isinstance(collisions, list) and collisions:
        first = clean(str(collisions[0].get("path", "")).split("/")[-1], 18)
        bits.append(f"{M_WARN}{first}")
    stamps = doc.get("collected_at") if isinstance(doc.get("collected_at"), dict) else {}
    bits.append(_section("PRs", doc.get("prs"), stamps.get("prs"), now))
    return fit(" · ".join(bits), width)


def render(doc, lines, width, now=None, windows=None):
    """**At most** *lines* lines, each at most *width* columns. Never raises.

    Header first, agents under it, tail immediately after the last agent. The
    tail used to be pinned to line *lines* with the gap padded blank — a status
    bar's layout, where the row count was the whole canvas. In a terminal that
    stranded `PRs not collected` twenty blank rows below the list it belongs
    to, which reads as a stray line rather than a footer.

    So *lines* is now a **budget, not a shape**: the board is a block at the
    top of the window and the rest of the screen stays clear. The header is
    still line one and the tail is still last, which is the part of "fixed
    layout" a reader's eye actually uses.
    """
    now = now or datetime.now(timezone.utc)
    if lines <= 0:
        return []
    if not isinstance(doc, dict):
        # A blank board, not an error and not a stale one. Saying nothing is
        # the honest reading of a fleet document that could not be read; the
        # rows are no longer spent whether we use them or not.
        return []

    generated = _parse_ts(doc.get("generated_at"))
    out = [_header(doc, now, generated, width)]
    if lines == 1:
        return out

    raw = doc.get("agents")
    agents = [a for a in raw if isinstance(a, dict)] if isinstance(raw, list) else []
    # Only what the fleet view itself lists. `Idle` is already a guess at death
    # and is excluded there for the same reason it is excluded here.
    agents = [a for a in agents if a.get("group") not in (None, "", "Idle")]
    agents.sort(key=_rank)

    # One row held back for the tail, which must always be reachable: it is
    # where `+N more` lives, and a board that dropped agents without saying so
    # is the one thing this file will not do.
    room = lines - 2
    for agent in agents[:room]:
        out.append(_agent_line(agent, now, generated, width, windows))
    out.append(_tail(doc, agents, min(room, len(agents)), now, width))
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--lines", type=int, default=3)
    parser.add_argument("--width", type=int, default=120)
    parser.add_argument("--out", default="")
    args = parser.parse_args(argv)

    doc = load(args.data_dir)
    body = "\n".join(
        render(doc, args.lines, args.width, windows=live_windows(args.data_dir))
    ) + "\n"
    if not args.out:
        sys.stdout.write(body)
        return 0
    # Atomic, because the bash entry point reads this file on every tick from
    # up to five callers at once; a half-written cache would flicker.
    out = Path(args.out)
    tmp = out.with_name(out.name + ".tmp")
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(body, encoding="utf-8")
        tmp.replace(out)
    except OSError:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
