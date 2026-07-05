#!/usr/bin/env bash
# PostToolUse hook: validate syntax of written/edited files
# Fires after Write|Edit — checks JSON and YAML syntax to catch blast-radius errors
# (e.g., trailing comma in settings.json breaking all hooks)

# Child session guard — skip for SDK-spawned sessions
[ -n "${_HOOK_CHILD_SESSION:-}" ] && exit 0

set -euo pipefail

# Read hook input from stdin
INPUT=$(cat)

# Extract the file path from the hook input
# PostToolUse provides tool_input which contains the file_path
FILE_PATH=$(echo "$INPUT" | python3 -c "
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

# Emit a blocking-error JSON object safely. Never interpolate untrusted text
# into a shell string — json.dumps handles quoting/escaping of the message.
emit_error() {
    echo "$1" >&2
    python3 -c 'import json,sys; print(json.dumps({"error": sys.argv[1]}))' "$1"
}

case "$EXT" in
    json)
        # Validate JSON syntax. The file path is passed as argv, never
        # interpolated into the Python source, so a malicious path/basename
        # cannot break out of open(...) and execute code (CWE-78).
        if ! python3 -c 'import json,sys; json.load(open(sys.argv[1]))' "$FILE_PATH" 2>/dev/null; then
            ERROR=$(python3 -c '
import json, sys
try:
    json.load(open(sys.argv[1]))
except json.JSONDecodeError as e:
    print(f"JSON syntax error in {sys.argv[1]}: {e}")
' "$FILE_PATH" 2>&1)
            emit_error "$ERROR"
            exit 1
        fi
        ;;
    yaml|yml)
        # Validate YAML syntax (if pyyaml available)
        if python3 -c "import yaml" 2>/dev/null; then
            if ! python3 -c 'import yaml,sys; yaml.safe_load(open(sys.argv[1]))' "$FILE_PATH" 2>/dev/null; then
                ERROR=$(python3 -c '
import yaml, sys
try:
    yaml.safe_load(open(sys.argv[1]))
except yaml.YAMLError as e:
    print(f"YAML syntax error in {sys.argv[1]}: {e}")
' "$FILE_PATH" 2>&1)
                emit_error "$ERROR"
                exit 1
            fi
        fi
        ;;
esac

# Success — no output needed
exit 0
