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

## Tool Shape Policy

**Skills ship conventional CLIs.** A bundled script takes argparse flags, writes
to stdout, and exits non-zero on failure. It does not take a JSON blob on stdin
or in `argv`, and it does not invent a bespoke RPC envelope.

The reason is that the model already knows how to use a CLI. Command-line
conventions — `--flag value`, `--help`, exit codes, stdout/stderr separation —
are in the training data a million times over; your custom JSON envelope is in
it zero times, so every invocation spends context re-learning a protocol that
buys nothing. A conventional CLI is also debuggable by hand: you can paste the
command into a terminal and see what the skill saw, which is the difference
between a five-minute fix and an afternoon.

```python
# Good — the model can guess this without reading your source.
parser = argparse.ArgumentParser(description="Render the cost report.")
parser.add_argument("--since", help="ISO date; defaults to 30 days ago")
parser.add_argument("--json", action="store_true", help="machine-readable output")
```

```python
# Bad — a protocol nobody has seen before, undebuggable from a shell.
payload = json.loads(sys.argv[1])
```

**Every entry point gets `--help`,** including ones that currently take no
arguments. `--help` is how both a human and the model discover what a script
does without reading it; a script that responds to `--help` with a traceback
reads as broken.

**The one legitimate exception is a hook.** Claude Code's hook contract *is*
JSON on stdin and JSON on stdout — `context_manager.py` reading
`json.load(sys.stdin)` is conforming to a published protocol, not inventing
one. When a tool schema is genuinely unavoidable, mirror the shape of Claude
Code's own native tools rather than designing a new one.

## Model-Upgrade Re-Test Checklist

Skills are prompts, and a prompt tuned against one model is not automatically
correct against the next. A model bump can silently change output format,
verbosity, refusal behaviour, or how literally an instruction is followed —
none of which raises an error. Run this whenever the `MULTIPLAI_MODEL` ceiling
changes, a skill's `model:`/`effort:` frontmatter changes, or Claude Code's
default model moves under you.

1. **Smoke-invoke every skill.** Each bundled script runs with `--help` and with
   its documented minimal invocation. Anything that traces back is broken now,
   whatever it did before.
2. **Run the contract assertions.** Skills with a `CONTRACT.md` have concrete
   expected-output checks; run them and diff. These are the checks that catch a
   changed *output shape* rather than a crash.
3. **Re-read the frontmatter tier.** A newer model at `effort: medium` often
   matches the previous one at `high` — the pin that was right six months ago
   may now be overpaying. Check the cost report before and after.
4. **Delete scaffolding the model no longer needs.** Newer models absorb
   capabilities that older ones needed step-by-step instructions for. Prompt
   scaffolding that has become redundant is not free: it costs context on every
   invocation and constrains a model that would do better unconstrained. Be
   aggressive here — a skill that shrinks on a model upgrade is the normal
   outcome, not a suspicious one.
5. **Record the result** in the skill's diary/learnings entry, so the next
   upgrade starts from what changed last time.

`config-audit` references this checklist on its cadence, so the prompt to run it
arrives without anyone having to remember.

## What NOT to Do

- Don't duplicate shared utilities (logging, env loading) — import them
- Don't hardcode log directories — `log_utils` handles this
- Don't write to `$CLAUDE_CONFIG_DIR/logs/` directly — use the logger
- Don't add dependencies outside the project root `requirements.txt`
- Don't create per-skill venvs (exception: if the skill has conflicting deps, discuss first)
- Don't take a JSON blob on stdin or in `argv` — ship an argparse CLI (see Tool Shape Policy; hooks are the one exception)
- Don't ship an entry point without `--help`
