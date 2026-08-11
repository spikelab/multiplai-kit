#!/bin/bash
# PreToolUse(Bash) entry point for the destructive-command guard.
#
# `guard_destructive.py` is the guard; this wrapper exists for one reason: to
# make it impossible to *silently* lose it.
#
# Sessions run `claude --dangerously-skip-permissions`, so this hook is the one
# layer that can still say no. A PreToolUse hook that errors is reported once
# and then ignored — the tool call proceeds. That is fail-open: on 2026-08-04 a
# missing `runtime/logs/` directory (kit #26) broke the shell redirect in the
# hook command, and every Bash call in that session ran unguarded behind a
# single line of stderr nobody reads twice.
#
# So: if the guard cannot run at all, deny. The guard itself exits 0 on every
# path by contract — including when it decides to deny, which it signals on
# stdout — so a non-zero exit here means it never reached a verdict, and a
# verdict is the only thing that may let a command through.
#
# Denying every Bash call is a loud failure, deliberately. The alternative is
# an unguarded session that looks normal.

# Child session guard — skip for SDK-spawned sessions (multiplai-core sets
# _HOOK_CHILD_SESSION on every SDK child), same as validate-syntax.sh.
[ -n "${_HOOK_CHILD_SESSION:-}" ] && exit 0

set -u

CONFIG_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"

bash "$CONFIG_DIR/hooks/run-hook-python" "$CONFIG_DIR/hooks/guard_destructive.py"
status=$?

[ "$status" -eq 0 ] && exit 0

# JSON assembled with printf, not a heredoc: the reason string carries `\n`
# escapes and `$`-prefixed paths that must reach the agent verbatim.
printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"%s"}}\n' \
  "The multiplai destructive-command guard could not run (exit $status), so no Bash command can be checked. This session runs with permissions bypassed, and this guard is the only layer that can refuse an unrecoverable command, so Bash is denied until it works.\\n\\nTell the user, and read \$CLAUDE_MULTIPLAI_HOME/runtime/logs/hook-errors.log for the cause — usually no Python reachable from \$CLAUDE_CONFIG_DIR/hooks/run-hook-python, a missing guard_destructive.py, or the guard itself crashed (see \$CLAUDE_MULTIPLAI_HOME/runtime/logs/guard-destructive.log). Do not work around this by disabling the hook."
exit 0
