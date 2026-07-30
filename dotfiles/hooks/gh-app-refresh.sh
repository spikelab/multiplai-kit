#!/usr/bin/env bash
# gh-app-refresh.sh — PreToolUse(Bash) hook: renew the GitHub App token when the
# cached one has run out, before the command runs.
#
# This runs before EVERY Bash call, so the guard below forks ZERO processes:
# a handful of shell builtins (tests, reads, arithmetic comparisons) against
# $EPOCHSECONDS and the bare-integer sidecars written beside the token cache.
# Anything heavier here — pulling the ISO-8601 expiry out of the JSON, shelling
# out to a clock program — costs two forks on every single Bash invocation, and
# removing that cost is exactly why the sidecar exists. Keep it this way.
#
# It never blocks or denies a tool call: no decision is emitted on any path and
# the exit is always 0. A broken bridge degrades to "the gh call gets a 401",
# never to "Bash stopped working". Note that "exit 0 on every path" is not by
# itself enough for that promise — a renewal that HANGS never reaches the exit.
# See the mint below for the one way that happened.
#
# Nor to "every Bash call stalls": a failed renewal writes a short-lived backoff
# marker beside the cache, and the guard honours it. Without the marker, a dead
# bridge plus an expired cache re-enters the mint on every Bash call, each one
# paying the SSH connect timeout (up to 10s) inside this hook — so the tax is
# capped at one stall per minute. The marker self-expires by timestamp; a
# successful renewal removes it.
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
# Brace group, not `read ... 2>/dev/null`: bash applies redirections left to
# right, so a failing `<` on a missing sidecar is reported by the shell BEFORE
# the stderr redirect is in effect — which spammed hook-errors.log with "No such
# file or directory" on precisely the missing-cache path you debug from.
{ read -r exp < "$HOME/.cache/multiplai/gh/$GH_TOKEN_APP.json.exp"; } 2>/dev/null
case "$exp" in ''|*[!0-9]*) exp=0 ;; esac
(( exp > EPOCHSECONDS + 120 )) && exit 0
# The token needs renewing — unless a mint just failed. The marker holds the
# epoch until which retrying is pointless; while it is fresh, skip the renew
# path entirely (same seeded-read-then-validate shape as the expiry above).
fail=0
{ read -r fail < "$HOME/.cache/multiplai/gh/$GH_TOKEN_APP.json.fail"; } 2>/dev/null
case "$fail" in ''|*[!0-9]*) fail=0 ;; esac
(( fail > EPOCHSECONDS )) && exit 0

# --- renew ---------------------------------------------------------------------
set -uo pipefail
LOG="${CLAUDE_MULTIPLAI_HOME:-$HOME}/runtime/logs/hook-errors.log"
mkdir -p "${LOG%/*}" 2>/dev/null || true
CACHE_DIR="$HOME/.cache/multiplai/gh"

# An environment token would make `gh auth login --with-token` refuse; App mode
# forwards none, but a stray one must not silently block the store either.
unset GH_TOKEN GITHUB_TOKEN

# Mint into a variable, then pipe only if it produced something. Still piped and
# never on argv — argv is visible in `ps`.
#
# The emptiness check is load-bearing, not defensive: `gh auth login
# --with-token` does NOT fail on empty stdin. Measured on gh 2.96.0, it falls
# through to the interactive OAuth **device flow**, prints a one-time code and
# blocks forever on a terminal that does not exist here. Piping a failed mint
# straight in would hang this hook — and it runs before EVERY Bash call, so that
# is "Bash stopped working", the one outcome the whole design forbids. The
# minting primitive's empty-stdout-on-failure contract does not rescue the
# caller; the caller must look. `timeout` bounds the store call regardless, so
# no future change in gh's stdin handling can stall a session again.
tok=$("${CLAUDE_CONFIG_DIR:-$HOME/.claude}/hooks/gh-tok" "$GH_TOKEN_APP" 2>>"$LOG") || tok=""

if [ -n "$tok" ] && printf '%s\n' "$tok" \
     | timeout 20 gh auth login --with-token --hostname github.com >>"$LOG" 2>&1; then
    rm -f "$CACHE_DIR/$GH_TOKEN_APP.json.fail" 2>/dev/null || true
else
    printf '%(%Y-%m-%dT%H:%M:%SZ)T gh-app-refresh: renewal failed for app "%s"; the next gh call may 401 (backing off 60s)\n' \
        -1 "$GH_TOKEN_APP" >>"$LOG" 2>/dev/null || true
    # Written on the failure path only, so it costs nothing when things work.
    # mkdir because a first-ever mint failure precedes the cache dir existing.
    mkdir -p "$CACHE_DIR" 2>/dev/null || true
    printf '%s\n' "$((EPOCHSECONDS + 60))" > "$CACHE_DIR/$GH_TOKEN_APP.json.fail" 2>/dev/null || true
fi
unset tok

exit 0
