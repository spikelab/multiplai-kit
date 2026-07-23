---
name: prioritize
description: Talk through a backlog and decide what actually matters — a deliberation session between capture and execution. Reads the plan-cli backlog, argues relative importance and urgency (Eisenhower), shapes the week and the day (rocks/pebbles/sand), and writes the decisions back to tasks.db. Use when the user says "prioritize", "plan my week", "plan my day", "what should I work on", "help me think through my backlog", or when a backlog has grown faster than it's being worked.
---

# Prioritize

## Overview

plan-cli covers capture (`plan capture`) and execution (`plan now`). This skill is
the missing middle: the deliberation where a pile of captured items becomes an
argued order. It is a **conversation**, not a report — the value is in the
pushback, not in restating the backlog.

`tasks.db` stays the single source of truth. Every write goes through plan-cli's
own validated markdown round-trip via `prioritize_session`.

## Setup (run once per session)

```bash
export PYTHONPATH="$CLAUDE_CONFIG_DIR/hooks:${PYTHONPATH:-}"
cd "$CLAUDE_CONFIG_DIR/skills/prioritize/scripts"
```

All commands below run from that directory. Always pass `--session-id`.

## Which mode

| Signal | Mode |
|---|---|
| "plan my week", Monday-ish, or no week doc for the current week | **Weekly frame** |
| "plan my day", "what should I work on", a week doc already exists | **Daily pull** |
| "prioritize", "help me think through my backlog" | **Weekly frame**, then offer the daily pull |

Check for the week doc at the `week_doc_path` in the brief. If unsure which the
user wants, ask — it's one question and it changes the whole session.

## Step 1 — Load

```bash
python3 -m prioritize_session --session-id "{session_id}" brief --snapshot
```

Returns `today`, `week_of`, `week_doc_path`, `counts`, `active`, `tasks`, and a
`snapshot_path` for revert. Each task carries `quadrant` (Q1–Q4), `urgency`,
`days_to_due`, `age_days`, `starved`, `sand`, `rock_candidate`, `has_detail`.

The brief deliberately omits `notes` and first steps. When a specific task needs
that context to be argued about, fetch it:

```bash
python3 -m prioritize_session --session-id "{session_id}" detail --ids 12,45
```

If a week doc exists, read it — the week's commitments are context for today.

## Step 2 — Deliberate (importance × urgency)

**Do not dump the brief back at the user.** They wrote these tasks; they don't
need them read aloud. Open with the tension the numbers actually show — the
overdue Q1 pileup, the Q2 item that's been sitting 40 days, the Q3 block eating
the week.

The quadrants are an opening position, not a verdict:

- **Q1 — important + urgent.** Real, but a crowded Q1 usually means Q2 was
  neglected earlier. Note the pattern; don't lecture.
- **Q2 — important, not urgent.** The starved quadrant, and the reason this
  skill exists. `starved: true` means it has sat 14+ days. Ask directly: what
  keeps displacing this? Should it get a due date to survive?
- **Q3 — urgent, not important.** Interrogate it. Is it genuinely someone
  else's deadline? Can it be shrunk, batched, or dropped?
- **Q4 — neither.** Say the quiet part: this belongs in the backlog's basement
  or out of it entirely.

Remember `importance` is three-valued in plan-cli but the matrix is binary —
`high` is the important half. A `medium` item landing in Q3/Q4 is a prompt to
ask whether it's really medium.

Argue. If the user's stated priority conflicts with their own stated goals or
with a deadline they set, say so plainly. Agreeing with a bad ordering is the
failure mode here. But the user's call wins once they've heard the argument.

Turn the conversation into concrete changes: rank order, importance moves, due
dates added or removed.

## Step 3 — Shape the day (rocks / pebbles / sand)

Compose the day out of what was just ranked:

- **One rock.** The high-leverage important item that gets the protected block.
  This becomes the `[now]` focus — exactly one. `rock_candidate: true` flags
  high-importance work with a real block of time (or no estimate, which usually
  means the big scary kind).
