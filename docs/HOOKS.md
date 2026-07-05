# Hooks Reference

All hooks are in `dotfiles/hooks/`. They're configured in `dotfiles/settings.json` under the `hooks` key.

## Hook Events

| Event | When | Hooks |
|-------|------|-------|
| SessionStart | Session begins | session-lifecycle.py |
| UserPromptSubmit | Every user message | context-router.py |
| PostToolUse (Write/Edit) | After file changes | validate-syntax.sh |
| PreCompact | Before context compaction | session-lifecycle.py |
| Stop | Claude stops responding | session-lifecycle.py |
| SessionEnd | Session ends | session-lifecycle.py |

## Hook Details

### session-lifecycle.py
Central hook handling four events. On SessionStart, creates diary entry, processes deferred extractions from previous sessions, checks the autodream consolidation gate, and surfaces unseen dream reports. On SessionEnd, saves deferred extraction markers and launches project state synthesis. On Stop, launches fire-and-forget learning extraction. On PreCompact, annotates the diary with a compaction marker.

### context-router.py
Runs on every user message. Loads a catalog of memory file descriptions, asks a routing model which files are relevant, then injects the full selected files as context. Also manages the nudge system (memory, skill-creation, long-session nudges).

### validate-syntax.sh
Validates YAML and JSON files after they're written/edited.

### run-hook-python
Wrapper script that routes Python hook invocations to the workspace's venv python. Falls back to system python3.

## Python Hook Dependencies

All Python hooks require these packages (installed by setup.sh):
- `claude-agent-sdk` — Agent SDK for calling Claude models
- `pyyaml` — YAML validation

## Adding Custom Hooks

1. Create your hook script in `dotfiles/hooks/`
2. Register it in `dotfiles/settings.json` under the appropriate event
3. For Python hooks, use `run-hook-python` as the interpreter:
   ```json
   "command": "bash $CLAUDE_CONFIG_DIR/hooks/run-hook-python $CLAUDE_CONFIG_DIR/hooks/my-hook.py"
   ```
