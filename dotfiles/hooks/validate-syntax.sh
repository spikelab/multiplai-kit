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
FILE_PATH=$(echo "$INPUT" | "$PY" -c "
import sys, json
try:
    data = json.load(sys.stdin)
    ti = data.get('tool_input', {})
    print(ti.get('file_path', ti.get('filePath', ti.get('notebook_path', ''))))
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

# Each format is parsed exactly once: the probe prints the diagnosis to stdout
# and exits non-zero on failure. The `|| true` is load-bearing under `set -e` —
# without it, a probe exiting non-zero kills the ERROR=$(...) assignment before
# emit_error runs, which is precisely the silently-inert failure this hook was
# rewritten to fix. The bare `except Exception` matters for the same reason: a
# non-UTF-8 file raises UnicodeDecodeError, not JSONDecodeError, and used to
# exit 1 with no message at all.
case "$EXT" in
    json|ipynb)
        ERROR=$("$PY" -c '
import json, sys
try:
    with open(sys.argv[1], encoding="utf-8") as fh:
        json.load(fh)
except json.JSONDecodeError as e:
    print(f"JSON syntax error in {sys.argv[1]}: {e}")
    sys.exit(1)
except Exception as e:
    print(f"Could not validate {sys.argv[1]} as JSON: {e}")
    sys.exit(1)
' "$FILE_PATH" 2>&1) || true
        if [ -n "$ERROR" ]; then
            emit_error "$ERROR"
        fi
        ;;
    yaml|yml)
        # Validate YAML syntax (if pyyaml available)
        if "$PY" -c "import yaml" 2>/dev/null; then
            ERROR=$("$PY" -c '
import sys, yaml
try:
    with open(sys.argv[1], encoding="utf-8") as fh:
        yaml.safe_load(fh)
except yaml.YAMLError as e:
    print(f"YAML syntax error in {sys.argv[1]}: {e}")
    sys.exit(1)
except Exception as e:
    print(f"Could not validate {sys.argv[1]} as YAML: {e}")
    sys.exit(1)
' "$FILE_PATH" 2>&1) || true
            if [ -n "$ERROR" ]; then
                emit_error "$ERROR"
            fi
        fi
        ;;
esac

# Success — no output needed
exit 0
