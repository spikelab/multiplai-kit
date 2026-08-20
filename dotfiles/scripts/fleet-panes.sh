#!/bin/bash
# fleet-panes.sh — which tmux pane holds which container.
#
#   fleet-panes.sh                  # record what tmux can see right now
#   fleet-panes.sh cc-p-08015414    # …and one container that is about to start
#
# Writes `$WORKSPACE/.multiplai/data/tmux/panes.json`, keyed by **container
# name** — the registry's `hostname` field, and the only stable join key here,
# because `/clear` mints a fresh session id (one container in that registry
# carries nine session UUIDs) while the container name survives every one.
#
# The plugin can never write this. `record_event()` runs *inside* the container
# and tmux runs on the Mac, so `$TMUX_PANE` there is not merely missing — it is
# unknowable. Every tmux fact has to be observed host-side and joined at render
# time, exactly as `live_containers.json` already is.
#
# ## Why this is a live query and not a launch record
#
# It used to be one. `write_pane_map` lived in `claude.sh`, wrote the entry for
# the pane it was launching in, and carried every other tab forward by `grep`-ing
# the file it had written last time. That makes the map a chain: an entry can
# only ever be *preserved*, never acquired, so a container that was running
# before the feature shipped — or before the file was first created — could
# never appear in it, and no process left alive knew which pane it was in.
#
# The fix is the `@cc` pane option `claude.sh` now stamps at launch:
#
#     tmux set-option -p -t "$TMUX_PANE" @cc "$CONTAINER_NAME"
#
# It is on the *pane*, so it survives a tab rename, it cannot be forgotten (the
# launcher sets it, not a convention someone honours), and a non-empty value
# *is* the definition of "this pane is an agent" — an empty one is a shell. So
# the whole fleet is one `tmux list-panes -a` away, the map becomes a cache of
# a current reading rather than an accreted record, and a pane missing from it
# yesterday appears the moment this runs again. No migration, no repair path.
#
# The `@cc` of a *dead* session outlives it — the pane is still there and still
# stamped — which is why `docker ps` is still the cross-check: an `@cc` naming
# a container that is not running is a tab whose session has exited.
#
# ## Two callers, one join
#
# `claude.sh` runs this at both of the roster's call points (before the run, so
# the SessionStart seconds later reads a fresh map with no daemon and no timer;
# after the exit, so a closed tab stops labelling a session that has ended), and
# `fleet-watch` runs it before every redraw. Extracted from the launcher rather
# than copied into the board precisely so there is one implementation: two
# copies of this join is how they drift.
#
# The pre-run call is the reason for the argument. At that moment this launch's
# container is not in `docker ps` yet — it does not exist — so the cross-check
# above would drop it. Naming it says "this one is about to be real".
#
# ## Silence
#
# Best-effort on every path, and it **never prints**. It runs on the launch path
# (where a diagnostic would land in the middle of a session starting) and inside
# `fleet-watch`'s redraw loop (where it would be painted over a frame later).
# No tmux, no `$TMUX`, no docker, an unreadable data dir, a failing query: all
# silent `exit 0`. Losing the map costs a label on a board. It must never cost a
# session.

self="${1:-}"

# --- where the data lives -----------------------------------------------------
# The resolution chain (environment first, then the markers `setup.sh` writes)
# is shared with `fleet-viewed.sh`: lib/resolve-workspace.sh sets `ws`. The
# launcher always has `$WORKSPACE`; a board started from a plain terminal has
# no variable and needs a marker file. The readability guard keeps the
# no-output contract even on a partial install.
ws="${WORKSPACE:-}"
if [ -z "$ws" ]; then
    _ws_lib="$(dirname "$0")/lib/resolve-workspace.sh"
    [ -r "$_ws_lib" ] && . "$_ws_lib"
    unset _ws_lib
fi
[ -n "$ws" ] || exit 0

data_dir="$ws/.multiplai/data"
[ -d "$data_dir" ] || exit 0

