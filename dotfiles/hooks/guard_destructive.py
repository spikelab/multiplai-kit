#!/usr/bin/env python3
"""PreToolUse guard — deny a curated set of unrecoverable commands.

Every multiplai session runs `claude --dangerously-skip-permissions`, so the
tool allow-list in `settings.json` is decoration: nothing prompts, nothing
blocks. The container is the sandbox, and inside it the agent can do anything
the user can. That is the intended trade — but a handful of operations are
*unrecoverable* (they destroy the host mount, rewrite shared history, or drop
a database), and for those "the agent was confidently wrong once" is too high
a price for the convenience.

Hooks still run in bypass mode, which makes PreToolUse the one layer that can
still say no. This guard is deliberately small: it denies commands that
destroy state which cannot be reconstructed, and gets out of the way for
everything else. It is not a sandbox and does not try to be — a determined
prompt-injection can rephrase around any pattern list. It stops the confident
mistake, not the adversary.

Contract (Claude Code PreToolUse):
  stdin  — JSON with `tool_name` and `tool_input`
  stdout — JSON `{"hookSpecificOutput": {"permissionDecision": "deny", ...}}`
  exit 0 always; a guard that crashes must not wedge the session.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

# --------------------------------------------------------------------------- #
# What counts as unrecoverable
# --------------------------------------------------------------------------- #
#
# Each rule is (name, compiled pattern, explanation shown to the agent). The
# explanation matters as much as the block: the agent is told to ask the user,
# which turns a denied call into a conversation instead of a retry loop.

def _rule(name: str, pattern: str, why: str) -> tuple[str, re.Pattern, str]:
    return name, re.compile(pattern, re.IGNORECASE), why


RULES = [
    _rule(
        "recursive-delete-outside-workspace",
        # rm -rf on an absolute path that is not under the workspace, /tmp, or
        # a scratchpad. Relative paths stay allowed: they resolve inside the
        # cwd, which is where the agent is supposed to be working.
        r"\brm\s+(?:-[a-zA-Z]*\s+)*-?[a-zA-Z]*[rR][a-zA-Z]*[fF]?[a-zA-Z]*\s+(?:-[a-zA-Z]+\s+)*(/(?!tmp/|var/folders/)\S*|~\S*|\$HOME\S*)",
        "Recursive delete outside the workspace destroys host state that is "
        "not in git and cannot be restored.",
    ),
    _rule(
        "delete-multiplai-state",
        r"\brm\s+.*\.multiplai(?:/|\b)",
        "`.multiplai/` holds the memory, diary and learnings corpus — the "
        "accumulated context of every prior session.",
    ),
    _rule(
        "force-push-protected",
        r"\bgit\s+push\b.*(?:--force(?!-with-lease)|(?:^|\s)-f(?:\s|$)).*\b(?:main|master)\b"
        r"|\bgit\s+push\b.*\b(?:main|master)\b.*(?:--force(?!-with-lease)|(?:^|\s)-f(?:\s|$))",
        "Force-pushing a protected branch rewrites history other checkouts "
        "and PRs depend on.",
    ),
    _rule(
        "git-hard-reset-remote",
        r"\bgit\s+reset\s+--hard\s+\S*origin/(?:main|master)\b",
        "A hard reset to origin discards every uncommitted and unpushed "
        "change in this checkout with no reflog entry for the working tree.",
    ),
    _rule(
        "docker-prune",
        r"\bdocker\s+(?:system|volume|image)\s+prune\b|\bdocker\s+volume\s+rm\b",
        "Pruning removes volumes and images belonging to other containers, "
        "including other running multiplai sessions.",
    ),
    _rule(
        "sql-destructive",
        r"\b(?:DROP\s+(?:TABLE|DATABASE|SCHEMA)|TRUNCATE\s+TABLE)\b"
        r"|\bDELETE\s+FROM\s+\w+\s*(?:;|$)",  # DELETE with no WHERE
        "Dropping or truncating a table — or a DELETE with no WHERE clause — "
        "is not recoverable without a backup.",
    ),
    _rule(
        "gh-mass-delete",
        r"\bgh\s+(?:repo|release)\s+delete\b",
        "Deleting a repo or release on GitHub affects state shared with other "
        "people and cannot be undone from here.",
    ),
    _rule(
        "history-rewrite-published",
        r"\bgit\s+filter-branch\b|\bgit\s+filter-repo\b",
        "Rewriting published history invalidates every existing clone.",
    ),
    _rule(
        "disk-overwrite",
        r"\b(?:mkfs(?:\.\w+)?|dd)\b[^|]*\bof=/dev/",
        "Writing to a block device destroys the filesystem on it.",
    ),
]

# Commands that look destructive but are how the agent is *supposed* to clean
# up after itself. Checked first so a legitimate cleanup is never denied.
ALLOWLIST = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\brm\s+-rf?\s+/tmp/\S+",
        r"\bgit\s+worktree\s+remove\b",
        r"\bgit\s+push\s+--force-with-lease\b",
        r"\bdocker\s+(?:rm|stop)\s+(?!-)",  # a named container, not a prune
    )
]

DENY_TEMPLATE = (
    "Blocked by the multiplai destructive-command guard ({name}).\n\n"
    "{why}\n\n"
    "This is unrecoverable, so it is the user's call, not yours. Tell them "
    "what you were about to run and why, and ask them to run it themselves "
    "or to confirm explicitly. Do not rephrase the command to get around "
    "this guard."
)


def _workspace() -> str:
    return os.environ.get("WORKSPACE", "")


def _is_allowlisted(command: str) -> bool:
    if any(p.search(command) for p in ALLOWLIST):
        return True
    # A recursive delete confined to the workspace is ordinary cleanup.
    ws = _workspace()
    if ws and re.search(r"\brm\s+-[a-zA-Z]*r", command, re.IGNORECASE):
        targets = re.findall(r"(/\S+)", command)
        if targets and all(t.startswith(ws) for t in targets):
            return True
    return False


def check(command: str) -> tuple[str, str] | None:
    """Return (rule_name, explanation) when *command* must be denied."""
    if not command or not command.strip():
        return None
    if _is_allowlisted(command):
        return None
    for name, pattern, why in RULES:
        if pattern.search(command):
            return name, why
    return None


def _deny(name: str, why: str) -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": DENY_TEMPLATE.format(name=name, why=why),
        }
    }


def _log(message: str) -> None:
    """Best-effort audit line. A guard that raises on a full disk is worse
    than a guard that stays quiet."""
    home = os.environ.get("CLAUDE_MULTIPLAI_HOME")
    if not home:
        return
    try:
        path = Path(home) / "runtime" / "logs" / "guard-destructive.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as fh:
            fh.write(message + "\n")
    except OSError:
        pass


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # malformed input is not this hook's problem

    if payload.get("tool_name") != "Bash":
        return 0

    command = (payload.get("tool_input") or {}).get("command", "")
    verdict = check(command)
    if verdict is None:
        return 0

    name, why = verdict
    _log(f"DENIED [{name}] {command[:400]}")
    print(json.dumps(_deny(name, why)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
