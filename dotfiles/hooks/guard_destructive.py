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


# One rm flag, short or long: `-f`, `-rf`, `--force`, `--interactive=never`.
_RM_FLAG = r"-{1,2}[a-zA-Z][\w=-]*"

# A flag that turns rm recursive: `--recursive`, or any short cluster
# carrying an `r` (`-r`, `-rf`, `-fr`, `-Rf`, ...).
_RM_RECURSIVE = r"(?:--recursive|-[a-zA-Z]*[rR][a-zA-Z]*)"

RULES = [
    _rule(
        "recursive-delete-outside-workspace",
        # rm -rf on an absolute path that is not under the workspace, /tmp, or
        # a scratchpad. Relative paths stay allowed: they resolve inside the
        # cwd, which is where the agent is supposed to be working. The /tmp
        # and /var/folders exemptions hold only while no `..` follows — a
        # traversal like /tmp/../etc leaves the exempted tree.
        r"\brm\s+"
        rf"(?:{_RM_FLAG}\s+)*"
        rf"{_RM_RECURSIVE}\s+"
        rf"(?:{_RM_FLAG}\s+)*"
        r"(/(?!(?:tmp|var/folders)/(?!\S*\.\.))\S*|~\S*|\$\{?HOME\}?\S*)",
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
        # The branch tokens use lookarounds, not \b: `main-fix` or
        # `feature/main` are ordinary branches that merely contain the word,
        # and \b would match inside them (word boundary before `-` and `/`).
        # `refs/heads/main` is the same branch fully qualified, and
        # `+<src>:main` (or a bare `+main`) is the refspec force syntax — no
        # --force flag involved, same rewrite.
        r"\bgit\s+push\b.*(?:--force(?!-with-lease)|(?:^|\s)-f(?:\s|$)).*(?<![\w./-])(?:refs/heads/)?(?:main|master)(?![\w./-])"
        r"|\bgit\s+push\b.*(?<![\w./-])(?:refs/heads/)?(?:main|master)(?![\w./-]).*(?:--force(?!-with-lease)|(?:^|\s)-f(?:\s|$))"
        r"|\bgit\s+push\b.*\s\+(?:[\w./-]+:)?(?:refs/heads/)?(?:main|master)(?![\w./-])",
        "Force-pushing a protected branch rewrites history other checkouts "
        "and PRs depend on.",
    ),
    _rule(
        "git-hook-bypass",
        # The container's git-hooks dispatcher (gitleaks secret scan) can be
        # skipped three ways; all three are the same decision. `git config
        # core.hooksPath` *query* forms carry no `-c ...=` and stay allowed,
        # as does prose that merely mentions no-verify without the flag dashes.
        r"\bgit\s+.*-c\s*core\.hooksPath="
        r"|\bgit\s+.*\s--no-verify(?![\w-])"
        r"|\bGIT_CONFIG_NOSYSTEM=\S*\s+.*\bgit\b",
        "This bypasses the git hooks that gate commits — including the "
        "pre-commit secret scan. Skipping that gate is the user's call, "
        "not yours.",
    ),
    _rule(
        "git-hard-reset-remote",
        r"\bgit\s+reset\s+--hard\s+\S*origin/(?:main|master)\b",
        "A hard reset to origin discards every uncommitted and unpushed "
        "change in this checkout with no reflog entry for the working tree.",
    ),
    _rule(
        "docker-prune",
        r"\bdocker\s+(?:system|volume|image|container)\s+prune\b|\bdocker\s+volume\s+rm\b",
        "Pruning removes volumes and images belonging to other containers, "
        "including other running multiplai sessions.",
    ),
    _rule(
        "sql-destructive",
        # Only when the segment actually invokes a SQL client. Without that
        # context the rule fired on prose — commit messages, echo'd notes,
        # heredoc-written migration files — and a guard that blocks ordinary
        # work gets disabled, and then protects nothing.
        r"\b(?:psql|mysql|sqlite3|mongosh|clickhouse-client|bq|manage\.py\s+dbshell)\b"
        r".*"
        r"(?:\b(?:DROP\s+(?:TABLE|DATABASE|SCHEMA)|TRUNCATE\s+TABLE)\b"
        r"|\bDELETE\s+FROM\s+\w+\s*(?:;|$))",  # DELETE with no WHERE
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
        # dd targets a device via of=; mkfs takes the device as a positional
        # argument (`mkfs.ext4 /dev/sda1`) — two syntaxes, two alternatives.
        r"\bdd\b[^|]*\bof=/dev/"
        r"|\bmkfs(?:\.\w+)?\b[^|]*\s/dev/",
        "Writing to a block device destroys the filesystem on it.",
    ),
]

