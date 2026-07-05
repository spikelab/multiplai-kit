# multiplai-kit — Developer Guide

This is the distributable Claude Code kit. See `README.md` for what it is and how users install/run it. This file covers how to **develop** the kit itself.

## Project Structure

This is a standalone git repo with its own `.git/`. There is a single working tree — develop directly in it.

**Key distinction:** `dotfiles/CLAUDE.md` is the user-facing global instructions that ship with the kit. This file (`CLAUDE.md` at project root) is for developing the kit.

**Architecture note — the memory system is now a plugin.** The context-routing, diary, and learnings-extraction hooks that used to live in `dotfiles/hooks/` have been extracted into a standalone Claude Code plugin, **`multiplai-context`**, published in the marketplace repo (`spikelab/multiplai-cc-mktplace`, under `plugins/multiplai-context/`). Those hooks were removed from this kit entirely — there is no `_retired/` directory. This kit now only ships the launcher, container, in-tree skills, reference docs, kit config, and the one remaining `validate-syntax` hook — and it installs the plugin from the marketplace. See `README.md` → "The Memory System Is Now a Plugin". When the bug is in routing/diary/learnings, fix it in the **marketplace repo**, not here.

## Git

- Single working tree, single `main` branch. Develop here; commit and push as usual.
- Personal data (`.multiplai/`, `.env`, `env.<profile>`) is gitignored and never enters the repo.

```bash
git status
git log --oneline -10
git add dotfiles/hooks/validate-syntax.sh
git commit -m "fix: tighten syntax validation"
```

## Environment Files & Secrets

This project has **four distinct env files** (plus their templates). Getting these mixed up is a real pitfall — read this section before adding any new environment variable.

| File | Committed? | Purpose |
|---|---|---|
| `.env` | **no** (gitignored) | Base config loaded on every launch. Workspace path, default git identity, GH token, container settings, **and all skill secrets (API keys)**. |
| `.env.example` | **yes** | Template for `.env`. Mirror every field here (with placeholder values/comments) so new users can `cp .env.example .env`. |
| `env.<profile>` | **no** (gitignored) | Optional per-profile overlay (e.g. `env.work`, `env.personal`). Contains only git identity + `GH_TOKEN_KEYCHAIN`. Loaded by `claude.sh --profile <name>` AFTER `.env`, so overrides specific fields. |
| `env.example` | **yes** | Template for profile files. Minimal — only the fields a profile is allowed to override. |

**Decision tree when adding a new env var:**