# --- when not to look ---------------------------------------------------------
# `$TMUX` is the guard that matters, and it is a guard against *writing*, not
# just against looking. `list-panes -a` only ever enumerates one tmux server:
# the one `$TMUX` points at, or — with no `$TMUX` — whatever happens to be on
# the default socket, which may be nothing at all. A board run in a plain
# terminal that wrote what it saw would empty the map for every reader.
[ -n "${TMUX:-}" ] || exit 0
command -v tmux >/dev/null 2>&1 || exit 0
command -v docker >/dev/null 2>&1 || exit 0

names=$(docker ps --format '{{.Names}}' 2>/dev/null) || exit 0

server=$(tmux display-message -p '#{socket_path}' 2>/dev/null) || exit 0

# One call for the whole server. The fields, in order:
#
#   pane id | @cc | automatic-rename | window name | session name
#
# `|` is the separator, and **three** of these fields are arbitrary text rather
# than two: a window name and a session name are whatever a person typed, and
# `@cc` is a tmux user option anyone can set to anything (which is the same
# reason it is guarded against `"` and `\` below). So tmux strips the separator
# out of all three on the way (`#{s/[|]//:…}`) — the record has to parse before
# anything downstream can sanitise it, and a `|` inside a field does not merely
# corrupt that field, it shifts every field after it: a `@cc` of
# `cc-p-01|0|pwned` parses as cc=`cc-p-01`, auto=`0`, window=`pwned`, which
# smuggles a label past both the `automatic-rename` gate and the strip. Only the
# pane id and `automatic-rename` come from alphabets tmux controls.
panes=$(tmux list-panes -a -F \
    '#{pane_id}|#{s/[|]//:@cc}|#{automatic-rename}|#{s/[|]//:window_name}|#{s/[|]//:session_name}' \
    2>/dev/null) || exit 0

now=$(date -u +%Y-%m-%dT%H:%M:%SZ)

# One line per entry, deliberately: the foreign-server merge below re-reads this
# file with nothing but `grep`, because `jq` is optional on a host and this runs
# on the launch path.
entries=""
seen=""
self_pane=""
self_window=""
self_session=""
self_found=""

add_entry() {
    # Sanitize here, not in the read loop: window/session only matter once they
    # are written as JSON string values, and the overwhelming majority of panes
    # are shell panes filtered out before ever reaching this point — sanitizing
    # them all cost two tr forks per pane on the server.
    _w=$(printf '%s' "$3" | tr -d '"\\[:cntrl:]')
    _s=$(printf '%s' "$4" | tr -d '"\\[:cntrl:]')
    entries="${entries:+$entries,
}    \"$1\": {\"pane\": \"$2\", \"server\": \"$server\", \"window\": \"$_w\", \"session\": \"$_s\", \"at\": \"$now\"}"
    seen="$seen
$1"
}

