#!/bin/bash
# Claude Code statusline — reads JSON from stdin, outputs formatted status
# Shows: model + effort | dir | git branch | context % | 5h and 7d plan usage | prompt cache
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
# one fork instead of ten. Three details, each load-bearing:
#
#   * Every path is wrapped `(...)? // ""`. `//` alone only covers null; it does
#     NOT cover a type error, and one badly-shaped subtree aborts the whole
#     program. It also treats `false` as missing, so the two prompt-cache
#     booleans are turned into strings before `//` sees them. A payload whose `.rate_limits` is the string "unavailable" —
#     which is the shape that appears before the session's first API response —
#     made jq exit 5 and print nothing, blanking every field including
#     model and cwd (and an empty cwd then breaks the `git -C` below). `?`
#     confines the failure to the field that failed.
#   * The delimiter is the unit separator (\x1f), not a tab: tab is IFS
#     whitespace, so `read` would collapse adjacent delimiters and shift every
#     field after an empty one.
#   * The record is NUL-terminated and read with `-d ''` from a process
#     substitution. Plain `read` stops at the first newline, so a newline
#     anywhere in a value (a model name, a path) would silently empty
#     every field after it. Command substitution cannot carry the NUL, hence
#     `< <(...)`.
#
# Plan usage limits are claude.ai subscribers only, and absent until the
# session's first API response — every consumer below tolerates an empty value.
IFS=$'\x1f' read -r -d '' model cwd used effort h5_pct h5_reset d7_pct d7_reset \
  cache_seen cache_warm cache_expires cache_hit cache_misses \
  < <(printf '%s' "$input" | jq -j '[
  ((.model.display_name)? // "?"),
  ((.workspace.current_dir)? // "?"),
  ((.context_window.used_percentage)? // ""),
  ((.effort.level)? // ""),
  ((.rate_limits.five_hour.used_percentage)? // ""),
  ((.rate_limits.five_hour.resets_at)? // ""),
  ((.rate_limits.seven_day.used_percentage)? // ""),
  ((.rate_limits.seven_day.resets_at)? // ""),
  ((.prompt_cache.caching_observed | if . == null then "" else tostring end)? // ""),
  ((.prompt_cache.warm | if . == null then "" else tostring end)? // ""),
  ((.prompt_cache.expires_at)? // ""),
  ((.prompt_cache.hit_ratio * 100 | floor)? // ""),
  ((.prompt_cache.misses)? // "")
] | map(tostring) | join("\u001f") + "\u0000"')

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
# Same resolution chain as the fleet scripts (lib/resolve-workspace.sh sets
# `ws`), rather than the subset this used to keep. `$WORKSPACE` is read here so
# a missing library costs nothing the environment already answered, and an
# unresolved workspace is not an error — it just leaves the path uncollapsed.
ws="${WORKSPACE:-}"
if [ -z "$ws" ]; then
  _ws_lib="$(dirname "$0")/lib/resolve-workspace.sh"
  [ -r "$_ws_lib" ] && . "$_ws_lib"
  unset _ws_lib
fi
[ -n "$ws" ] && short_cwd="${short_cwd/#$ws/'~'}"
short_cwd="${short_cwd/#$HOME/'~'}"
# Inside a worktree, the worktree's name is the useful part: everything up to
# and including the first path component containing "worktree" is dropped and
# "wt:" marks it ("$ws/.worktrees/foo/src" -> "wt:foo/src"). The first match
# is the container, so a worktree that is itself named "fix-worktree" still
# shows. Being in the container directory itself is not a worktree.
case "$cwd" in
  *worktree*/?*)
    wt_rest="${cwd#*worktree}"
    wt_rest="${wt_rest#*/}"
    short_cwd="wt:${wt_rest%/}"
    # Further shorten: keep the worktree name and the last component if long
    if [ "${#short_cwd}" -gt 28 ] && [ "${wt_rest%/}" != "${wt_rest%%/*}" ]; then
      short_cwd="wt:${wt_rest%%/*}/.../${wt_rest##*/}"
    fi
    ;;
  *)
    # Further shorten: keep the last two path components if long
    if [ "${#short_cwd}" -gt 28 ]; then
      parent="${short_cwd%/*}"
      short_cwd=".../${parent##*/}/${short_cwd##*/}"
    fi
    ;;
esac

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

# Reasoning effort, abbreviated, set right after the model name with no
# separator (absent on models without the parameter)
effort_info=""
case "$effort" in
  low)    effort_info=" ${CYAN}lo${RST}" ;;
  medium) effort_info=" ${CYAN}med${RST}" ;;
  high)   effort_info=" ${CYAN}hi${RST}" ;;
  xhigh)  effort_info=" ${CYAN}xhi${RST}" ;;
  max)    effort_info=" ${CYAN}max${RST}" ;;
  ?*)     effort_info=" ${CYAN}${effort}${RST}" ;;
esac

# Prompt cache — e.g. "cache 91% ⟳42m ✗2". The percentage is the session's
# cache hit ratio, so unlike the other percentages a high one is good. The
# countdown runs to when the cached prefix goes cold, and "cold" replaces it
# once that has happened. "✗N" counts requests that re-processed content the
# cache already held, and only shows when N > 0. Absent until the session's
# first API response; "cache off" means no response has reported cache tokens.
cache_info=""
if [ "$cache_seen" = "false" ]; then
  cache_info=" ${SEP} ${DIM}cache off${RST}"
elif [ "$cache_seen" = "true" ]; then
  cache_info=" ${SEP} cache"
  if [ -n "$cache_hit" ]; then
    if [ "$cache_hit" -ge 80 ]; then hit_color="$GREEN"
    elif [ "$cache_hit" -ge 50 ]; then hit_color="$YELLOW"
    else hit_color="$RED"; fi
    cache_info="${cache_info} ${hit_color}${cache_hit}%${RST}"
  fi
  if [ "$cache_warm" = "true" ] && [ -n "$cache_expires" ]; then
    cache_info="${cache_info} ${DIM}⟳$(until_hm "$cache_expires")${RST}"
  else
    cache_info="${cache_info} ${YELLOW}cold${RST}"
  fi
  [ "${cache_misses:-0}" -gt 0 ] 2>/dev/null && cache_info="${cache_info} ${RED}✗${cache_misses}${RST}"
fi

# Assemble
echo -n "${BOLD}${model}${RST}${effort_info} ${SEP} ${short_cwd}${git_info}${ctx_info}${h5_info}${d7_info}${cache_info}"
