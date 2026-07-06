#!/usr/bin/env bash
# PostToolUse hook: validate syntax of written/edited files
# Fires after Write|Edit — checks JSON and YAML syntax to catch blast-radius errors
# (e.g., trailing comma in settings.json breaking all hooks)

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

# Extract the file path from the hook input
# PostToolUse provides tool_input which contains the file_path
FILE_PATH=$(echo "$INPUT" | "$PY" -c "
import sys, json
try:
    data = json.load(sys.stdin)
    # Try tool_input.file_path (Write/Edit)
    ti = data.get('tool_input', {})
    print(ti.get('file_path', ti.get('filePath', '')))
except:
    print('')
" 2>/dev/null)

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

case "$EXT" in
    json)
        if ! "$PY" -c 'import json,sys; json.load(open(sys.argv[1]))' "$FILE_PATH" 2>/dev/null; then
            ERROR=$("$PY" -c '
import json, sys
try:
    json.load(open(sys.argv[1]))
except json.JSONDecodeError as e:
    print(f"JSON syntax error in {sys.argv[1]}: {e}")
' "$FILE_PATH" 2>&1)
            emit_error "$ERROR"
        fi
        ;;
    yaml|yml)
        # Validate YAML syntax (if pyyaml available)
        if "$PY" -c "import yaml" 2>/dev/null; then
            if ! "$PY" -c 'import yaml,sys; yaml.safe_load(open(sys.argv[1]))' "$FILE_PATH" 2>/dev/null; then
                ERROR=$("$PY" -c '
import yaml, sys
try:
    yaml.safe_load(open(sys.argv[1]))
except yaml.YAMLError as e:
    print(f"YAML syntax error in {sys.argv[1]}: {e}")
' "$FILE_PATH" 2>&1)
                emit_error "$ERROR"
            fi
        fi
        ;;
esac

# Success — no output needed
exit 0
