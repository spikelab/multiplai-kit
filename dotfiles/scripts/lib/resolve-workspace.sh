#!/bin/bash
# resolve-workspace.sh — shared workspace resolution for the fleet scripts.
#
# SOURCED by fleet-panes.sh and fleet-viewed.sh, never executed. Sets `ws` to
# the workspace root, or leaves it empty when nothing resolves — the caller
# decides what an empty answer costs (both exit 0: silence is their contract).
#
# Resolution order: the environment first, then the marker `setup.sh` writes at
# `$CLAUDE_CONFIG_DIR/.workspace` (the launcher sets that variable for the
# container), then the marker beside the scripts (`dotfiles/.workspace`) — the
# rung that fires on the host, where a tmux hook inherits the tmux *server's*
# pre-launcher environment. `$0` is the sourcing script's own path, so the
# marker sits one level above its directory and travels with the install.
#
# statusline.sh and fleet-watch keep deliberate subsets of this chain — see
# their comments before folding them in.
ws="${WORKSPACE:-}"
if [ -z "$ws" ] && [ -r "${CLAUDE_CONFIG_DIR:-}/.workspace" ]; then
    read -r ws < "$CLAUDE_CONFIG_DIR/.workspace"
fi
if [ -z "$ws" ] && [ -r "$(dirname "$0")/../.workspace" ]; then
    read -r ws < "$(dirname "$0")/../.workspace"
fi
