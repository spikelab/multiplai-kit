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
| The board itself, in a terminal | `dotfiles/scripts/fleet-watch` + `fleet-render.py` | — (drawn, not stored) |

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

The two files above are the *facts*. The board is what shows them: **a terminal
you keep on screen**, beside or below the one running tmux.

```bash
~/path/to/multiplai-kit/dotfiles/scripts/fleet-watch      # redraw every 5s
~/path/to/multiplai-kit/dotfiles/scripts/fleet-watch 2    # every 2s
```

Nothing to wire up and nothing to configure — it finds your workspace the same
way the marker script does, and any key quits. Redirected or piped it draws
once and exits, so `fleet-watch > board.txt` is a snapshot rather than a hung
process.

It looks like this:

```
FLEET 6 fronts · 2 need you · ⚠1 collision · upd 12s
✋ pi-eval          DolceEngine   18m  permission — bash
✋ fleet-readable   mktplace       3m  approve edit to fleet.py
+3 more · 👀2 seen · ⚠fleet.py · PRs 3 14m
```

Header on the first line, agents in the middle, the tail on the last —
a fixed layout, so your eye lands in the same place every tick rather than
re-reading the board to find out what moved. Ordering is needs-you, then
unseen, then seen. `AGENTS.md` and `/multiplai-context:fleet-status` remain the
full list; this is a glance, and it says `+3 more` rather than pretending
otherwise.

### It used to be the status bar

Until 2026-08-07 the board was `status-format` lines in tmux itself, drawn by a
`fleet-bar` script this kit no longer ships. On paper that was the better
placement — ambient, in every window, nothing to start or supervise, with
`status-interval` as a free scheduler. In practice it cost three rows of every
window permanently to show two agents, tmux caps `status` at five lines, and a
`#()` job can neither wrap nor scroll, so half a wide terminal sat empty while
the checkpoint text was cut at 44 characters.

The renderer still carries that budget — the fixed columns and the `+N more`
are a status bar's constraints outliving the status bar. Lifting them is the
fleet console's job, not a patch to `fleet-render.py`.

### What it does and does not do

- **It never recommends.** Readings only. "2 need you" is a fact; "merge the
  PR" is advice, and a board you glance at is the wrong surface on which to
  argue.
- **It never looks confident about stale data.** Ages are recomputed from the
  scan's own stamp on every tick, so the clock stays live between scans, and
  past ten minutes the header says `⚠stale`.
- **It never hides silently.** Overflow is an explicit `+N more`.
- **"Not collected" is not "none".** A section nobody has scanned reads
  `PRs not collected`; a scan that found nothing reads `PRs none`. A section
  carried from an earlier `/fleet-status` carries its own age (`PRs 3 14m`).

Signal is carried by markers — `✋` needs you, `●` working, `👀` seen, `⚠`
collision or stale — rather than colour. They survive a pipe, a `less`, and a
terminal with no colour, and they cost nothing to emit.

Content is still sanitized on the way in: checkpoint text is LLM-written from
session transcripts, and this repaints every few seconds, so one escape
sequence arriving through data would corrupt every frame after it. Control
characters are stripped. The companion strip — a `#` opening a tmux format
sequence — went with the status bar, since nothing reads this output as a tmux
format any more.

### The one guard that matters

`fleet-render.py` is **stdlib-only and reads data files only**. It does not
import plugin code, does not shell out to `fleet_status.py`, and is never run
through `uv`. That is a boundary, not a packaging preference: the plugin's
manifest and cache are container-writable, so a host process that resolved
plugin code would execute whatever a container could write — the same reasoning
that keeps `claude.sh`'s drain path host-side.
`evals/unit/test_fleet_render.py` asserts it, and
`evals/unit/test_fleet_watch.py` asserts the same of the script that calls it.

One rule is inverted between the two host-side scripts, on purpose.
`fleet-viewed.sh` is a tmux hook and **never** prints: tmux puts a hook's
stderr in your terminal, and every one of its failure paths is ordinary.
`fleet-watch` **does** print — a person ran it and is looking at the output, so
"cannot resolve the workspace" is the answer they came for. The silent version
of that failure is exactly what made a blank status bar indistinguishable from
an idle fleet.

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
