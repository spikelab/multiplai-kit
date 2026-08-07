# The tmux fleet board

The fleet view can tell you what every agent is doing. What it cannot tell you,
on its own, is **which of them have done something since you last looked** —
and that is the only question that matters when six tabs are running at once.

Answering it needs one fact the container can never observe: when you looked at
a tab. tmux runs on the Mac; a session runs inside a container that has no
`$TMUX_PANE`, no tmux socket, and no way to acquire either. So the host writes
the fact, and the fleet renderer joins it in later.

Two host-side pieces produce it, and both are in this kit:

| Piece | Written by | File |
|---|---|---|
| Which pane holds which container | `claude.sh` (`write_pane_map`) | `$WORKSPACE/.multiplai/data/tmux/panes.json` |
| When each pane was last looked at | `dotfiles/scripts/fleet-viewed.sh`, via tmux hooks | `$WORKSPACE/.multiplai/data/tmux/viewed/<n>` |

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

Replace the path with wherever you cloned the kit. Three details are
load-bearing:

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
