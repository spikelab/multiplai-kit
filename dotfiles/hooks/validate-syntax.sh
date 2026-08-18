#!/usr/bin/env bash
# PostToolUse hook: validate syntax of written/edited files
# Fires after Write|Edit|NotebookEdit — checks JSON and YAML syntax to catch
# blast-radius errors (e.g., trailing comma in settings.json breaking all hooks)

# Child session guard — skip for SDK-spawned sessions
[ -n "${_HOOK_CHILD_SESSION:-}" ] && exit 0

set -euo pipefail

# Resolve Python via the kit venv (where pyyaml is installed by setup.sh),
# falling back to system python3 — same resolution as run-hook-python.
# System python3 typically lacks pyyaml, so without this the YAML branch
# below would silently skip (the `import yaml` guard fails).
CONFIG_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
MULTIPLAI_HOME="${CLAUDE_MULTIPLAI_HOME:-$(dirname "$CONFIG_DIR")}"
VENV_PYTHON="$MULTIPLAI_HOME/.venv/bin/python"
if [ -x "$VENV_PYTHON" ]; then
    PY="$VENV_PYTHON"
else
    PY="python3"
fi

# Read hook input from stdin
INPUT=$(cat)

# Extract the file path from the hook input.
# Write/Edit carry tool_input.file_path; NotebookEdit carries notebook_path.
# jq when available (always, in the container image): this hook fires on every
# Write/Edit, and most edits are files the case below never validates — a full
# Python startup just to extract the path was the hook's dominant cost. The
# Python fallback covers a bare Mac, where macOS ships no jq.
if command -v jq >/dev/null 2>&1; then
    FILE_PATH=$(printf '%s' "$INPUT" | jq -r '.tool_input | (.file_path // .filePath // .notebook_path // "")' 2>/dev/null) || FILE_PATH=""
else
    FILE_PATH=$(echo "$INPUT" | "$PY" -c "
import sys, json
try:
    data = json.load(sys.stdin)
    ti = data.get('tool_input', {})
    print(ti.get('file_path', ti.get('filePath', ti.get('notebook_path', ''))))
except:
    print('')
" 2>/dev/null)
fi

if [ -z "$FILE_PATH" ] || [ ! -f "$FILE_PATH" ]; then
    exit 0
fi

# Get file extension
EXT="${FILE_PATH##*.}"

# Surface a validation failure to Claude. PostToolUse feedback reaches the
# model via exit code 2 (stderr is fed back) — a plain stdout JSON `{"error"}`
# object is ignored, so the old exit-1-with-stdout path was silently inert.
# The path is passed as argv, never interpolated into the shell/Python source,
# so a malicious path/basename cannot break out and execute code (CWE-78).
emit_error() {
    echo "$1" >&2
    exit 2
}

# Map the extension to a format; anything else needs no Python at all.
case "$EXT" in
    json|ipynb) FMT=JSON ;;
    yaml|yml)   FMT=YAML ;;
    *)          exit 0 ;;
esac

# The format is parsed exactly once, by one probe shared between JSON and YAML:
# it prints the diagnosis to stdout and exits non-zero on failure. A missing
# pyyaml exits 0 silently (SystemExit is not an Exception), preserving the old
# skip-if-unavailable behavior without a second interpreter startup for the
# probe. The `|| true` is load-bearing under `set -e` — without it, a probe
# exiting non-zero kills the ERROR=$(...) assignment before emit_error runs,
# which is precisely the silently-inert failure this hook was rewritten to fix.
# The bare `except Exception` matters for the same reason: a non-UTF-8 file
# raises UnicodeDecodeError, not JSONDecodeError, and used to exit 1 with no
# message at all.
ERROR=$("$PY" -c '
import sys
fmt, path = sys.argv[1], sys.argv[2]
if fmt == "JSON":
    import json
    parse, syntax_err = json.load, json.JSONDecodeError
else:
    try:
        import yaml
    except ImportError:
        sys.exit(0)  # pyyaml unavailable — skip validation
    parse, syntax_err = yaml.safe_load, yaml.YAMLError
try:
    with open(path, encoding="utf-8") as fh:
        parse(fh)
except syntax_err as e:
    print(f"{fmt} syntax error in {path}: {e}")
    sys.exit(1)
except Exception as e:
    print(f"Could not validate {path} as {fmt}: {e}")
    sys.exit(1)
' "$FMT" "$FILE_PATH" 2>&1) || true
if [ -n "$ERROR" ]; then
    emit_error "$ERROR"
fi

# Success — no output needed
exit 0
