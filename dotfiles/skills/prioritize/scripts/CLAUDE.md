# prioritize_session — dev notes

Helper CLI for the `prioritize` skill. Reads the plan-cli backlog, enriches it
for an Eisenhower conversation, and writes ranking decisions back.

## The one rule

**This package never touches `tasks.db`.** Every write is rendered as backlog
markdown and handed to `plan backlog --apply`, so plan-cli owns validation,
rank semantics, and the one-`[now]`-at-a-time invariant. If you find yourself
reaching for sqlite here, the feature belongs in plan-cli instead.

## Two parser facts that constrain `render.py`

Both come from plan-cli's `lib/commands/backlog.js` → `parseAndApply`:

1. **Rank is file order.** The parser numbers non-done task lines 1..N as it
   reads them. A partial file silently renumbers everything in it, so
   `render_backlog` always emits the entire backlog — never a subset.
2. **Importance is the enclosing `## High/Medium/Low` heading** (an inline
   `[high]`/`[low]` token overrides it per line). Sections are emitted in a
   fixed order, so ordering *across* importance levels is not expressible.

Corollaries worth remembering: `## Now` is not a section heading to the parser,
so the focus line carries an explicit inline importance token or its importance
would be left unset. Checked (`[x]`) lines take the done branch before the rank
counter, so they can sit outside the sections. `due none` is the only clear
token — there is no way to clear a duration.

Titles are validated before rendering: a title containing ` — ` would be
truncated at the extras separator, and one ending in a backticked word would be
read as the task type. Both raise `ChangesetError` rather than corrupting a
task.

## Layout

| Module | Job |
|---|---|
| `plan_cli.py` | Finds and runs plan-cli (`$PLAN_CLI_BIN` → PATH → `$PLAN_CLI_HOME` → `$WORKSPACE/github/plan-cli`) |
| `enrich.py` | Urgency, quadrant, age, starved/sand/rock flags; drops `notes`/`start` to keep the brief small |
| `render.py` | Changeset → backlog markdown, with validation |
| `session.py` | Pre-write snapshots and the revert changeset |
| `__main__.py` | `brief` / `detail` / `apply` / `revert`, all emitting JSON |

## Running

```bash
export PYTHONPATH="$CLAUDE_CONFIG_DIR/hooks:${PYTHONPATH:-}"
cd "$CLAUDE_CONFIG_DIR/skills/prioritize/scripts"
python3 -m prioritize_session --session-id test brief
```

`PLANNING_DIR` selects the backlog (the kit sets it to `$WORKSPACE/.planning`).
Point it at a scratch directory to experiment without touching the real one.

## Tests

```bash
PYTHONPATH=. python -m pytest tests/ -q
```

plan-cli is mocked throughout — the suite never runs a subprocess or opens a
database. `tests/conftest.py` resolves `log_utils` from the kit's `hooks/`
directory so the suite doesn't depend on an exported `PYTHONPATH`.

When changing `render.py`, also re-run a live round trip against a scratch
`PLANNING_DIR` — the tests pin this package's behavior, not plan-cli's parser.
