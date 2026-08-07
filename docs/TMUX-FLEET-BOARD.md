# The tmux fleet board

The fleet view can tell you what every agent is doing. What it cannot tell you,
on its own, is **which of them have done something since you last looked** —
and that is the only question that matters when six tabs are running at once.

Answering it needs one fact the container can never observe: when you looked at
a tab. tmux runs on the Mac; a session runs inside a container that has no
`$TMUX_PANE`, no tmux socket, and no way to acquire either. So the host writes
the fact, and the fleet renderer joins it in later.

Three host-side pieces are in this kit — two that write the facts, one that
shows them:

| Piece | Written by | File |
|---|---|---|
| Which pane holds which container | `claude.sh` (`write_pane_map`) | `$WORKSPACE/.multiplai/data/tmux/panes.json` |
| When each pane was last looked at | `dotfiles/scripts/fleet-viewed.sh`, via tmux hooks | `$WORKSPACE/.multiplai/data/tmux/viewed/<n>` |
| The board itself, in your status bar | `dotfiles/scripts/fleet-bar` + `fleet-bar-render.py` | `$WORKSPACE/.multiplai/data/tmux/bar.txt` |

The join — *is this marker newer than what that agent last did?* — happens at
render time in the `multiplai-context` plugin. Neither host-side piece knows
anything about seen-ness; they write facts, and the reader draws the conclusion.

The pane map is automatic: `claude.sh` writes it on every launch, nothing to
configure. The viewed markers need four lines in your own `~/.tmux.conf`,
below.

## Wiring the hooks

**The kit does not edit `~/.tmux.conf`.** It is your file, it lives outside the
workspace, and a container-side agent cannot see it. Paste this yourself, then
`tmux source-file ~/.tmux.conf`:

```tmux
set -g focus-events on
set -g @fleet-viewed '~/path/to/multiplai-kit/dotfiles/scripts/fleet-viewed.sh'

set-hook -g after-select-pane   'run-shell -b "#{@fleet-viewed} #{pane_id}"'
set-hook -g after-select-window 'run-shell -b "#{@fleet-viewed} #{pane_id}"'
set-hook -g client-focus-in     'run-shell -b "#{@fleet-viewed} #{pane_id}"'
set-hook -g after-rename-window 'run-shell -b "#{@fleet-viewed} #{pane_id}"'
```

Replace the path with wherever you cloned the kit — and **point it at the
installed `dotfiles/scripts/`, not a copy**. Both host-side scripts find your
workspace by reading `.workspace`, which `setup.sh` writes one directory above
them; a script moved somewhere else loses that and goes silent, since neither
`$WORKSPACE` nor `$CLAUDE_CONFIG_DIR` exists in a tmux server's environment.
(If you must relocate them, set `WORKSPACE` for the tmux server instead:
`set-environment -g WORKSPACE /path/to/workspace`.)

Three details are load-bearing:

- **`set-hook -g`, never `-ga`.** `-ga` *appends*, so every config reload stacks
  another copy of the hook and the script runs N times per pane switch. `-g`
  replaces.
- **`run-shell -b`** backgrounds it, so a pane switch never waits on a
  filesystem write.
- **`focus-events on`** is what makes `client-focus-in` fire. Without it,
  switching back to the terminal from another app does not count as looking,
  and a tab you have been staring at reads as unseen.

`after-rename-window` is there because the marker carries the window name, so
renaming a tab refreshes the label the fleet view shows for it.

All four hooks were verified to exist and accept a binding on tmux 3.4.

## What the marker looks like

One file per pane, named for the pane id with the `%` stripped (`%12` → `12`).
Exactly three lines:

```
2026-08-06T21:24:02Z
pi-eval
/private/tmp/tmux-501/default
```

The timestamp, the window name at that moment, and the tmux server socket.

The server line is not decoration. **tmux recycles pane ids per server**, so
`%12` on one server and `%12` on another are unrelated panes. A reader must
compare the marker's server against the one recorded in `panes.json` and ignore
the marker when they differ. Falling back to "not seen" is harmless; crediting
one tab's attention to a different session is the one failure this feature
must not have.

## Cost, and why the script looks the way it does

It runs on **every** pane switch, every window switch, and every time the
terminal regains focus. That budget is the design: pure bash, no `python`, no
`jq`, one `tmux display-message` (batched, both facts in a single call), one
`printf` redirect.

It also **never prints**. tmux puts a hook's stderr in your terminal, so every
failure path — no workspace, unwritable data dir, a pane id that is not a pane
id, no tmux at all — exits 0 in silence. Every one of those is ordinary: this
is an enrichment over a fleet view that works fine without it.

Markers are pruned at 7 days on each run. Pane ids climb for the life of a tmux
server, so without pruning the directory grows forever — and a marker's whole
question ("have I looked at this since it last did something?") is about the
last few minutes, so a week-old file has no reader.

## The board itself

