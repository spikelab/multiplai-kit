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

# Parse query from JSON stdin
query=$(cat | grep -o '"query"[[:space:]]*:[[:space:]]*"[^"]*"' | sed 's/.*"query"[[:space:]]*:[[:space:]]*"//;s/"$//')

[ -z "$query" ] && exit 0

dir="${CLAUDE_PROJECT_DIR:-.}"
ignore_file="$(dirname "$0")/file-suggestion-ignore"

rg --files --no-ignore-vcs \
  ${ignore_file:+--ignore-file "$ignore_file"} \
  "$dir" 2>/dev/null \
  | grep -i "$query" \
  | head -15
