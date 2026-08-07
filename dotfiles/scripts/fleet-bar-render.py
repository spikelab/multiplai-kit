#!/usr/bin/env python3
"""Render the tmux fleet bar — a few fixed-width lines, from data files only.

The board is the tmux status bar itself, several lines high, in every window.
No pane, no daemon, no launchd job: `status-interval` already fires on a timer
inside a process that is always running, so the scheduler is free.

**This file is host-side kit code and must stay stdlib-only.** It reads
`fleet.json` and nothing else — it does not import from the
`multiplai-context` plugin, does not shell out to `fleet_status.py`, and is
never invoked through `uv run`. That is a security boundary, not a packaging
preference: the plugin's manifest and cache are container-writable, so a host
process that resolved plugin code would execute whatever a container could
write. The same reasoning already keeps `claude.sh`'s drain path host-side.

Three rules the rendering obeys:

**It never recommends.** Readings only. "2 need you" is a fact; "merge the PR"
is advice, and a status bar is the wrong surface to argue with.

**It never looks confident about stale data.** Every line's ages are recomputed
from `generated_at` on each render, so the clock stays live between scans, and
past ten minutes the bar says so.

**It never hides silently.** Whatever does not fit becomes an explicit `+N
more`. A board that dropped the last two agents without saying so is worse than
no board.
"""

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

FLEET_JSON = "fleet.json"

# Past this, the bar stops presenting its numbers as current. Ten minutes is
# chosen against what writes the file: every SessionStart re-renders it, and
# with tabs open that is minutes apart — so ten means "nothing has started or
# stopped in a while", not "the renderer is broken".
STALE_AFTER = timedelta(minutes=10)

# Per-field caps, applied before anything reaches a tmux format string. A tab
# name is a handle, not a sentence.
MAX_LABEL = 16
MAX_PROJECT = 12
MAX_TEXT = 44

# Markers carry the signal instead of colour. tmux substitutes `status-format`
# in a single pass, so a `#[fg=red]` living inside *data* is printed literally
# rather than interpreted — styling has to be in the format string, which the
# data cannot reach. Unicode needs no styling at all.
M_NEEDS = "✋"       # ✋ stopped to ask you something
M_LIVE = "●"        # ● working
M_SEEN = "\U0001f440"    # 👀 you have looked at it since it last acted
M_WARN = "⚠"        # ⚠ collision, or stale data

# Everything that is not printable text. A checkpoint is LLM-written from a
# session transcript, so its contents are untrusted (see the marketplace's
# `docs/untrusted-content.md`) and a control character in a status line can
# reposition the cursor or corrupt the whole bar.
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")

# A `#` that opens a tmux format sequence: `#(shell)`, `#{var}`, `#[style]`,
# or `##`. Verified on tmux 3.4 with a real attached client that a `#(...)`
# reaching `status-format` through *data* is not executed — substitution is
# single-pass — so this is defence in depth rather than a live injection fix.
# It stays because the failure would be silent and severe, and because the
# next tmux is not bound by what this one does.
_FORMAT_OPEN = re.compile(r"#(?=[({\[#])")


def clean(text, limit):
    """One printable line, capped — safe to hand to a tmux format string."""
    text = _CONTROL.sub(" ", str(text or ""))
    text = _FORMAT_OPEN.sub("", text)
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)].rstrip() + "…"


def fit(line, width):
    """Hard-truncate to *width*, ending in an ellipsis when something was cut.

    A tmux status line silently cuts at the last column, which is how a board
    loses its rightmost field — the staleness marker — without anyone noticing.
    Truncating here makes the loss visible.
    """
    if width <= 0:
        return ""
    if len(line) <= width:
        return line
    return line[: max(0, width - 1)] + "…"


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

    Missing and malformed are the same answer on purpose. This runs from a tmux
    hook several times a second; there is no surface on which to report a
    problem, and a bar that printed a traceback into the status line would be
    the worst outcome available.
    """
    try:
        raw = json.loads((Path(data_dir) / FLEET_JSON).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return raw if isinstance(raw, dict) else None


def _rank(agent):
    """Sort tier. Lower comes first.

    Needs-you outranks everything: it is the only tier where nothing moves
    until a person acts. Unseen next — that is the question the board exists
    for. Seen last, because you have already dealt with it.

    Within a tier the order is whatever `fleet.json` already had, which is the
    fleet's own recency ordering. Re-deriving it here is how a bar and a digest
    start disagreeing about the same fleet.
    """
    if agent.get("group") == "Needs you":
        return 0
    return 2 if agent.get("seen") else 1


def _agent_line(agent, now, generated, width):
    """One agent: marker, tab, project, age, and what it is waiting on."""
    mark = M_NEEDS if agent.get("group") == "Needs you" else M_LIVE
    if agent.get("seen"):
        mark = M_SEEN
    label = clean(
        agent.get("tmux_window") or agent.get("hostname") or agent.get("session_id", "")[:8],
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
    what = clean(agent.get("next_action") or agent.get("intent"), MAX_TEXT)
    bits = [mark, label.ljust(MAX_LABEL), project.ljust(MAX_PROJECT), shown.rjust(4)]
    if what:
        bits.append(f" {what}")
    return fit(" ".join(bits).rstrip(), width)


def _header(doc, now, generated, width):
    counts = doc.get("counts") if isinstance(doc.get("counts"), dict) else {}
    bits = [
        "FLEET",
        f"{counts.get('fronts', 0)} fronts",
        f"{counts.get('needs_you', 0)} need you",
    ]
    collisions = counts.get("collisions", 0)
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


def render(doc, lines, width, now=None):
    """Exactly *lines* lines, each at most *width* columns. Never raises.

    Layout is fixed so a reader's eye can land in the same place every tick:
    the header on the first line, the tail on the last, agents in between.
    Fixed beats adaptive here — a bar whose rows move around is one you have to
    read rather than glance at.
    """
    now = now or datetime.now(timezone.utc)
    if lines <= 0:
        return []
    if not isinstance(doc, dict):
        # A blank bar, not an error and not a stale bar. The rows are already
        # spent; leaving them empty says "nothing to show" without claiming
        # anything about the fleet.
        return [""] * lines

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

    room = lines - 2
    for agent in agents[:room]:
        out.append(_agent_line(agent, now, generated, width))
    while len(out) < lines - 1:
        out.append("")
    out.append(_tail(doc, agents, min(room, len(agents)), now, width))
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--lines", type=int, default=3)
    parser.add_argument("--width", type=int, default=120)
    parser.add_argument("--out", default="")
    args = parser.parse_args(argv)

    body = "\n".join(render(load(args.data_dir), args.lines, args.width)) + "\n"
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
