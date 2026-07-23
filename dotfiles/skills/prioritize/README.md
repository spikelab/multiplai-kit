# prioritize

A deliberation session for the plan-cli backlog — the step between capturing
work and doing it.

plan-cli already handles capture (`plan capture`) and execution (`plan now`).
What it doesn't do is help decide **what actually matters** when the backlog has
grown faster than it's being worked. That's this skill: a conversation that
argues relative importance and urgency, shapes the week and the day, and writes
the result back into `tasks.db`.

## Use it

```
/prioritize            # weekly frame, then the daily pull
/prioritize my week    # set the week's commitments
/prioritize my day     # pull today's focus from the week
```

## What happens

1. **Loads** the backlog through `plan backlog --json` and tags each task with
   its Eisenhower quadrant, urgency, age, and whether it's been starved.
2. **Argues** the ranking with you — especially the important-but-not-urgent
   work that keeps getting displaced. It's meant to push back, not agree.
3. **Shapes the day** into one rock (the `[now]` focus), a few pebbles, and
   sand for the gaps.
4. **Writes** the decisions back through plan-cli's own validated round-trip,
   and relays exactly what changed.
5. **Outputs** a week doc at `$PLANNING_DIR/week-<monday>.md` cross-linked to
   backlog ids, plus today's shortlist.

## Guarantees

- **One source of truth.** `tasks.db` is the only store. This skill never writes
  to it directly — every change goes through plan-cli.
- **Undo.** Each session snapshots the backlog first. `revert` restores order,
  importance, dates and focus. It can't un-complete a task or clear a duration
  it added, and it names anything it couldn't restore.
- **Same backlog everywhere.** `PLANNING_DIR` points the Mac terminal and the
  container session at one database, so `plan capture` from a terminal and a
  prioritization conversation in Claude Code see the same list.

## Requirements

- plan-cli, found via `$PLAN_CLI_BIN`, `plan` on `PATH`, `$PLAN_CLI_HOME`, or
  `$WORKSPACE/github/plan-cli`.
- `PLANNING_DIR` set to the shared planning directory (the kit's `claude.sh`
  defaults it to `$WORKSPACE/.planning`).

## Development

See `scripts/CLAUDE.md` — particularly the two plan-cli parser facts that
constrain how the backlog markdown is written.
