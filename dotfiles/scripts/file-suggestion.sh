#!/bin/bash
# file-suggestion.sh — Custom @ file picker for Claude Code
#
# Replaces the built-in @ picker via the fileSuggestion setting.
# Uses rg --no-ignore-vcs to walk into gitignored sub-projects,
# with a separate ignore file to exclude build artifacts and junk.
#
# API: receives JSON on stdin {"query": "src/comp"}, outputs
# newline-separated file paths to stdout (max 15).

set -euo pipefail

# Parse query from JSON stdin. This runs on every keystroke of the @ picker,
# so it stays a short pipeline rather than a jq fork — but `grep -m1` does the
# selecting, not sed. sed has no non-greedy match: a leading `.*` takes the
# LAST `"query"` in the payload, so a nested or embedded one would silently
# search for the wrong term. (The three-process form this replaces had the
# mirror-image bug — it emitted EVERY match, joining them with newlines into a
# pattern that then matched no file at all.)
query=$(grep -oE '"query"[[:space:]]*:[[:space:]]*"[^"]*"' \
        | sed -nE '1s/.*:[[:space:]]*"([^"]*)"$/\1/p' || true)

[ -z "$query" ] && exit 0

dir="${CLAUDE_PROJECT_DIR:-.}"
ignore_file="$(dirname "$0")/file-suggestion-ignore"

# Match the query as a literal substring (-F), and tolerate no matches: a
# grep with zero hits exits 1, which under `set -e` would otherwise abort the
# whole script and surface as a picker error instead of an empty result.
rg --files --no-ignore-vcs \
  --ignore-file "$ignore_file" \
  "$dir" 2>/dev/null \
  | { grep -iF "$query" || true; } \
  | head -15