1. **Is it a secret or global config?** → `.env` (and mirror in `.env.example`)
2. **Is it a per-identity value that differs work vs personal?** → `.env` for the default, allowed in `env.<profile>` for overrides. Mirror in `env.example` if it's a new field profiles should support.
3. **Is it a skill-specific secret?** → `.env`. All skills load secrets from `.env` via `python-dotenv` (see the deep-research skill's `research_pipeline/env.py` in the `multiplai-research` plugin for the pattern: `$CLAUDE_MULTIPLAI_HOME/.env` first, then walk up from the script location).

**What NOT to do:**

- Don't create a new `.env.*` file for a specific skill. One `.env` at the project root, shared by all skills.
- Don't put secrets in `env.<profile>`. Profile files are for git identity overlay only. API keys go in `.env` so they apply regardless of which profile is active.
- Don't forget to update `.env.example` when you add a field to `.env`. The example file is the only thing new users see to know what keys are needed.

**Shell env wins over `.env`.** All loaders use `override=False` semantics. So `TAVILY_API_KEY=x python -m research_pipeline ...` overrides the value in `.env` for that single invocation.

**`claude.sh` launch flow:**

```
./claude.sh --profile personal
  ↓
1. source .env                    # WORKSPACE, default git, TAVILY_API_KEY, etc.
2. source env.personal            # overrides GIT_AUTHOR_NAME/EMAIL/GH_TOKEN_KEYCHAIN
3. start container with all resulting env vars inherited
4. inside container, skills call load_env() which re-reads .env
   (but override=False, so the shell values from steps 1-2 win)
```

See `README.md` → "Environment Configuration" for the user-facing version.

## Python Environment

Uses its own venv at `.venv/` (repo root). Hook scripts run via `run-hook-python` which resolves `$CLAUDE_MULTIPLAI_HOME/.venv/bin/python`. `setup.sh` creates and populates it.

```bash
# Create and install kit deps (run from the repo root)
uv venv .venv
uv pip install --python .venv/bin/python -r requirements.txt

# Sanity-check the kit venv is wired up
.venv/bin/python -m pytest evals/unit/ -q
```

## Running Evals

Evals live at `evals/` (project root, not inside dotfiles/) and cover the kit's **own live code** only — model-ceiling resolver, `multiplai.conf` loading, and `sync_skill_config.py`. Free, fast, no API key. See `evals/README.md`.

```bash
# From the repo root
.venv/bin/python -m pytest evals/ -q
```

| File | Covers |
|------|--------|
| `evals/unit/test_model_resolver.py` | Model-ceiling logic (`dotfiles/hooks/model_resolver.py`) |
| `evals/unit/test_config_loading.py` | `multiplai.conf` parsing |
| `evals/unit/test_sync_skill_config.py` | `scripts/sync_skill_config.py` |

**The memory / routing / learnings evals are gone** — they tested the retired in-tree hooks and were removed with them. Those mechanisms now live in the `multiplai-context` plugin, which has its own `tests/` (run from the plugin dir). Threshold for the kit tests: 100% (any failure is a bug).

## Editing Hooks

**The memory/lifecycle hooks moved to the plugin.** Routing (`context_manager.py`), session lifecycle (`session_start.py`, `session_stop.py`, `session_end.py`, `pre_compact.py`), and learnings extraction (`extract_learnings.py`) now live in the marketplace repo (`multiplai-cc-mktplace`) under `plugins/multiplai-context/scripts/`, registered in that plugin's `hooks/hooks.json`. Edit and test them there.

What's left in this kit's `dotfiles/hooks/` and registered in `dotfiles/settings.json` is just **`validate-syntax.sh`** (PostToolUse on Write|Edit). Everything else in `dotfiles/hooks/` is a live helper: `run-hook-python`, `model_resolver.py`, `log_utils.py`.

**Hook protocol:** Hooks receive JSON on stdin, write JSON to stdout. See Claude Code docs for the schema per event type.

**Key constraint (plugin side):** SessionEnd hooks are killed within seconds — they cannot run long-running scripts. The plugin uses the deferred pattern (write a marker at SessionEnd, process at next SessionStart via a detached subprocess). See the plugin's `scripts/session_end.py` and `scripts/extract_learnings.py`.

**Testing the in-tree hook locally:**
```bash
# Syntax validation (PostToolUse)
echo '{"hook_event_name":"PostToolUse","tool_name":"Write","tool_input":{"file_path":"/tmp/x.json","content":"{}"}}' | \
  bash dotfiles/hooks/validate-syntax.sh
```

To test the memory/lifecycle hooks, run them from the plugin repo (it has its own `tests/`).

## Editing Skills

The skill library ships as themed marketplace plugins (`multiplai-pm`, `multiplai-writing`, `multiplai-research`, `multiplai-dev`, `multiplai-media`) developed in the marketplace repo (`multiplai-cc-mktplace`), not here. `dotfiles/skills/` is reserved for the user's own local skills: one directory per skill with a `SKILL.md` (frontmatter + prompt) and optionally `scripts/`, `references/`, or supporting `.md` files. The `/multiplai-context:*` skills live in the marketplace repo too.

## Configuration

`multiplai.conf` (at the kit project root, NOT in dotfiles/) sets the model/effort ceilings, log level/retention, and per-skill overrides for the **in-tree skills**. Changes take effect on next invocation. See the file for documentation on each setting.

`dotfiles/settings.json` controls Claude Code settings (hooks, permissions, UI). Changes take effect on next session start.

## Testing Changes

Run the kit's unit tests after any change to live kit code:

```bash
.venv/bin/python -m pytest evals/ -q
```

> The old dev-instance + smoke-test harness (`make-dev-instance.sh`,
> `smoke-test.sh`, `evals/smoke/`) was removed — it was built around the
> in-tree hooks that now live in the `multiplai-context` plugin. A replacement
> isolated-testing flow is TBD; until then, run `pytest evals/` and test
> memory/routing changes in the plugin repo (which has its own `tests/`).

## Key Files

| File | Purpose |
|------|---------|
| `dotfiles/settings.json` | Registers the `validate-syntax` hook; `pluginConfigs.multiplai`; statusline; permissions |
| `multiplai.conf` | Kit config (model/effort ceiling, per-skill overrides) — at project root, NOT in dotfiles/ |
| `dotfiles/hooks/validate-syntax.sh` | The one runtime hook still registered (PostToolUse Write\|Edit) |
| `dotfiles/hooks/model_resolver.py` | Model-ceiling logic for in-tree skills |
| `dotfiles/hooks/log_utils.py` | Shared logging helper (used via PYTHONPATH by plugin skills — buildme, deep-research) |
| `multiplai-cc-mktplace` → `plugins/multiplai-context/` | The memory/context/learning plugin (marketplace repo) — routing, diary, learnings now live here |
| `evals/conftest.py` | Test infra — `sys.path` wiring + LLM bypass for the kit unit tests |
| `container/` | Container tooling — fetched at setup from spikelab/multiplai-container |
| `setup.sh` | First-time setup with prerequisite validation |
| `claude.sh` | Launcher (container/local/shell modes) |
