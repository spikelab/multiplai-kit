"""Turn a decision changeset into the backlog markdown plan-cli parses.

The write path is deliberately indirect: this module never touches the DB. It
renders markdown in plan-cli's own backlog format and hands it to
`plan backlog --apply`, so every write goes through plan-cli's validation, its
rank semantics, and its one-`[now]`-at-a-time invariant.

Two properties of plan-cli's parser drive the design here:

  * **Rank is file order.** The parser numbers non-done task lines 1..N as it
    reads. So a partial file silently renumbers — every task must be rendered
    every time. `render_backlog` always emits the whole backlog.
  * **Importance is the enclosing section.** A task's `## High/Medium/Low`
    heading sets its importance; an inline `[high]`/`[low]` token overrides it
    for that line. Because rank is global but sections are ordered
    High → Medium → Low, ordering *across* importance levels isn't
    expressible — to move a task above a more important one, change its
    importance.
"""

from __future__ import annotations

import logging
import re

log = logging.getLogger(__name__)

VALID_IMPORTANCE = ("high", "medium", "low")
VALID_TYPES = ("sales", "client-work", "product-studio", "marketing", "admin", "personal")
UPDATABLE_FIELDS = ("importance", "due", "duration", "type", "title", "done")

SECTION_LABEL = {"high": "High", "medium": "Medium", "low": "Low"}

# The parser splits a task line on this separator to find the extras segment,
# so a title containing it would be silently truncated.
EXTRAS_SEPARATOR = " — "

# A trailing backticked word on a title is read as the task type.
_TRAILING_TYPE_RE = re.compile(r"`[^`]+`\s*$")

_DUE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class ChangesetError(ValueError):
    """The changeset is malformed or refers to tasks that aren't in the backlog."""


def _validate_update(task_id: int, fields: dict) -> None:
    unknown = set(fields) - set(UPDATABLE_FIELDS)
    if unknown:
        raise ChangesetError(
            f"task {task_id}: unknown update field(s) {sorted(unknown)}; "
            f"allowed: {list(UPDATABLE_FIELDS)}"
        )

    if "importance" in fields and fields["importance"] not in VALID_IMPORTANCE:
        raise ChangesetError(
            f"task {task_id}: importance must be one of {list(VALID_IMPORTANCE)}, "
            f"got {fields['importance']!r}"
        )

    if "type" in fields and fields["type"] is not None and fields["type"] not in VALID_TYPES:
        raise ChangesetError(
            f"task {task_id}: type must be one of {list(VALID_TYPES)} or null, "
            f"got {fields['type']!r}"
        )

    due = fields.get("due")
    if "due" in fields and due is not None and not _DUE_RE.match(str(due)):
        raise ChangesetError(
            f"task {task_id}: due must be YYYY-MM-DD or null, got {due!r}"
        )

    duration = fields.get("duration")
    if "duration" in fields:
        if duration is None:
            raise ChangesetError(
                f"task {task_id}: duration cannot be cleared through the backlog "
                "format (there is no token for it) — set a new value instead"
            )
        if not isinstance(duration, int) or duration <= 0:
            raise ChangesetError(
                f"task {task_id}: duration must be a positive integer of minutes, "
                f"got {duration!r}"
            )

    title = fields.get("title")
    if "title" in fields:
        if not title or not str(title).strip():
            raise ChangesetError(f"task {task_id}: title cannot be empty")
        _validate_title(task_id, str(title))


def _validate_title(task_id: int, title: str) -> None:
    if EXTRAS_SEPARATOR in title:
        raise ChangesetError(
            f"task {task_id}: title contains {EXTRAS_SEPARATOR!r}, which plan-cli "
            "reads as the start of the due/duration segment — the title would be "
            "truncated. Use a plain hyphen or a colon."
        )
    if _TRAILING_TYPE_RE.search(title):
        raise ChangesetError(
            f"task {task_id}: title ends with a backticked word, which plan-cli "
            "reads as the task type. Reword it."
        )


