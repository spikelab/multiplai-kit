#!/bin/bash
# Claude Code statusline — reads JSON from stdin, outputs formatted status
# Shows: model | dir | git branch | context % (color-coded) | output style

input=$(cat)

# ANSI codes as real escape sequences
RST=$'\033[0m'
BOLD=$'\033[1m'
DIM=$'\033[2m'
RED=$'\033[31m'
GREEN=$'\033[32m'
YELLOW=$'\033[33m'
CYAN=$'\033[36m'
SEP="${DIM}|${RST}"

# Extract fields via jq
model=$(echo "$input" | jq -r '.model.display_name // "?"')
cwd=$(echo "$input" | jq -r '.workspace.current_dir // "?"')
style=$(echo "$input" | jq -r '.output_style.name // empty')
used=$(echo "$input" | jq -r '.context_window.used_percentage // empty')
cost=$(echo "$input" | jq -r '.cost.total_cost_usd // empty')

# Shorten path: replace $HOME with ~
short_cwd="${cwd/#$HOME/~}"
# Further shorten: keep the last two path components if long
if [ "${#short_cwd}" -gt 40 ]; then
  parent="${short_cwd%/*}"
  short_cwd=".../${parent##*/}/${short_cwd##*/}"
fi

# Git info
git_info=""
if git -C "$cwd" rev-parse --git-dir >/dev/null 2>&1; then
  branch=$(git -C "$cwd" --no-optional-locks branch --show-current 2>/dev/null)
  [ -z "$branch" ] && branch="detached"
  dirty=""
  if ! git -C "$cwd" --no-optional-locks diff --quiet 2>/dev/null || \
     ! git -C "$cwd" --no-optional-locks diff --cached --quiet 2>/dev/null; then
    dirty="*"
  fi
  git_info=" ${SEP} ${branch}${dirty}"
fi

# Context % with color coding
ctx_info=""
if [ -n "$used" ] && [ "$used" != "null" ]; then
  used_int=${used%.*}
  if [ "$used_int" -ge 80 ]; then
    ctx_color="$RED"
  elif [ "$used_int" -ge 50 ]; then
    ctx_color="$YELLOW"
  else
    ctx_color="$GREEN"
  fi
  ctx_info=" ${SEP} ${ctx_color}${used}%${RST}"
fi

# Cost (if available). Round first, then hide a zero cost — comparing the raw
# value only caught "0", not "0.00"/"0.001".
cost_info=""
if [ -n "$cost" ] && [ "$cost" != "null" ]; then
  cost_rounded=$(printf "%.2f" "$cost" 2>/dev/null || echo "0.00")
  if [ "$cost_rounded" != "0.00" ]; then
    cost_info=" ${SEP} \$${cost_rounded}"
  fi
fi

# Output style (only show if not "default")
style_info=""
if [ -n "$style" ] && [ "$style" != "null" ] && [ "$style" != "default" ]; then
  style_info=" ${SEP} ${CYAN}${style}${RST}"
fi

# Assemble
echo -n "${BOLD}${model}${RST} ${SEP} ${short_cwd}${git_info}${ctx_info}${cost_info}${style_info}"
