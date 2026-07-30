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
# The token is piped, never passed on argv: argv is visible in `ps`. But it is
# minted into a variable FIRST and only piped once it is non-empty — see the
# comment on the mint below. Never pipe a possibly-failed mint straight into
# `gh auth login`.
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

CACHE_DIR="$HOME/.cache/multiplai/gh"

# Mint into a variable and only reach for `gh` once there is something to store.
#
# `gh auth login --with-token` does NOT fail on empty stdin. Measured on gh
# 2.96.0: it falls through to the interactive OAuth **device flow**, prints a
# one-time code, and blocks forever waiting on a terminal no hook has. So the
# obvious `gh-tok | gh auth login --with-token` pipeline turns every failed mint
# into a HUNG SessionStart rather than a degraded one — `gh-tok`'s
# empty-stdout-on-failure contract does not save the caller, the caller has to
# check for itself. (2026-07-30: a wrong `org` in the host App profile made
# every mint fail, and no session would start at all.)
#
# `timeout` is the belt-and-braces behind the emptiness check: no future change
# in how `gh` handles its stdin can stall a session again. It is generous
# because the store call talks to the API to validate the token before writing.
tok=$("${CLAUDE_CONFIG_DIR:-$HOME/.claude}/hooks/gh-tok" "$GH_TOKEN_APP" 2>>"$LOG") || tok=""

if [ -n "$tok" ] && printf '%s\n' "$tok" \
     | timeout 20 gh auth login --with-token --hostname github.com >>"$LOG" 2>&1; then
    rm -f "$CACHE_DIR/$GH_TOKEN_APP.json.fail" 2>/dev/null || true
else
    printf '%(%Y-%m-%dT%H:%M:%SZ)T gh-app-auth: mint/store failed for app "%s"; gh will be unauthenticated\n' \
        -1 "$GH_TOKEN_APP" >>"$LOG" 2>/dev/null || true
    # This failure just proved the mint path dead; write the same backoff marker
    # the refresh hook honours, so the FIRST Bash call doesn't pay the SSH
    # connect-timeout stall a second time (see gh-app-refresh.sh).
    mkdir -p "$CACHE_DIR" 2>/dev/null || true
    printf '%s\n' "$((EPOCHSECONDS + 60))" > "$CACHE_DIR/$GH_TOKEN_APP.json.fail" 2>/dev/null || true
fi
unset tok

# A failed mint must never block session start.
exit 0
