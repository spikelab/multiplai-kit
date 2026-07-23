"""Turn the raw backlog into a compact deliberation brief.

Two jobs:
  1. Derive the signals an Eisenhower conversation needs — urgency from due
     proximity, quadrant, how long an item has been sitting — so the ranking
     argument runs on stated facts rather than vibes.
  2. Keep it small. The full dump carries `start` steps and `notes` for every
     task; loading all of that just to argue about ordering wastes context.
     The brief drops them, and `detail` fetches them for the few tasks that
     actually get discussed.

Nothing here decides anything. The quadrant is an opening position for the
conversation, not a verdict — the point of the session is for Nick to argue
with it.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

log = logging.getLogger(__name__)

# Due-proximity buckets, in days remaining.
URGENT_WITHIN_DAYS = 2
SOON_WITHIN_DAYS = 7

# A Q2 item (important, not urgent) that has sat this long is being starved —
# the documented failure mode this skill exists to interrupt.
STARVED_AFTER_DAYS = 14

# plan-cli gives <=15min tasks a momentum bonus; same threshold for "sand".
SAND_MAX_MINUTES = 15

# A rock needs a real block of time. Unknown duration on a high-importance item
# counts — unestimated work is usually the big scary kind.
ROCK_MIN_MINUTES = 45

# Fields carried into the brief. `start`/`notes` are deliberately excluded.
_BRIEF_FIELDS = (
    "id",
    "title",
    "type",
    "importance",
    "due",
    "duration",
    "rank",
    "status",
    "done_when",
)


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except ValueError:
        log.warning("SKIP stage=parse_date reason=unparseable value=%s", value)
        return None


def urgency_of(due: str | None, today: date) -> tuple[str, int | None]:
    """Return (bucket, days_to_due). Bucket is the urgency axis of the matrix."""
    due_date = _parse_date(due)
    if due_date is None:
        return "unscheduled", None
    days = (due_date - today).days
    if days < 0:
        return "overdue", days
    if days <= URGENT_WITHIN_DAYS:
        return "urgent", days
    if days <= SOON_WITHIN_DAYS:
        return "soon", days
    return "later", days


def quadrant_of(importance: str | None, urgency: str) -> str:
    """Map onto Eisenhower.

    Importance is three-valued in plan-cli but the matrix is binary, so `high`
    is the important half and medium/low are not. That's a lossy call on
    purpose: medium items showing up in Q3/Q4 is exactly the prompt to ask
    whether they're really medium.
    """
    important = (importance or "medium") == "high"
    urgent = urgency in ("overdue", "urgent", "soon")
    if important and urgent:
        return "Q1"  # important + urgent — do
    if important:
        return "Q2"  # important, not urgent — schedule (the starved quadrant)
    if urgent:
        return "Q3"  # urgent, not important — delegate or shrink
    return "Q4"  # neither — drop or defer


def _monday_of(today: date) -> date:
    return today - timedelta(days=today.weekday())


def enrich_task(task: dict, today: date) -> dict:
    """Compact a task and attach the deliberation signals."""
    out = {k: task.get(k) for k in _BRIEF_FIELDS}

    urgency, days_to_due = urgency_of(task.get("due"), today)
    out["urgency"] = urgency
    out["days_to_due"] = days_to_due
    out["quadrant"] = quadrant_of(task.get("importance"), urgency)

    captured = _parse_date(task.get("captured"))
    age_days = (today - captured).days if captured else None
    out["age_days"] = age_days

    out["starved"] = bool(
        out["quadrant"] == "Q2" and age_days is not None and age_days >= STARVED_AFTER_DAYS
    )

    duration = task.get("duration")
    out["sand"] = bool(duration is not None and duration <= SAND_MAX_MINUTES)
    out["rock_candidate"] = bool(
        task.get("importance") == "high"
        and (duration is None or duration >= ROCK_MIN_MINUTES)
    )
    out["has_detail"] = bool(task.get("start") or task.get("notes"))
    return out


def build_brief(backlog: dict, today: date, planning_dir) -> dict:
    """Build the full session brief from a `plan backlog --json` payload."""
    active = backlog.get("active")
    tasks = backlog.get("tasks", [])

    enriched = [enrich_task(t, today) for t in tasks]
    enriched_active = enrich_task(active, today) if active else None

    every = enriched + ([enriched_active] if enriched_active else [])
    counts = {q: sum(1 for t in every if t["quadrant"] == q) for q in ("Q1", "Q2", "Q3", "Q4")}
    counts["total"] = len(every)
    counts["starved"] = sum(1 for t in every if t["starved"])
    counts["overdue"] = sum(1 for t in every if t["urgency"] == "overdue")
    counts["sand"] = sum(1 for t in every if t["sand"])

    monday = _monday_of(today)
    brief = {
        "today": today.isoformat(),
        "week_of": monday.isoformat(),
        "week_doc_path": str(planning_dir / f"week-{monday.isoformat()}.md"),
        "counts": counts,
        "active": enriched_active,
        "tasks": enriched,
    }
    log.info(
        "DONE stage=brief total=%d q1=%d q2=%d starved=%d overdue=%d",
        counts["total"],
        counts["Q1"],
        counts["Q2"],
        counts["starved"],
        counts["overdue"],
    )
    return brief