while IFS='|' read -r pane cc auto window session; do
    # The map exists to answer "which pane", so a record that cannot is worse
    # than a missing one. `%12` is the only shape tmux issues.
    case "$pane" in %[0-9]*) ;; *) continue ;; esac

    # Only a *pinned* name is a label. With `automatic-rename` on, tmux is
    # naming the window after whatever it last ran — `bash` in a fresh window,
    # `docker` mid-session — and a board that renders `mktplace@docker` is worse
    # than one that falls through to the worktree/branch label it already knows
    # how to build. `off` is the one state that means a human typed this string.
    #
    # tmux renders the option as `0`/`1` in a format rather than `off`/`on`;
    # both spellings are accepted, and **anything else declines the label**.
    # That is the safe direction for a value this script did not expect: no
    # label falls back to the container name, a wrong one puts `zsh` on the
    # board with the same confidence as a real handle.
    case "$auto" in 0|off) ;; *) window="" ;; esac

    # Before the `@cc` test, not after, and that ordering is the whole point:
    # this is the record the fallback below uses, and it is needed in precisely
    # the case where the stamp is *missing* from the launcher's own pane.
    if [ -n "${TMUX_PANE:-}" ] && [ "$pane" = "$TMUX_PANE" ]; then
        self_pane="$pane"; self_window="$window"; self_session="$session"
    fi

    # An empty `@cc` is a shell pane, which is the overwhelming majority of
    # them. This is the whole test — there is no prefix to honour and no window
    # name to pattern-match, which is the point of stamping the pane.
    [ -n "$cc" ] || continue

    # Unlike a container name, `@cc` is a tmux user option and anyone can set
    # it to anything. It becomes a JSON *key*, so a value that could break the
    # file is dropped rather than escaped — a lossy map beats an unparseable
    # one, which silently disables the board for every reader.
    case "$cc" in *[\"\\]*) continue ;; esac

    # Running, or about to be. `--rm` reaps a container the moment its session
    # ends while the pane keeps its stamp, so `docker ps` is what retires a tab
    # whose work is over. The pre-run call's own container is not in that list
    # yet, which is what the argument is for.
    if [ "$cc" != "$self" ]; then
        case "
$names
" in *"
$cc
"*) ;; *) continue ;; esac
    fi
    [ "$cc" = "$self" ] && self_found=1

    add_entry "$cc" "$pane" "$window" "$session"
done <<EOF
$panes
EOF

# The stamp is what makes this launch findable, so if it did not take — a tmux
# too old for `set-option -p`, a set that failed for any other reason — the
# launcher would vanish from its own map. It still knows its pane, so fall back
# to that. Costs nothing when the stamp worked, which is every ordinary case.
if [ -n "$self" ] && [ -z "$self_found" ] && [ -n "$self_pane" ]; then
    case "$self" in *[\"\\]*) ;; *) add_entry "$self" "$self_pane" "$self_window" "$self_session" ;; esac
fi

# --- other tmux servers -------------------------------------------------------
# The query above is the complete truth about *this* tmux server and replaces
# everything it previously said. It says nothing at all about a second server,
# and pane ids are recycled per server — so those entries are carried forward
# with the socket path they were written under, exactly as before. Dropping
# them would let a board run from one server retire every tab belonging to the
# other; relabelling them as ours would credit one server's `%12` to another's.
#
# This is all that is left of the old carry-forward, and it is bounded by the
# same rule: an entry survives only while `docker ps` still lists its container.
while IFS= read -r name; do
    [ -n "$name" ] || continue
    case "
$seen
" in *"
$name
"*) continue ;; esac
    case "$name" in *[\"\\]*) continue ;; esac
    line=$(grep -m1 -F "    \"$name\": {" "$data_dir/tmux/panes.json" 2>/dev/null) || continue
    [ -n "$line" ] || continue
    # Ours and absent from the query means the pane is gone. Only another
    # server's entry is carried.
    case "$line" in *"\"server\": \"$server\""*) continue ;; esac
    entries="${entries:+$entries,
}${line%,}"
done <<EOF
$names
EOF

mkdir -p "$data_dir/tmux" 2>/dev/null || exit 0
tmp="$data_dir/tmux/.panes.json.$$"
{
    printf '{\n'
    printf '  "version": 1,\n'
    printf '  "observed_at": "%s",\n' "$now"
    printf '  "observer": "host",\n'
    printf '  "kind": "tmux",\n'
    printf '  "server": "%s",\n' "$server"
    printf '  "panes": {\n'
    [ -n "$entries" ] && printf '%s\n' "$entries"
    printf '  }\n'
    printf '}\n'
} > "$tmp" 2>/dev/null || { rm -f "$tmp" 2>/dev/null; exit 0; }

# Atomic, for the same reason the roster is: a reader in another container must
# never see a half-written file.
mv -f "$tmp" "$data_dir/tmux/panes.json" 2>/dev/null || rm -f "$tmp" 2>/dev/null

exit 0
