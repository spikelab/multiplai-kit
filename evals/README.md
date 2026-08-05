# Eval Suite

Unit tests for the kit's **own live code**. Free, fast, no API key.

```bash
.venv/bin/python -m pytest evals/ -q
```

| File | Covers |
|------|--------|
| `unit/test_model_resolver.py` | Model-ceiling logic (`dotfiles/hooks/model_resolver.py`) |
| `unit/test_config_loading.py` | `multiplai.conf` parsing (model/effort ceilings) |
| `unit/test_claude_sh_env.py` | `claude.sh` container env forwarding + GitHub auth-mode selection, on the container path (stub `docker`) and the bare `--local` path (stub `claude`) |
| `unit/test_guard_destructive.py` | PreToolUse destructive-command guard, calibrated in both directions |
| `unit/test_guard_hook_wiring.py` | Whether the guard is *reached* — no shell redirect on its hook command, `run-hook-python` makes its own log dir, wrapper denies when the guard can't run |
| `unit/test_log_retention.py` | Log rotation/retention helper |
| `unit/test_gh_app_hooks.py` | The GitHub App SessionStart/PreToolUse hooks (stub `gh-tok` + stub `gh`) |

## What moved out

The memory / context-routing / learnings system is no longer in this repo — it's
the **`multiplai-context` plugin** in the marketplace repo (`multiplai-cc-mktplace`,
under `plugins/multiplai-context/`). Its tests live there (`tests/`). The old
in-tree routing / extraction / diary evals were removed along with the retired
hooks they targeted.
