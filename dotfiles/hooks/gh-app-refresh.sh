#!/usr/bin/env bash
# gh-app-refresh.sh — PreToolUse(Bash) hook: renew the GitHub App token when the
# cached one has run out, before the command runs.
#
# This runs before EVERY Bash call, so the guard below forks ZERO processes:
# three shell builtins (a test, a read, an arithmetic comparison) against
# $EPOCHSECONDS and the bare-integer sidecar written beside the token cache.
# Anything heavier here — pulling the ISO-8601 expiry out of the JSON, shelling
# out to a clock program — costs two forks on every single Bash invocation, and
# removing that cost is exactly why the sidecar exists. Keep it this way.
#
# It never blocks or denies a tool call: no decision is emitted on any path and
# the exit is always 0. A broken bridge degrades to "the gh call gets a 401",
# never to "Bash stopped working".
#
# Renewal is decided at the moment of use, not on a timer: a session can sit idle
# for hours, so any clock-driven scheme misses precisely that case. Here
# "ran out seven hours ago" and "runs out in four minutes" are the same branch.
#
# A missing, unreadable or non-numeric sidecar lands in the renew branch — an
# unparseable cache is never treated as valid.
#
# `exp` is seeded before the read rather than after it with `|| exp=0`: `read`
# returns non-zero at EOF-without-newline, so the `||` form threw away a
# perfectly good expiry from a sidecar that happened to lack its final newline
# and re-minted on every Bash call. Seeding first covers the missing-file case
# (the redirect fails, `read` never runs, `exp` stays 0) without that false
# negative.

[ -n "${GH_TOKEN_APP:-}" ] || exit 0
exp=0
read -r exp < "$HOME/.cache/multiplai/gh/$GH_TOKEN_APP.json.exp" 2>/dev/null
case "$exp" in ''|*[!0-9]*) exp=0 ;; esac
(( exp > EPOCHSECONDS + 120 )) && exit 0

# --- renew ---------------------------------------------------------------------
set -uo pipefail
LOG="${CLAUDE_MULTIPLAI_HOME:-$HOME}/runtime/logs/hook-errors.log"
mkdir -p "${LOG%/*}" 2>/dev/null || true

# An environment token would make `gh auth login --with-token` refuse; App mode
# forwards none, but a stray one must not silently block the store either.
unset GH_TOKEN GITHUB_TOKEN

# Piped, never on argv — argv is visible in `ps`. The minting primitive prints
# nothing on stdout when it fails, so a failure aborts the store rather than
# writing a truncated credential.
if ! "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/hooks/gh-tok" "$GH_TOKEN_APP" 2>>"$LOG" \
     | gh auth login --with-token --hostname github.com >>"$LOG" 2>&1; then
    printf '%(%Y-%m-%dT%H:%M:%SZ)T gh-app-refresh: renewal failed for app "%s"; the next gh call may 401\n' \
        -1 "$GH_TOKEN_APP" >>"$LOG" 2>/dev/null || true
fi

exit 0
