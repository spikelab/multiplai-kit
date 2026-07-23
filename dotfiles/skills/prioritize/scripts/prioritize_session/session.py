"""Pre-session snapshots, so a deliberation can be undone.

A prioritization session rewrites rank and importance across the whole
backlog. That's a lot of state to change on the strength of one conversation,
so every write is preceded by a snapshot of the exact `backlog --json` payload
and can be replayed back.

What revert restores: order, importance, due, duration, type, title, focus.
What it cannot restore: completions. `plan backlog --apply` marks tasks done
through plan-cli's `markDone`, and the backlog format has no "un-done" token —
a task that left the backlog has to be re-captured.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)


def snapshot_dir() -> Path:
    """Where snapshots live — alongside the kit's other runtime artifacts."""
    home = os.environ.get("CLAUDE_MULTIPLAI_HOME")
    base = Path(home) if home else Path.home() / ".multiplai"
    path = base / "runtime" / "prioritize"
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_snapshot(backlog: dict, session_id: str = "") -> Path:
    """Write the pre-session backlog and return its path."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = f"-{session_id[:8]}" if session_id else ""
    path = snapshot_dir() / f"backlog-{stamp}{suffix}.json"
    path.write_text(json.dumps(backlog, indent=2), encoding="utf-8")
    log.info(
        "DONE stage=snapshot path=%s tasks=%d", path, len(backlog.get("tasks", []))
    )
    return path


def latest_snapshot() -> Path | None:
    snapshots = sorted(snapshot_dir().glob("backlog-*.json"))
    return snapshots[-1] if snapshots else None


def load_snapshot(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def revert_changeset(
    snapshot: dict, present_ids: set[int] | None = None
) -> tuple[dict, list[int]]:
    """Build the changeset that puts the backlog back the way the snapshot found it.

    Order is the snapshot's own importance-then-rank sequence, which is how
    plan-cli renders — replaying it reproduces the original ranks.

    Tasks completed during the session are gone from the backlog and can't be
    restored, so they're dropped from the changeset and returned as the second
    element. Reverting a session that finished real work should still restore
    the ranking; failing the whole revert would take away the safety net
    exactly when the session was used properly.
    """
    active = snapshot.get("active")
    tasks = list(snapshot.get("tasks", []))

    unrestorable: list[int] = []
    if present_ids is not None:
        if active and active["id"] not in present_ids:
            unrestorable.append(active["id"])
            active = None
        unrestorable += [t["id"] for t in tasks if t["id"] not in present_ids]
        tasks = [t for t in tasks if t["id"] in present_ids]

    importance_rank = {"high": 0, "medium": 1, "low": 2}
    ordered = sorted(
        tasks,
        key=lambda t: (
            importance_rank.get(t.get("importance") or "medium", 1),
            t.get("rank") if t.get("rank") is not None else 10**9,
        ),
    )

    updates = {}
    for task in ([active] if active else []) + ordered:
        updates[str(task["id"])] = {
            "importance": task.get("importance") or "medium",
            "title": task["title"],
            "type": task.get("type"),
            # Always restated, including None: a due the session *added* has to
            # be cleared to get back to the snapshot.
            "due": task.get("due"),
        }
        # Duration is the one field the backlog format can't clear, so a
        # duration the session added survives the revert.
        if task.get("duration"):
            updates[str(task["id"])]["duration"] = task["duration"]

    changeset = {
        "now": active["id"] if active else None,
        "order": ([active["id"]] if active else []) + [t["id"] for t in ordered],
        "updates": updates,
    }
    log.info(
        "DONE stage=revert_changeset tasks=%d unrestorable=%d",
        len(updates),
        len(unrestorable),
    )
    return changeset, unrestorable
