# Skill Development Guide

Reference for building new skills or modifying existing ones in the multiplai kit.

## Directory Layout

```
dotfiles/skills/<skill-name>/
├── SKILL.md              # Prompt template — Claude reads this to execute the skill
├── instructions.md       # Short description for skill catalog (1-2 sentences)
├── scripts/              # Python/shell code the skill invokes
│   ├── <package>/        # Python package (invoked with python -m <package>)
│   │   ├── __init__.py
│   │   ├── __main__.py   # CLI entry point
│   │   └── ...
│   ├── tests/            # Tests (mock all LLM calls, no API keys needed)
│   └── CLAUDE.md         # Dev notes for the scripts directory
├── references/           # Skill-specific reference material
└── README.md             # User-facing documentation
```

## Logging — MANDATORY

All skill Python code MUST use the shared `log_utils` module from `dotfiles/hooks/`.
Do NOT create a custom logging setup. Do NOT use `logging.basicConfig()`.
Do NOT write log files with manual file I/O.

### Setup

In SKILL.md, before any Python invocation:

```bash
export PYTHONPATH="$CLAUDE_CONFIG_DIR/hooks:${PYTHONPATH:-}"
```

In Python code:

```python
from log_utils import setup_logging

# Call once at startup — name must match the skill name
logger = setup_logging("my-skill", session_id=session_id)
```

In modules that just need a logger (don't call setup_logging again):

```python
import logging
log = logging.getLogger(__name__)
```

### What the shared module handles

- Log format: `[timestamp] [component] [session:xxxxxxxx] LEVEL: message`
- UTC timestamps (ISO 8601)
- Session ID injection (first 8 chars)
- `MULTIPLAI_LOG_LEVEL` / `MULTIPLAI_DEBUG` config
- Date-rotated file handler (7-day retention)
- ERROR+ drain to shared `hook-errors.log`
- Log directory: `$CLAUDE_MULTIPLAI_HOME/runtime/logs/`

### Structured messages

Use verb prefixes and key=value pairs for parseable log lines:

| Prefix | When |
|--------|------|
| `START` | Operation beginning (include key params) |
| `DONE`  | Operation completed (include result summary) |
| `SKIP`  | Operation skipped (include reason) |
| `FAIL`  | Operation failed (include error) |

```python
log.info("START stage=search query=%s providers=%d", query, len(providers))
log.info("DONE stage=search results=%d duration=%.1fs", count, elapsed)
log.warning("SKIP stage=fetch reason=timeout url=%s", url)
log.error("FAIL stage=synthesize reason=%s", str(err))
```

See `dotfiles/reference/dev/logging-standard.md` for the full spec.

## Environment & Secrets

- All secrets (API keys) live in the project root `.env` file — one file, shared by all skills
- Load with `python-dotenv`: `load_dotenv(project_root / ".env", override=False)`
- Shell env wins over `.env` (use `override=False`)
- Mirror every key in `.env.example` with placeholder values
- Do NOT create per-skill `.env` files

For the standard `.env` loading pattern, see `deep-research/scripts/research_pipeline/env.py`.

## Python Invocation Pattern

Skills invoke Python as a module from their scripts directory:

```bash
# In SKILL.md:
export PYTHONPATH="$CLAUDE_CONFIG_DIR/hooks:${PYTHONPATH:-}"
cd "$CLAUDE_CONFIG_DIR/skills/<skill>/scripts" && python3 -m <package> \
  --session-id "{session_id}" \
  [other args]
```

Always pass `--session-id` for log correlation.

## Testing

- All tests mock LLM/API calls — no API keys needed, runs in milliseconds
- Use `PYTHONPATH=. python -m pytest tests/ -xvs` from the scripts directory
- Tests go in `scripts/tests/`, not at the skill root

## What NOT to Do

- Don't duplicate shared utilities (logging, env loading) — import them
- Don't hardcode log directories — `log_utils` handles this
- Don't write to `$CLAUDE_CONFIG_DIR/logs/` directly — use the logger
- Don't add dependencies outside the project root `requirements.txt`
- Don't create per-skill venvs (exception: if the skill has conflicting deps, discuss first)
