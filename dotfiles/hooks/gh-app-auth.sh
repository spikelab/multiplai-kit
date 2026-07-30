#!/usr/bin/env bash
# gh-app-auth.sh — SessionStart hook: put a GitHub App installation token into
# gh's own credential store, so `gh` is authenticated from the first command.
#
# Inert unless the session was launched in App mode (GH_TOKEN_APP set by
# claude.sh). PAT-mode users and anyone running the marketplace plugins alone
# pay one test and see no behaviour change — hence the guard on line one.
#
# Why gh's credential store and not an environment variable: the Bash tool starts
# a fresh non-interactive shell per call, so an `export` in one call is gone by
# the next (measured 2026-07-30), and ~/.bashrc is not sourced either. `gh auth
# login --with-token` writes hosts.yml — a FILE — which every later call reads.
# It also validates the token against the API before storing, so a broken mint
# cannot leave a plausible-looking credential behind.
#
# The token is piped, never passed on argv: argv is visible in `ps`.
#
# `gh auth setup-git` (registered AFTER this hook in settings.json) makes
# `gh auth git-credential` git's credential helper, which is what lets
# `git clone/fetch/push` over https work off the same stored token with no token
# in the URL and no bespoke helper.

[ -n "${GH_TOKEN_APP:-}" ] || exit 0

set -uo pipefail

LOG="${CLAUDE_MULTIPLAI_HOME:-$HOME}/runtime/logs/hook-errors.log"
mkdir -p "$(dirname "$LOG")" 2>/dev/null || true

# GH_TOKEN in the environment makes `gh auth login --with-token` refuse outright
# ("the value of the GH_TOKEN environment variable is being used"). claude.sh
# never forwards one in App mode, but unset it here too so a stray GITHUB_TOKEN
# from somewhere else cannot silently block the store. Local to this hook.
unset GH_TOKEN GITHUB_TOKEN

if ! "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/hooks/gh-tok" "$GH_TOKEN_APP" 2>>"$LOG" \
     | gh auth login --with-token --hostname github.com >>"$LOG" 2>&1; then
    printf '%(%Y-%m-%dT%H:%M:%SZ)T gh-app-auth: mint/store failed for app "%s"; gh will be unauthenticated\n' \
        -1 "$GH_TOKEN_APP" >>"$LOG" 2>/dev/null || true
fi

# A failed mint must never block session start.
exit 0
