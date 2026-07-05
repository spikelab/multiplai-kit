# Hook Writing Patterns

Reference doc for writing Claude Code hooks (UserPromptSubmit, PostToolUse, Stop, SessionStart, SessionEnd).

## Architecture

Hooks are shell commands executed by Claude Code at specific lifecycle events. They receive JSON on stdin and must output JSON to stdout.

### Hook Types and Their Input

| Event | Input Fields | Output Expected |
|-------|-------------|----------------|
| UserPromptSubmit | `prompt`, `session_id`, `transcript_path` | `hookSpecificOutput.additionalContext` or `{}` |
| PostToolUse | `tool_name`, `tool_input`, `tool_output` | `{}` or error |
| Stop | `stop_hook_active`, `transcript_path`, `session_id` | Blocking message or `{}` |
| SessionStart | `session_id`, `transcript_path` | `hookSpecificOutput.additionalContext` or `{}` |
| SessionEnd | `session_id`, `transcript_path` | `{}` |

## Common Pitfalls

### stdout is the protocol channel
- Anything printed to stdout becomes the hook's response to Claude Code
- Debug output MUST go to stderr (`echo "debug" >&2`) or a log file
- A stray `echo` or `print()` in a hook can break the JSON response and crash all hooks

### Environment isolation
- Hooks run as subprocesses — they do NOT inherit the parent terminal's environment
- `$TMUX`, `$TERM_PROGRAM`, custom env vars from `.bashrc`/`.zshrc` are NOT available
- If you need env vars, set them explicitly in the hook or read from a config file
- `$HOME` and `$PATH` are generally available but verify for your specific setup

### JSON handling
- A trailing comma in JSON (`{"key": "value",}`) is INVALID and will break parsing
- Always validate JSON output before returning it — use `python -c "import json; json.loads(...)"` or `jq .`
- When building JSON in bash, use `jq` or `python` — don't hand-construct it with string concatenation

### Multi-phase hooks (Stop hook pattern)
- The Stop hook blocks Claude's response — the blocking message appears as a "stop hook feedback" system message
- Claude must execute the instructions in the blocking message (diary, learnings, commit)
- After Claude executes, the Stop hook runs AGAIN to handle the files Claude just wrote
- This creates a two-phase pattern: Phase 1 (work commit + diary/learnings), Phase 2 (commit those files)
- stdout from phase 1 goes to Claude as instructions; stdout from phase 2 goes to Claude as confirmation

### File path handling
- Always use absolute paths in hooks — the working directory may vary
- Quote all file paths: `"$FILE_PATH"` not `$FILE_PATH`
- When the hook receives paths from Claude Code, they're already absolute

## Checklist Before Writing a Hook

1. What event triggers this hook?
2. What input fields do I need from stdin?
3. What should the successful output look like? (JSON format)
4. What should the error output look like?
5. Am I printing anything to stdout that isn't the response JSON?
6. Am I assuming any env vars exist? (verify!)
7. If this hook modifies files, does it need to be idempotent?
8. What happens if this hook fails? (Does it block Claude? Silently fail?)

## Testing Hooks

```bash
# Test with sample input
echo '{"prompt": "test", "session_id": "abc", "transcript_path": "/tmp/test.jsonl"}' | bash $CLAUDE_CONFIG_DIR/hooks/my-hook.sh

# Validate JSON output
echo '{"prompt": "test"}' | bash $CLAUDE_CONFIG_DIR/hooks/my-hook.sh | python3 -c "import json, sys; json.load(sys.stdin); print('Valid JSON')"
```
