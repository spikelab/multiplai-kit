#!/bin/bash
# Claude Code statusline — reads JSON from stdin, outputs formatted status
# Shows: model + effort | dir | git branch | context % | 5h and 7d plan usage | output style
#
# Timezone: reset clock-times render in $STATUSLINE_TZ, falling back to
# $CLAUDE_CONFIG_DIR/.timezone, then the system zone. Containers run UTC, so
# without one of those a weekly reset reads in UTC rather than local time.
# Debugging: set STATUSLINE_DEBUG_DUMP=/path to capture the raw payload.

input=$(cat)

[ -n "$STATUSLINE_DEBUG_DUMP" ] && printf '%s' "$input" > "$STATUSLINE_DEBUG_DUMP"

tz="${STATUSLINE_TZ:-}"
if [ -z "$tz" ] && [ -r "${CLAUDE_CONFIG_DIR:-}/.timezone" ]; then
  read -r tz < "$CLAUDE_CONFIG_DIR/.timezone"
fi
[ -n "$tz" ] && export TZ="$tz"

# ANSI codes as real escape sequences
RST=$'\033[0m'
BOLD=$'\033[1m'
DIM=$'\033[2m'
RED=$'\033[31m'
GREEN=$'\033[32m'
YELLOW=$'\033[33m'
CYAN=$'\033[36m'
SEP="${DIM}|${RST}"

# Extract all fields in one jq pass — this runs on every statusline refresh, so
# one fork instead of ten. `// ""` (not `// empty`) keeps absent fields as empty
# strings, and the delimiter is the unit separator (\x1f) rather than a tab:
# tab is IFS whitespace, so `read` would collapse adjacent delimiters and shift
# every field after an empty one. Plan usage limits are claude.ai subscribers
# only, and absent until the session's first API response — every consumer
# below has to tolerate an empty value.
IFS=$'\x1f' read -r model cwd style used effort h5_pct h5_reset d7_pct d7_reset <<< "$(printf '%s' "$input" | jq -r '[
  (.model.display_name // "?"),
  (.workspace.current_dir // "?"),
  (.output_style.name // ""),
  (.context_window.used_percentage // ""),
  (.effort.level // ""),
  (.rate_limits.five_hour.used_percentage // ""),
  (.rate_limits.five_hour.resets_at // ""),
  (.rate_limits.seven_day.used_percentage // ""),
  (.rate_limits.seven_day.resets_at // "")
] | map(tostring) | join("\u001f")')"

# Shorten the model name: "Opus 5 (1M context)" -> "Opus 5 1M". Width is the real
# budget here — anything past the terminal's last column is silently truncated,
# and the usage segments are at the far right.
model="${model/ (1M context)/ 1M}"
model="${model/ (/ }"; model="${model/)/}"

# Shorten the path. $HOME is the container's home, not the host's, so the
# workspace root needs collapsing too — otherwise an absolute host path eats
# ~30 columns and pushes the usage segments off a narrow terminal.
# NB: the replacement is quoted because bash tilde-expands a bare `~` there,
# which silently turns "~" straight back into "$HOME".
short_cwd="$cwd"
ws="${WORKSPACE:-}"
if [ -z "$ws" ] && [ -r "${CLAUDE_CONFIG_DIR:-}/.workspace" ]; then
  read -r ws < "$CLAUDE_CONFIG_DIR/.workspace"
fi
[ -n "$ws" ] && short_cwd="${short_cwd/#$ws/'~'}"
short_cwd="${short_cwd/#$HOME/'~'}"
# Further shorten: keep the last two path components if long
if [ "${#short_cwd}" -gt 28 ]; then
  parent="${short_cwd%/*}"
  short_cwd=".../${parent##*/}/${short_cwd##*/}"
fi

# Git info. `branch --show-current` itself fails outside a repo (exit 128), so
# no separate rev-parse probe is needed; success with empty output is detached.
git_info=""
if branch=$(git -C "$cwd" --no-optional-locks branch --show-current 2>/dev/null); then
  [ -z "$branch" ] && branch="detached"
  dirty=""
  if ! git -C "$cwd" --no-optional-locks diff --quiet 2>/dev/null || \
     ! git -C "$cwd" --no-optional-locks diff --cached --quiet 2>/dev/null; then
    dirty="*"
  fi
  git_info=" ${SEP} ${branch}${dirty}"
fi

# Green/yellow/red at 50/80% — used for context and for both usage windows
pct_color() {
  local p=${1%.*}
  if [ "$p" -ge 80 ]; then echo "$RED"
  elif [ "$p" -ge 50 ]; then echo "$YELLOW"
  else echo "$GREEN"; fi
}

# "1h36m" / "12m" until the given epoch second
until_hm() {
  local secs=$(( $1 - ${EPOCHSECONDS:-$(date +%s)} ))
  [ "$secs" -lt 0 ] && secs=0
  local h=$(( secs / 3600 )) m=$(( (secs % 3600) / 60 ))
  if [ "$h" -gt 0 ]; then echo "${h}h${m}m"; else echo "${m}m"; fi
}

# Context %
ctx_info=""
if [ -n "$used" ] && [ "$used" != "null" ]; then
  ctx_info=" ${SEP} $(pct_color "$used")${used}%${RST}"
fi

# Session (5h) usage — e.g. "5h 70% ⟳1h36m". Relative, because what matters is
# how long until it clears.
h5_info=""
if [ -n "$h5_pct" ]; then
  h5_int=${h5_pct%.*}
  h5_info=" ${SEP} 5h $(pct_color "$h5_int")${h5_int}%${RST}"
  [ -n "$h5_reset" ] && h5_info="${h5_info} ${DIM}⟳$(until_hm "$h5_reset")${RST}"
fi

# Weekly (7d, all models) usage — e.g. "7d 52% ⟳Mon 06:00". Absolute, because
# days-from-now is harder to act on than a weekday.
d7_info=""
if [ -n "$d7_pct" ]; then
  d7_int=${d7_pct%.*}
  d7_info=" ${SEP} 7d $(pct_color "$d7_int")${d7_int}%${RST}"
  if [ -n "$d7_reset" ]; then
    d7_when=$(date -d "@$d7_reset" '+%a %H:%M' 2>/dev/null || date -r "$d7_reset" '+%a %H:%M' 2>/dev/null)
    [ -n "$d7_when" ] && d7_info="${d7_info} ${DIM}⟳${d7_when}${RST}"
  fi
fi

# Reasoning effort, abbreviated (absent on models without the parameter)
effort_info=""
case "$effort" in
  low)    effort_info=" ${SEP} ${CYAN}lo${RST}" ;;
  medium) effort_info=" ${SEP} ${CYAN}med${RST}" ;;
  high)   effort_info=" ${SEP} ${CYAN}hi${RST}" ;;
  xhigh)  effort_info=" ${SEP} ${CYAN}xhi${RST}" ;;
  max)    effort_info=" ${SEP} ${CYAN}max${RST}" ;;
  ?*)     effort_info=" ${SEP} ${CYAN}${effort}${RST}" ;;
esac

# Output style (only show if not "default")
style_info=""
if [ -n "$style" ] && [ "$style" != "null" ] && [ "$style" != "default" ]; then
  style_info=" ${SEP} ${CYAN}${style}${RST}"
fi

# Assemble
echo -n "${BOLD}${model}${RST}${effort_info} ${SEP} ${short_cwd}${git_info}${ctx_info}${h5_info}${d7_info}${style_info}"
