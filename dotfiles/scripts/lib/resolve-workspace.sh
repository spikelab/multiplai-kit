#!/bin/bash
# resolve-workspace.sh — shared workspace resolution for the fleet scripts and
# the statusline.
#
# SOURCED, never executed. Sets `ws` to the workspace root, or leaves it empty
# when nothing resolves — the caller decides what an empty answer costs
# (fleet-panes and fleet-viewed exit 0 in silence, fleet-watch says so and
# exits 1, the statusline renders an uncollapsed path).
#
# Callers read `$WORKSPACE` themselves and source this only when it is empty,
# so a partial install cannot cost them an answer the environment already had.
#
# Resolution order, after the environment:
#
#   1. `$CLAUDE_CONFIG_DIR/.workspace` — the marker `setup.sh` writes where the
#      launcher points that variable, i.e. inside the container.
#   2. `dotfiles/.workspace` — the same marker beside the installed scripts.
#      This is the rung that fires on the host, where a tmux hook inherits the
#      tmux *server's* pre-launcher environment and has neither variable.
#
# The second marker is located from THIS FILE (`${BASH_SOURCE[0]}`), not from
# the caller's `$0`. Resolving it against the caller made the path depend on
# how deep in the tree the caller happened to sit: a future caller one level
# further down would silently read a marker that does not exist, and — since
# an empty `ws` is a normal answer here — would report nothing rather than
# fail.
ws="${WORKSPACE:-}"
if [ -z "$ws" ] && [ -r "${CLAUDE_CONFIG_DIR:-}/.workspace" ]; then
    read -r ws < "$CLAUDE_CONFIG_DIR/.workspace"
fi
if [ -z "$ws" ]; then
    _rw_marker="${BASH_SOURCE[0]%/*}/../../.workspace"
    [ -r "$_rw_marker" ] && read -r ws < "$_rw_marker"
    unset _rw_marker
fi
