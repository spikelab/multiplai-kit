# Eval Suite

Unit tests for the kit's **own live code**. Free, fast, no API key.

```bash
.venv/bin/python -m pytest evals/ -q
```

| File | Covers |
|------|--------|
| `unit/test_model_resolver.py` | Model-ceiling logic (`dotfiles/hooks/model_resolver.py`) |
| `unit/test_config_loading.py` | `multiplai.conf` parsing (model/effort ceilings, per-skill overrides) |
| `unit/test_sync_skill_config.py` | `scripts/sync_skill_config.py` |

## What moved out

The memory / context-routing / learnings system is no longer in this repo — it's
the **`multiplai-context` plugin** (`PROJECTS/multiplai-plugin/plugins/multiplai-context/`).
Its tests live there (`tests/`, run from the plugin dir). The old in-tree routing /
extraction / diary evals were removed along with the retired hooks they targeted.
