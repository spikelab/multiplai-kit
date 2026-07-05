# Hooks Reference

The memory/context/lifecycle hooks that used to live here have been extracted
into the **`multiplai-context`** plugin (installed from the marketplace). This
kit now ships exactly **one** registered hook plus two live helpers, all in
`dotfiles/hooks/` and configured in `dotfiles/settings.json` under `hooks`.

## Registered hook

| Event | When | Hook |
|-------|------|------|
| PostToolUse (Write\|Edit) | After a file is written/edited | `validate-syntax.sh` |

Session lifecycle (SessionStart/Stop/SessionEnd/PreCompact) and per-prompt
context routing (UserPromptSubmit) are handled by the `multiplai-context`
plugin, registered in that plugin's own `hooks/hooks.json` — not here. To edit
or debug them, work in the plugin, not this kit.

## Hook details

### validate-syntax.sh
PostToolUse hook. After a Write/Edit to a `.json`/`.yaml`/`.yml` file it parses
the file and, on a syntax error, exits 2 with the error on stderr so Claude
sees the failure and can self-correct (a trailing comma in `settings.json`
would otherwise silently break every hook). Valid files exit 0 with no output.

### run-hook-python (helper, not registered)
Wrapper that routes a Python hook invocation to the workspace venv's python
(`$CLAUDE_MULTIPLAI_HOME/.venv/bin/python`), falling back to system `python3`.
It also parses `multiplai.conf` (without `eval`) and exports the
`MULTIPLAI_*` config vars for the invoked script.

### model_resolver.py, log_utils.py (helpers, not registered)
`model_resolver.py` resolves the model/effort ceiling for the in-tree skills;
`log_utils.py` is the shared logging helper. Neither is a hook itself.

## Python dependencies

`validate-syntax.sh` needs only `pyyaml` (for YAML). See `requirements.txt`.

## Adding a custom hook

1. Create your hook script in `dotfiles/hooks/`.
2. Register it in `dotfiles/settings.json` under the appropriate event.
3. For Python hooks, invoke via `run-hook-python`:
   ```json
   "command": "bash $CLAUDE_CONFIG_DIR/hooks/run-hook-python $CLAUDE_CONFIG_DIR/hooks/my-hook.py"
   ```