# Commands that look destructive but are how the agent is *supposed* to clean
# up after itself. Checked per shell segment, before the rules, so a
# legitimate cleanup is never denied.
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


# Naive shell-segment split — connectors and pipes, quotes not honoured. Each
# segment is then matched in *bare* form (quotes stripped, $WORKSPACE
# expanded), so splitting inside a quoted string can only make the guard
# stricter, never looser.
_SEGMENT_SPLIT_RE = re.compile(r"&&|\|\||[;|\n]")

_QUOTES_RE = re.compile(r"[\"']")

# The recursive-rm shape, for the workspace allowance below. Built from the
# same flag pieces as the deny rule so the two cannot drift apart.
_RM_RECURSIVE_RE = re.compile(
    rf"\brm\s+(?:{_RM_FLAG}\s+)*{_RM_RECURSIVE}(?=\s)", re.IGNORECASE
)


def _segments(command: str) -> list[str]:
    return [s for s in (p.strip() for p in _SEGMENT_SPLIT_RE.split(command)) if s]


def _bare(segment: str) -> str:
    """The form the allowlist and the rules both match against.

    Quotes are stripped — `rm -rf '/etc'` is `rm -rf /etc` to the shell, and
    quoting a path (a normal idiom for paths with spaces) must not carry a
    command past a rule keyed on the unquoted form. `$WORKSPACE` is expanded
    for the same reason: the shell will expand it, so the guard must judge
    the path it expands to.
    """
    s = _QUOTES_RE.sub("", segment)
    ws = _workspace()
    if ws:
        s = s.replace("${WORKSPACE}", ws).replace("$WORKSPACE", ws)
    return s


def _is_allowlisted(segment: str) -> bool:
    """*segment* arrives in bare form (see _bare)."""
    # `..` escapes any allowance: `/tmp/../etc` is not in /tmp, and
    # `$WORKSPACE/../..` is not in the workspace. A target that traverses is
    # never allowlisted — the deny rules judge it instead.
    targets = re.findall(r"(/\S+)", segment)
    if any(".." in t for t in targets):
        return False
    if any(p.search(segment) for p in ALLOWLIST):
        return True
    # A recursive delete confined to the workspace is ordinary cleanup — but
    # never `.multiplai/` (the memory/diary/learnings corpus lives inside the
    # workspace, and this allowance must not defeat the rule protecting it).
    ws = _workspace()
    if ws and _RM_RECURSIVE_RE.search(segment):
        if targets and all(
            t.startswith(ws) and ".multiplai" not in t for t in targets
        ):
            return True
    return False


def check(command: str) -> tuple[str, str] | None:
    """Return (rule_name, explanation) when *command* must be denied.

    Evaluated per shell segment: the allowlist clears only the segment it
    matches, never the whole command. Otherwise `rm -rf /tmp/x && <anything>`
    would ride the /tmp allowance past every rule. Both the allowlist and the
    rules see the segment's bare form, so neither side is fooled by quoting.
    """
    if not command or not command.strip():
        return None
    for segment in _segments(command):
        bare = _bare(segment)
        if _is_allowlisted(bare):
            continue
        for name, pattern, why in RULES:
            if pattern.search(bare):
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