def apply_updates(backlog: dict, changeset: dict) -> tuple[list[dict], int | None]:
    """Fold the changeset into an in-memory task list.

    Returns (tasks, now_id) where tasks carry a `done` flag for lines that
    should render as `[x]`. Nothing is written.
    """
    updates = changeset.get("updates") or {}
    active = backlog.get("active")
    tasks = [dict(t) for t in backlog.get("tasks", [])]
    if active:
        tasks.insert(0, dict(active))

    by_id = {t["id"]: t for t in tasks}

    for raw_id, fields in updates.items():
        try:
            task_id = int(raw_id)
        except (TypeError, ValueError):
            raise ChangesetError(f"update key {raw_id!r} is not a task id")
        if task_id not in by_id:
            raise ChangesetError(
                f"task {task_id} is not in the current backlog — reload the brief; "
                "it may have been completed elsewhere"
            )
        if not isinstance(fields, dict):
            raise ChangesetError(f"task {task_id}: update must be an object")
        _validate_update(task_id, fields)
        by_id[task_id].update(fields)
        if "due" in fields and fields["due"] is None:
            # Distinguish "explicitly cleared" from "never had one" — only the
            # former should render the literal `due none` token.
            by_id[task_id]["_clear_due"] = True

    # Titles we didn't set still have to survive the round trip.
    for task in tasks:
        if not task.get("done"):
            _validate_title(task["id"], str(task.get("title") or ""))

    # Focus: absent key means "leave the current focus alone".
    if "now" in changeset:
        now_id = changeset["now"]
        if now_id is not None:
            now_id = int(now_id)
            if now_id not in by_id:
                raise ChangesetError(f"now: task {now_id} is not in the current backlog")
            if by_id[now_id].get("done"):
                raise ChangesetError(f"now: task {now_id} is also marked done")
    else:
        now_id = active["id"] if active else None

    return tasks, now_id


def order_tasks(tasks: list[dict], order: list[int] | None) -> list[dict]:
    """Sort within importance groups: listed ids first, then existing rank.

    `order` is a preference list, not a full permutation — naming three ids
    floats those three to the top of their sections and leaves everything else
    in its current relative order.
    """
    order = order or []
    known = {t["id"] for t in tasks}
    unknown = [i for i in order if i not in known]
    if unknown:
        raise ChangesetError(f"order refers to tasks not in the backlog: {unknown}")

    position = {task_id: idx for idx, task_id in enumerate(order)}
    big = len(order) + 1

    def sort_key(task: dict):
        if task["id"] in position:
            return (0, position[task["id"]], 0)
        rank = task.get("rank")
        return (1, big, rank if rank is not None else 10**9)

    return sorted(tasks, key=sort_key)


def render_task_line(task: dict, *, now: bool = False, importance_token: str | None = None) -> str:
    """Emit one task line in plan-cli's format."""
    done = bool(task.get("done"))
    checkbox = "x" if done else " "
    tokens = ""
    if importance_token:
        tokens += f"[{importance_token}] "
    if now:
        tokens += "[now] "

    line = f"- [{checkbox}] [{task['id']}] {tokens}{task['title']}"

    task_type = task.get("type")
    if task_type:
        line += f" `{task_type}`"

    extras = []
    if task.get("_clear_due"):
        # Explicit clear — plan-cli reads the literal "none".
        extras.append("due none")
    elif task.get("due"):
        extras.append(f"due {task['due']}")
    if task.get("duration"):
        extras.append(f"~{task['duration']}min")
    if extras:
        line += EXTRAS_SEPARATOR + " ".join(extras)
    return line


def render_backlog(backlog: dict, changeset: dict) -> str:
    """Render the complete backlog markdown for `plan backlog --apply`."""
    tasks, now_id = apply_updates(backlog, changeset)
    ordered = order_tasks(tasks, changeset.get("order"))

    done_tasks = [t for t in ordered if t.get("done")]
    live = [t for t in ordered if not t.get("done")]

    lines = [
        "# Backlog",
        "",
        "> Written by the `prioritize` skill for `plan backlog --apply`.",
        "> Line order sets rank; the section heading sets importance.",
        "",
    ]

    # Focus first. It sits outside the importance sections, so its importance
    # rides on an explicit inline token rather than an enclosing heading.
    now_task = next((t for t in live if t["id"] == now_id), None) if now_id else None
    if now_task:
        importance = now_task.get("importance") or "medium"
        if importance not in VALID_IMPORTANCE:
            importance = "medium"
        lines.append("## Now")
        lines.append(render_task_line(now_task, now=True, importance_token=importance))
        lines.append("")

    for level in VALID_IMPORTANCE:
        group = [
            t
            for t in live
            if (t.get("importance") or "medium") == level and t is not now_task
        ]
        if not group:
            continue
        lines.append(f"## {SECTION_LABEL[level]}")
        lines.extend(render_task_line(t) for t in group)
        lines.append("")

    if done_tasks:
        # No importance heading — checked lines are consumed by the done path
        # and never reach the rank counter or a field update.
        lines.append("## Completed this session")
        lines.extend(render_task_line(t) for t in done_tasks)
        lines.append("")

    log.info(
        "DONE stage=render live=%d done=%d now=%s",
        len(live),
        len(done_tasks),
        now_id,
    )
    return "\n".join(lines) + "\n"
