#!/bin/bash
# fleet-viewed.sh — record that a tmux pane was just looked at.
#
# Bound to tmux's pane-selection hooks (see docs/TMUX-FLEET-BOARD.md), so this
# runs on *every* pane switch, every window switch, and every time the terminal
# regains OS focus. That budget is the whole design:
#
#   - pure bash, no `python`, no `jq`, no temp files;
#   - exactly one `tmux` call, batched to fetch both facts at once;
#   - one `printf` redirect to write the marker.
#
# It writes a fact and nothing else. The join — is this newer than what that
# agent last did? — happens later, at render time, in the reader. That
# separation is deliberate: this script must never grow a notion of which
# session a pane belongs to, because the pane→session map is written by the
# launcher and is not this script's to interpret.
#
# **It must never print.** tmux paints a hook's stdout nowhere useful and its
# stderr into your terminal, so every path here ends in a silent `exit 0`. A
# missing workspace, an unwritable data dir, a pane id that is not a pane id,
# or no tmux at all are all ordinary — this is an enrichment over a fleet view
# that works fine without it.

# --- where the data lives -----------------------------------------------------
# The resolution chain is shared with `fleet-panes.sh` —
# lib/resolve-workspace.sh sets `ws`. Here only the `$0`-relative rung can
# fire in practice: this runs on the **host**, from a tmux hook that inherits
# the tmux *server's* pre-launcher environment, and `$CLAUDE_CONFIG_DIR` is
# set by the launcher for the container. `setup.sh` writes the marker beside
# these scripts (`dotfiles/.workspace`). The readability guard keeps the
# no-output contract even on a partial install.
_ws_lib="$(dirname "$0")/lib/resolve-workspace.sh"
[ -r "$_ws_lib" ] || exit 0
. "$_ws_lib"
[ -n "$ws" ] || exit 0

viewed_dir="$ws/.multiplai/data/tmux/viewed"

# --- the pane id --------------------------------------------------------------
# `%12` becomes `12`, which is filesystem-safe by construction. Anything that
# is not `%` followed by digits is not a pane id tmux issued, so there is
# nothing to record and nothing to complain about — this is the guard that
# stops a hook misconfiguration from writing arbitrary filenames.
target="${1:-}"
pane="${target#%}"
case "$pane" in
    ''|*[!0-9]*) exit 0 ;;
esac

# --- prune --------------------------------------------------------------------
# Markers must not accumulate: one file per pane id, and pane ids climb for the
# life of a tmux server. Seven days is chosen against what a marker is *for* —
# "have I looked at this since it last did something" is a question about the
# last few minutes, so anything a week old has no reader. Guarded so a `find`
# that is missing, restricted, or on a read-only mount stays silent.
find "$viewed_dir" -type f -mtime +7 -delete 2>/dev/null

# --- the marker ---------------------------------------------------------------
# One `display-message` for both facts. The window name is here rather than
# only in the launcher's pane map because a tab gets its real name *mid*
# session — you name it once you know what the work is — and this hook is
# already bound to `after-rename-window`, so the label stays fresh with no
# extra machinery.
#
# The server path is line 3 and is load-bearing: tmux recycles pane ids per
# server, so a reader must ignore this marker unless the server matches the one
# that issued the pane id it is joining to. Degrading to "not seen" is safe;
# attributing one pane's attention to another session is the one failure this
# feature must not have.
#
# `-t "$target"` is not optional. Without a target, `display-message` resolves
# `#{window_name}` against the *current* pane of the current client — and these
# hooks fire precisely at the moments that is in flux. On `after-select-window`
# and `client-session-changed` tmux hands the pane in `#{hook_pane}` while the
# client's own current pane may still be the one being switched away from, so
# an untargeted read writes the old window's name into the new pane's marker.
# The marker's whole job is to say what you are looking at.
info=$(tmux display-message -p -t "$target" '#{window_name}'$'\n''#{socket_path}' 2>/dev/null) || exit 0
window="${info%%$'\n'*}"
server="${info#*$'\n'}"
[ "$server" = "$info" ] && server=""

mkdir -p "$viewed_dir" 2>/dev/null || exit 0
printf '%s\n%s\n%s\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    "$window" \
    "$server" \
    > "$viewed_dir/$pane" 2>/dev/null

exit 0
