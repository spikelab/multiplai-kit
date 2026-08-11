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
# This hook also runs bare on a Mac (no container): /bin/bash there is 3.2 — no
# $EPOCHSECONDS, no printf '%(...)T' — and macOS ships no GNU coreutils, so no
# `timeout`. Every construct below works on both. Keep it that way; the tests
# pin the specific offenders.
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

# bash-5 builtin clock where it exists; on a bare Mac (/bin/bash 3.2) this
# costs one `date` fork — off the hot path, so that is fine here.
now=${EPOCHSECONDS:-$(date +%s)}

# SessionStart also fires on `resume` and after a compaction, and the token
# minted at the real session start is usually still live then. Same freshness
# check as gh-app-refresh (seeded read, unparseable counts as stale): while the
# sidecar says the cached token comfortably outlives the skew window, there is
# nothing to do — no mint, no backoff write, no `gh` fork. A missing or stale
# sidecar falls through to the mint exactly as before.
exp=0
{ read -r exp < "$CACHE_DIR/$GH_TOKEN_APP.json.exp"; } 2>/dev/null
case "$exp" in ''|*[!0-9]*) exp=0 ;; esac
(( exp > now + 120 )) && exit 0

# Mint+store — backoff marker first, mint via gh-tok, emptiness check, bounded
# store — is the block shared with gh-app-refresh.sh; all the reasoning
# (device-flow hang, kill-mid-mint, bash-3.2) lives in gh-store-token.
_GH_STORE_TAG="gh-app-auth"
_GH_STORE_FAIL_HINT="gh will be unauthenticated"
. "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/hooks/gh-store-token"

# A failed mint must never block session start.
exit 0