- **2–3 pebbles.** Real work that fits around the rock.
- **Sand.** ≤15-minute fills (`sand: true`) for the gaps between meetings.

Be honest about capacity. If the rock is 120 minutes and the day already has
four hours of meetings, the day doesn't fit — say that and cut something rather
than producing a list that quietly fails.

Rock/pebble/sand is **not stored** — it's the shape of today's output, not a DB
field. Keep it in the conversation and the day plan.

## Step 4 — Persist

Write a changeset JSON, then apply it:

```json
{
  "now": 662,
  "order": [662, 665, 12],
  "updates": {
    "665": { "importance": "high", "due": "2026-07-25" },
    "12":  { "done": true }
  }
}
```

- `now` — task id to focus, `null` to clear focus. **Omit the key** to leave the
  current focus alone.
- `order` — a preference list, not a full permutation. Named ids float to the
  top of their importance section; everything else keeps its relative order.
  Ordering **across** importance levels isn't expressible (the backlog format
  groups by section) — to move a task above a more important one, change its
  importance.
- `updates` — per task id: `importance`, `due` (`YYYY-MM-DD` or `null` to
  clear), `duration` (minutes, cannot be cleared), `type`, `title`, `done`.

```bash
# See the markdown without writing anything:
python3 -m prioritize_session --session-id "{session_id}" apply --changes /tmp/changes.json --dry-run

# Write it:
python3 -m prioritize_session --session-id "{session_id}" apply --changes /tmp/changes.json
```

Apply prints plan-cli's own change summary. **Relay it** — the user should see
what actually changed, not a claim that it worked. If plan-cli reports
validation issues, surface them; those lines were skipped.

To undo the whole session:

```bash
python3 -m prioritize_session --session-id "{session_id}" revert
```

Revert restores order, importance, due, type, title and focus. It cannot restore
completions or clear a duration the session added — anything it couldn't restore
comes back in `unrestorable`.

## Step 5 — Output

**Weekly frame** — write/refresh the week doc at the brief's `week_doc_path`
(`$PLANNING_DIR/week-<monday>.md`): ~5 ordered commitments, each with a
`Done when:` line and its backlog id, so the doc and the DB stay cross-linked.

```markdown
# Week of 2026-07-20

## Commitments
1. **Ship the Q3 board deck** — `[645]`
   Done when: Deck sent to the board.
2. ...

## Explicitly not this week
- [652] Website copy rewrite — deferred; revisit next Monday.
```

The "not this week" section matters as much as the list. An unstated deferral
comes back as guilt.

**Daily pull** — print today's shape and hand off:

```
Rock:    [645] Write Q3 board deck (~90min) → set as [now]
Pebbles: [662] Update resume (~45min), [665] Follow up with Bob (~15min)
Sand:    [671] Renew domain (~5min)

Run `plan now` to start.
```

## Adding tasks mid-session

If the conversation surfaces work that isn't logged, it isn't real yet — log it.
Confirm first (title + "done when"), then:

```bash
plan add "<title>" --type <type> --importance <level> --done-when "<definition>"
```

It lands at the bottom of the backlog; re-rank it in the same session if it
deserves better.

## Failure modes to avoid

- **Reading the backlog aloud.** They wrote it. Lead with the tension.
- **Agreeing to be pleasant.** If the ordering doesn't survive scrutiny, say so.
- **Silent writes.** Always relay plan-cli's summary of what changed.
- **A day plan that doesn't fit.** Cut it in the conversation, not in reality.
- **Inventing tasks.** Only ids from the brief exist. `apply` rejects unknown
  ids rather than guessing — reload the brief if it complains.

## Resources

- `references/frameworks.md` — the two frameworks in more depth, and the
  questions that make each one bite.
- `scripts/prioritize_session/` — the CLI. See `scripts/CLAUDE.md` for how the
  write path stays safe.