The two files above are the *facts*. The board is what shows them: **the tmux
status bar, several lines high, in every window.** Not a pane, not a daemon,
nothing to start or supervise — `status-interval` already fires on a timer
inside a process that is always running, so tmux is the scheduler.

It looks like this:

```
FLEET 6 fronts · 2 need you · ⚠1 collision · upd 12s
✋ pi-eval          DolceEngine   18m  permission — bash
✋ fleet-readable   mktplace       3m  approve edit to fleet.py
+3 more · 👀2 seen · ⚠fleet.py · PRs 3 14m
```

Header on the first line, agents in the middle, the tail on the last —
a fixed layout, so your eye lands in the same place every tick rather than
re-reading the bar to find out what moved. Ordering is needs-you, then unseen,
then seen.

### Wiring it up

Same rule as the hooks: this is documentation, and `~/.tmux.conf` is yours to
edit.

```tmux
# 5 is tmux's hard maximum (`set -g status 6` → "unknown value").
# Line 0 stays YOUR status line; lines 1..3 are the fleet.
set -g status 4
set -g status-interval 5
set -g 'status-format[1]' '#(~/path/to/multiplai-kit/dotfiles/scripts/fleet-bar 1)'
set -g 'status-format[2]' '#(~/path/to/multiplai-kit/dotfiles/scripts/fleet-bar 2)'
set -g 'status-format[3]' '#(~/path/to/multiplai-kit/dotfiles/scripts/fleet-bar 3)'
```

**What this costs, plainly: those rows are gone from every window**, and the
bar shows the top few agents, not the fleet. `AGENTS.md` and
`/multiplai-context:fleet-status` remain the full list — the bar is a glance,
and it says `+3 more` rather than pretending otherwise.

Fewer lines works: `status 2` gives the board one row, which renders as the
header alone. More than 5 is not available at any price.

### What it does and does not do

- **It never recommends.** Readings only. "2 need you" is a fact; "merge the
  PR" is advice, and a status bar is the wrong surface on which to argue.
- **It never looks confident about stale data.** Ages are recomputed from the
  scan's own stamp on every tick, so the clock stays live between scans, and
  past ten minutes the header says `⚠stale`.
- **It never hides silently.** Overflow is an explicit `+N more`.
- **"Not collected" is not "none".** A section nobody has scanned reads
  `PRs not collected`; a scan that found nothing reads `PRs none`. A section
  carried from an earlier `/fleet-status` carries its own age (`PRs 3 14m`).

Signal is carried by markers — `✋` needs you, `●` working, `👀` seen, `⚠`
collision or stale — rather than colour. tmux substitutes `status-format` in a
single pass, so a `#[fg=red]` inside *content* is printed literally rather than
interpreted; styling has to live in the format string, where the data cannot
reach it. That is also why content is sanitized before it reaches the cache:
checkpoint text is LLM-written from session transcripts, and it is stripped of
control characters and format-opening sequences on the way in.

### Cost, and the two guards

`fleet-bar` is called once per line per tick per attached client. It reads a
pre-rendered cache and prints one line; when the cache goes stale (5s), exactly
one caller regenerates it and the rest print what is already there. The lock is
an atomic `mkdir`, so the kernel picks the winner — and a lock older than a
minute is cleared, because a crashed render must not pin the board to whatever
it last showed.

Like the marker script, **it never emits a diagnostic**: its stdout *is* the
status bar. No workspace, no cache, no renderer, no python3 — all print one
empty line and exit 0.

`fleet-bar-render.py` is **stdlib-only and reads data files only**. It does not
import plugin code, does not shell out to `fleet_status.py`, and is never run
through `uv`. That is a boundary, not a packaging preference: the plugin's
manifest and cache are container-writable, so a host process that resolved
plugin code would execute whatever a container could write — the same reasoning
that keeps `claude.sh`'s drain path host-side. `evals/unit/test_fleet_bar.py`
asserts it.

## Checking it works

Switch panes, then look:

```bash
ls -l "$WORKSPACE/.multiplai/data/tmux/viewed/"
cat "$WORKSPACE/.multiplai/data/tmux/viewed/"*
```

A file per pane you have visited, each three lines, the timestamp moving as you
switch. If nothing appears: check the path in `@fleet-viewed` resolves, and run
the script by hand (`dotfiles/scripts/fleet-viewed.sh %1`) — by contract it
stays silent when it fails, so a hand-run that writes nothing means the
workspace did not resolve.

The board itself has the same failure signature, and it is worth knowing that
**an empty bar and an idle fleet look identical**. Both scripts print nothing
and exit 0 when they cannot find the workspace, by design — a status bar is the
wrong place for an error message. So if the bar is blank, confirm resolution
before concluding there is nothing to show:

```bash
dotfiles/scripts/fleet-bar 1                       # as tmux runs it
WORKSPACE=/path/to/workspace dotfiles/scripts/fleet-bar 1   # forced
```

A header from the second and nothing from the first means the marker is not
where the script expects it — check that `dotfiles/.workspace` exists and that
you wired tmux to the installed script rather than a copy.
