# multiplai-kit

A distributable Claude Code kit — launcher, container, reference docs, and workspace conventions as a self-contained package. Clone it, run setup, launch via the wrapper script, and get the full system without touching your existing `~/.claude/`.

The skill library and the memory/context layer ship as **Claude Code plugins from the Multiplai marketplace** (`spikelab/multiplai-cc-mktplace`): the [`multiplai-context`](#the-memory-system-is-now-a-plugin) plugin (memory, routing, lifecycle) plus five themed skill packs (`multiplai-pm`, `multiplai-writing`, `multiplai-research`, `multiplai-dev`, `multiplai-media`). `setup.sh` installs the marketplace and the context plugin; you pick the skill packs you want.

## How It Works

Sets `CLAUDE_CONFIG_DIR` to the included `dotfiles/` directory before launching Claude Code. This makes Claude Code use the kit's settings, skills, reference docs, and config instead of `~/.claude/`. Your existing Claude Code config is completely untouched.

The kit is responsible for:
- **Launcher** (`claude.sh`) — container/local/shell modes, git-identity profiles, GCP overlays.
- **Container** — a sandboxed Docker/OrbStack image (fetched from [`multiplai-container`](https://github.com/spikelab/multiplai-container) at setup) that runs Claude with `--dangerously-skip-permissions` safely.
- **Reference docs** (21) — prescriptive best-practice docs loaded per coding task.
- **Kit config** (`multiplai.conf`) — model/effort ceilings and per-skill overrides.
- **Installing and configuring the Multiplai plugins** — the `multiplai-context` memory/lifecycle plugin and the themed skill packs (see `docs/SKILLS.md`).

## The Memory System Is Now a Plugin

Earlier versions of this kit shipped the memory system as in-tree hooks (`context-router.py`, `session-lifecycle.py`, `extract-learnings.py`, `autodream.py`, `synthesize-now.py`) registered in `settings.json`. **Those have been extracted into a standalone plugin** and now live under `dotfiles/hooks/_retired/`. The only hook the kit still registers directly is `validate-syntax.sh`.

The replacement is **`multiplai-context`** (v0.4.0), a normal Claude Code plugin developed in its own repo:

```
PROJECTS/multiplai-plugin/
├── .claude-plugin/marketplace.json     # marketplace "multiplai"
└── plugins/multiplai-context/
    ├── .claude-plugin/plugin.json       # plugin manifest + userConfig schema
    ├── hooks/hooks.json                 # SessionStart / UserPromptSubmit / Stop / SessionEnd / PreCompact
    ├── scripts/                         # context_manager.py, session_*.py, extract_learnings.py, dream.py, …
    ├── skills/                          # setup, dream, dream-remember, health, memory-health-audit, now, refresh-catalogs, backfill
    └── templates/                       # starter memory files
```

What the plugin provides (see its own `README.md` for full detail):
- **Per-prompt context routing** — a `UserPromptSubmit` hook routes each prompt against indexed catalogs and injects only the relevant memory.
- **Session lifecycle** — diary per UTC day, deferred learnings extraction, dream-due nudge.
- **Consolidation** — `/multiplai-context:dream` proposes memory edits; `/multiplai-context:dream-remember` reviews and applies them.

### How the kit loads and configures the plugin

The plugin is installed **from the marketplace** (done by `setup.sh`, or manually):

```
/plugin marketplace add spikelab/multiplai-cc-mktplace
/plugin install multiplai-context@multiplai
```

Because `CLAUDE_CONFIG_DIR` points at the kit's `dotfiles/`, the install lands in `dotfiles/plugins/` — self-contained, nothing touches `~/.claude/`. Options come from `settings.json` → `pluginConfigs["multiplai-context@multiplai"].options`; `setup.sh` fills the path options (`workspace_dir`, `skills_dir`, `resources_dir`) from your `.env`.

For **plugin development**, sideload a checkout instead with `claude --plugin-dir <path-to-plugin>` and pass options via `CLAUDE_PLUGIN_OPTION_*` env vars (sideloaded plugins do not read `pluginConfigs` automatically; `claude.sh` forwards these vars into the container).

## Prerequisites

**Required:**
- Claude Code CLI (`npm install -g @anthropic-ai/claude-code`)
- Claude Max plan or API key (the plugin's LLM calls use the Agent SDK, with an API-key fallback)
- Python 3.11+ and uv (or pip)
- git
- jq
- ripgrep (`rg`)

**Recommended:**
- Docker / OrbStack (container mode is the default — without it, Claude runs unsandboxed on your host)
- ffmpeg (for youtube-transcript audio fallback and the transcribe skill)

**Optional (macOS only):**
- mlx-whisper (for local audio transcription via Metal GPU)

## Quick Start

```bash
# Clone
git clone https://github.com/spikelab/multiplai-kit
cd multiplai-kit

# Configure
cp .env.example .env
# Edit .env: set WORKSPACE (absolute path), GIT_AUTHOR_NAME, GIT_AUTHOR_EMAIL

# Setup (creates workspace, memory templates, configures the kit, builds Docker image)
./setup.sh

# Launch
./claude.sh
```

First run prompts for authentication via `/login`. Credentials persist in `~/.claude-container/credentials.json` across container restarts. The plugin's Python scripts declare their own dependencies via PEP 723 inline metadata and run under `uv run --no-project`, so deps are resolved on demand — no manual install or managed-venv step.

## The Workspace Model

Setup creates a workspace with `INBOX/`, `PROJECTS/`, `RESOURCES/`, and the plugin's `.multiplai/` state directory. The key concept: **everything you work on is a project.**

Projects aren't just code. A project is anything you have multiple sessions about:

| Example | What it is |
|---------|-----------|
| `PROJECTS/my-app/` | A codebase you're building |
| `PROJECTS/job-search/` | Applications, resumes, interview prep |
| `PROJECTS/relocation/` | Visa research, apartment hunting, checklists |
| `PROJECTS/health-plan/` | Exercise routine, meal planning, tracking |
| `PROJECTS/finances/` | Tax prep, budgeting, investment research |
| `PROJECTS/book-project/` | Drafts, outlines, research notes |

Creating a project directory is how you tell the system "this is a thing I'm working on." It gives your sessions a home — files, plans, and context accumulate there across sessions instead of scattering across `INBOX/`.

**Projects can be temporary.** Working on something for a week? Create a project directory, work in it, delete it when done. The diary and learnings captured along the way persist under `.multiplai/` regardless.

**Projects can have their own git repos.** Code projects often do — each self-contained sub-project carries its own `.git/` (and `.venv/` if Python). The workspace repo only tracks workspace-level files.

### How Projects Connect to Memory

The plugin's routing is project-aware. When you start a session and mention a project, the `UserPromptSubmit` hook identifies the relevant context and injects it. Over time the plugin builds per-project `now/` state summaries from your diary, so each new session starts with awareness of where that project stands — recent decisions, active branches, blockers, next actions.

## Launcher Modes

`claude.sh` detects the runtime context automatically:

| Context | What happens |
|---------|-------------|
| Docker available (default) | Runs in container with `--dangerously-skip-permissions` (container IS the sandbox) |
| `--local` flag | Bare mode on host, permission prompts active, no container |
| `--shell` flag | Container bash shell (for debugging) |
| Already inside container | Bare mode + `--dangerously-skip-permissions` |
| No Docker installed | Warns, falls back to bare mode without skip-permissions |

```bash
./claude.sh                         # container (default)
./claude.sh --profile work          # container, work git identity
./claude.sh --gcp ro                # container + GCP credential overlay
./claude.sh --local                 # bare mode, host permissions
./claude.sh --shell                 # container bash shell
./claude.sh --profile work --shell  # work profile, bash shell
```

`claude.sh` also passes through `--plugin-dir` / `--add-dir` to the underlying `claude` invocation (and keeps them out of `bash` in `--shell` mode), plus `--strict-mcp-config` to isolate account-level MCP integrations.

## Environment Configuration

The kit uses **two kinds of env files** with similar names — intentional but confusing at first glance:

| File | Committed? | Purpose | Loaded |
|---|---|---|---|
| `.env` | gitignored | **Base config** — workspace path, default git identity, GH token, container settings, **and secrets (API keys for skills)** | Always, by `claude.sh` |
| `.env.example` | committed | Template for `.env` | Manual: `cp .env.example .env` |
| `env.<profile>` (e.g. `env.work`, `env.personal`) | gitignored | **Optional override layer** — git identity and GH token only. Does NOT replace `.env`, just overrides specific fields. | Only when `--profile <name>` is passed |
| `env.example` | committed | Template for profile files | Manual: `cp env.example env.<name>` |
| `env.<gcp>` (e.g. `env.gcp.ro`) | gitignored | **GCP credential overlay** — sets `GCP_KEY_FILE` + `GCP_PROJECT` | Only when `--gcp <name>` is passed |

**Rule of thumb — where does a new value belong?**

| New value | Where it goes |
|---|---|
| Secret (API key, token) used by a skill | `.env` (add matching entry to `.env.example`) |
| Global config (workspace path, container settings) | `.env` |
| Per-identity value (git name/email/GH token) that changes between work/personal | `.env` (default) + `env.<profile>` (overrides) |
| Plugin option you want forwarded to the container | export `CLAUDE_PLUGIN_OPTION_<NAME>` before launch (`claude.sh` forwards it) |

**The dot matters.** `.env.example` (leading dot) is the template for the base config. `env.example` (no dot) is the template for profile overrides. They are NOT duplicates.

### Creating a Profile (optional)

Profiles switch git identity and GitHub token for different contexts (personal vs work). They layer on top of `.env`:

```bash
cp env.example env.work
# Edit env.work: set GIT_AUTHOR_NAME, GIT_AUTHOR_EMAIL, GH_TOKEN_KEYCHAIN

./claude.sh --profile work
```

Profile files override only:
- `GIT_AUTHOR_NAME` / `GIT_AUTHOR_EMAIL`, `GIT_COMMITTER_NAME` / `GIT_COMMITTER_EMAIL`
- `GH_TOKEN_KEYCHAIN` — macOS Keychain key for the GitHub token
- `CLAUDE_CREDENTIALS_FILE` — separate Claude OAuth credentials file per profile
- `GEMINI_CONFIG_DIR` — optional separate Gemini CLI config dir

Without `--profile`, only `.env` is loaded. For a full walkthrough — Keychain setup, separate Claude login, a worked example — see [`docs/PROFILES.md`](docs/PROFILES.md).

### How Skills Access Secrets

Skills that need secrets (e.g. `deep-research` uses `TAVILY_API_KEY`, `EXA_API_KEY`; optionally `BRAVE_API_KEY`, `SERPER_API_KEY`) load them from `.env` automatically via `python-dotenv`. No per-skill config files. Add the key to `.env` (and document it in `.env.example`) and the skill picks it up on next launch. Shell-exported env vars take precedence over `.env` values:

```bash
TAVILY_API_KEY=override-key ./claude.sh
```

## Architecture

```
multiplai-kit/                          # = the "runtime" / kit repo
├── claude.sh              # Single entrypoint (container default, --local, --shell, --profile, --gcp)
├── setup.sh               # One-time: prerequisite checks, workspace, memory templates, Docker build
├── multiplai.conf         # Kit config (model/effort ceilings, per-skill overrides) — project root, NOT in dotfiles/
├── requirements.txt       # Kit venv deps
├── .env.example           # Base config template (becomes .env — workspace, secrets)
├── env.example            # Profile template (becomes env.<name> — git identity overlay)
│
├── dotfiles/              # = CLAUDE_CONFIG_DIR (Claude Code reads everything from here)
│   ├── CLAUDE.md          # Global instructions (personalized by setup.sh)
│   ├── settings.json      # Registers validate-syntax hook; pluginConfigs.multiplai; statusline; permissions
│   ├── hooks/             # validate-syntax.sh, run-hook-python, model_resolver.py, catalog generators
│   │   └── _retired/      # Old in-tree memory hooks, superseded by the multiplai-context plugin
│   ├── skills/            # Your own local skills (the skill library ships as marketplace plugins)
│   ├── reference/dev/     # 21 best-practice docs
│   ├── scripts/           # statusline, file picker, sync_skill_config.py
│   ├── output-styles/     # Output formatting
│   ├── templates/         # Project templates
│   ├── plugins/           # Claude Code plugin state (marketplaces, cache) — incl. the loaded plugin
│   └── logs/              # Hook logs (validate-syntax, errors)
│
├── runtime/
│   └── logs/              # Component logs (deep-research, build-pipeline, …)
│
├── evals/                 # Unit tests for the kit's own live code (project root, NOT in dotfiles/)
├── container/             # Dockerfile, build.sh, venv-sync-entrypoint.sh, apple-containers-experiment.sh
├── scripts/               # sync_skill_config.py (skill model/effort sync)
├── workspace-scaffold/    # Templates for a new workspace (CLAUDE.md.template, memory/)
│
├── docs/                  # SKILLS.md, HOOKS.md, CUSTOMIZATION.md, PROFILES.md
│
└── (loaded separately)
    PROJECTS/multiplai-plugin/plugins/multiplai-context/   # the memory/context/learning plugin
```

## What's Included

### Hooks (in-tree)

The kit registers exactly one runtime hook in `settings.json`; everything else in `dotfiles/hooks/` is a live helper:

| File | Role |
|------|------|
| `validate-syntax.sh` | PostToolUse (Write\|Edit) — validates YAML/JSON syntax. The only hook registered in `settings.json`. |
| `run-hook-python` | Wrapper that routes Python hook scripts to the kit venv |
| `model_resolver.py` | Model-ceiling logic (caps a requested tier via `MULTIPLAI_MODEL`) |
| `log_utils.py` | Shared logging helper used via PYTHONPATH by plugin skills (buildme, deep-research) |

Memory routing, diary, learnings extraction, and the autodream gate now live in the **`multiplai-context` plugin**, not here. The old in-tree hooks and catalog generators have been removed along with the tests that targeted them.

### Skills (themed marketplace packs)

The skill library ships as five themed plugins from the Multiplai marketplace — `multiplai-pm`, `multiplai-writing`, `multiplai-research`, `multiplai-dev`, `multiplai-media` — install the ones you want. See `docs/SKILLS.md` for the pack index. `dotfiles/skills/` stays available for your own local skills. The `multiplai-context` plugin adds its namespaced commands under `/multiplai-context:*` (below).

### Memory, Context & Learning (provided by the plugin)

All of the following is the **`multiplai-context` plugin** — summarized here; see its `README.md` for the authoritative version.

**Per-prompt context routing.** A `UserPromptSubmit` hook routes every prompt against indexed catalogs (memory, and optionally skills/resources) and injects only what's relevant — no memory dump. Two routing strategies:
- **`token_overlap`** (default) — offline keyword overlap, instant, no model call.
- **`llm`** — one model call per prompt (default model **Haiku**, `router_model`). Measured ~7–10s/prompt via the Agent SDK (CLI cold-start per call), so it's best treated as a routing-quality experiment, not steady-state. Prefer `token_overlap` for daily use.

**Re-recommendation cooldown.** After a file is injected, it's suppressed from re-injection for `recommend_cooldown_turns` turns (default 4) — it's already in the conversation. The `PreCompact` hook clears the map after compaction (the content was summarized away), so a longer cooldown can never starve the model.

**Catalogs.** Memory/skills/resources catalogs are generated and cached by the plugin under `.multiplai/data/` (regenerate with `/multiplai-context:refresh-catalogs`). The kit no longer carries its own catalog generators.

### Session Lifecycle (plugin hooks)

| Event | Plugin script | Role |
|-------|---------------|------|
| `SessionStart` | `session_start.py` | Init session state; drain deferred extractions; emit dream-due nudge |
| `UserPromptSubmit` | `context_manager.py` | Route the prompt and inject relevant memory |
| `Stop` | `session_stop.py` | Lightweight checkpoint |
| `SessionEnd` | `session_end.py` | Write a deferred-extraction marker for the next session to process |
| `PreCompact` | `pre_compact.py` | Enqueue a deferred-extraction marker; clear the cooldown map |

Heavy LLM extraction never runs inside a kill-within-seconds hook — it's deferred via a marker queue (`data/pending_extractions/`) and processed by `extract_learnings.py` as a detached subprocess from the next `SessionStart`.

### How It Learns

```
Session conversation
    ↓
SessionEnd / PreCompact writes a marker  (instant — no LLM in the hook)
    ↓
next SessionStart spawns extract_learnings.py (detached) → diary + learnings
    ↓
.multiplai/learnings/*.md   (pending — per-day)
    ↓
/multiplai-context:dream            → proposal in .multiplai/dreams/
/multiplai-context:dream-remember   → human review, approve/reject per file
    ↓
.multiplai/memory/*.md       (permanent context — routed in automatically)
```

**What doesn't happen automatically:** memory updates. Extracted learnings sit in `.multiplai/learnings/` until you run `/multiplai-context:dream-remember` and approve the proposed edits. The human reviews what enters permanent memory.

### Plugin Commands

All namespaced under `/multiplai-context:`:

| Command | What it does |
|---------|--------------|
| `/multiplai-context:setup` | Onboarding interviewer — populates memory files from starter templates |
| `/multiplai-context:dream` | Generate a consolidation **proposal** from the learnings backlog into `.multiplai/dreams/` (no edits) |
| `/multiplai-context:dream-remember` | Review the proposal, approve/reject per target file, apply edits, clean up processed learnings |
| `/multiplai-context:health` | Mechanical infra check — model client, dirs present, memory freshness, diary/learnings counts. Fast, cheap |
| `/multiplai-context:memory-health-audit` | Analytical effectiveness audit — cross-correlates retrieval logs, diary, learnings, structure. Run ~monthly |
| `/multiplai-context:refresh-catalogs` | Regenerate catalog indexes (`--force`, `--dry-run`, `--only`) |
| `/multiplai-context:backfill` | Reconstruct learnings/diary/now from existing transcripts (`--days N`, `--since DATE`, `--all`) |
| `/multiplai-context:now` | Rebuild per-project `now/` status snapshots from recent diary entries |

### Where Your Data Lives

Everything stays under `<workspace>/.multiplai/` (or `~/.multiplai/` if `workspace_dir` is unset):

| Subdir | What's in it |
|--------|--------------|
| `memory/` | Your memory files — you edit these directly |
| `diary/` | One `YYYY-MM-DD.md` file per UTC day, one block per session that ran |
| `learnings/` | Extracted insights pending consolidation (per-day) |
| `dreams/` | Pending consolidation proposals awaiting review |
| `now/` | Per-project current-state summaries |
| `data/` | Runtime state — catalogs, logs, plugin venv, deferred-extraction markers. Disposable |

Memory files are the one thing worth version-controlling. The plugin's `/multiplai-context:setup` detects whether `memory_dir` is inside a git repo and offers to `git init` it; `/multiplai-context:dream` (auto mode) then commits memory changes after each consolidation.

### Plugin Configuration

Set via `settings.json → pluginConfigs.multiplai.options` (and/or forwarded `CLAUDE_PLUGIN_OPTION_*` env vars). The options you'll actually touch:

| Option | Default | Purpose |
|--------|---------|---------|
| `workspace_dir` | `""` | Anchor for all state — memory/diary/now/learnings default under `<workspace_dir>/.multiplai/` |
| `memory_router` | `token_overlap` | Routing strategy: `token_overlap` (offline, fast) or `llm` (one model call/prompt) |
| `router_model` | `claude-haiku-4-5` | Model for the `llm` router (ignored under `token_overlap`) |
| `recommend_cooldown_turns` | `4` | Turns to suppress re-injecting a just-injected file (`0` disables) |
| `catalog_model` | `claude-sonnet-4-6` | Model for LLM catalog generation |
| `enable_skills` / `skills_dir` | `false` / `~/.claude/skills` | Optionally catalog skills for routing (the kit points `skills_dir` at `dotfiles/skills`) |
| `enable_resources` / `resources_dir` | `false` / `""` | Optionally catalog a research/reference corpus |
| `anthropic_api_key` | _(sensitive)_ | API-key fallback when the Agent SDK is unavailable |

### Kit Configuration (`multiplai.conf`)

Separate from the plugin. `multiplai.conf` (project root, **not** in `dotfiles/`) sets model/effort ceilings and per-skill overrides for the **in-tree skills**. Changes take effect on next invocation.

| Setting | Default | Purpose |
|---------|---------|---------|
| `MULTIPLAI_DEBUG` | `false` | Verbose logging |
| `MULTIPLAI_MODEL` | `claude-opus-4-6` | Model ceiling — caps the tier a skill/hook can request (`haiku < sonnet < opus`) |
| `MULTIPLAI_EFFORT` | `high` | Effort ceiling (`low < medium < high < max`) |
| `MULTIPLAI_LOG_LEVEL` | `INFO` | Component log verbosity |
| `MULTIPLAI_LOG_RETENTION_DAYS` | `0` | Rotated-log retention (`0` = keep forever) |

Per-skill `[section]` overrides set exact model/effort for a named skill; run `python scripts/sync_skill_config.py` after editing (setup.sh does this automatically).

### Eval Suite

Unit tests at `evals/` (project root) covering the kit's **own live code** — the model-ceiling resolver, `multiplai.conf` loading, and `sync_skill_config.py`. Free, fast, no API key.

```bash
.venv/bin/python -m pytest evals/ -q
```

The memory/routing/learnings mechanisms (and their tests) moved to the **`multiplai-context` plugin**, which has its own `tests/` suite run from `PROJECTS/multiplai-plugin/plugins/multiplai-context/`.

## Container Mode

### Why Docker/OrbStack (not Apple Containers)

We evaluated Apple's native containerization framework (Virtualization.framework + `container` CLI) on macOS 26 Tahoe in March 2026. Decision: **stay with Docker via OrbStack.**

1. **No incremental benefit.** Apple Containers still requires a Homebrew install — same friction as installing OrbStack.
2. **No Metal/GPU passthrough.** Apple Containers run Linux micro-VMs; Metal is macOS-only. MLX inference, SwiftUI previews, GPU workloads can't run inside any Linux container.
3. **No macOS builds from inside the container.** Xcode, Simulator, code signing, Apple frameworks require the macOS host. The SSH build bridge is needed regardless of runtime.
4. **OrbStack is more mature.** Docker Compose, robust mounts, lower memory overhead (~200MB), faster startup (0.2s vs 0.9s). Apple Containers is pre-1.0 with no Compose equivalent and incomplete memory ballooning.

Revisit if: Apple Containers hits 1.0 with Metal passthrough, or OrbStack becomes unavailable/costly. (`container/apple-containers-experiment.sh` captures the test.)

### How It Works

Container mode is the default. `claude.sh` launches Docker with:
- Workspace mounted at the **same absolute path** (host and container paths match for session continuity)
- `dotfiles/` reachable via `CLAUDE_CONFIG_DIR`
- Named volume for the Linux venv (synced from host packages)
- Credentials persisted at `~/.claude-container/credentials.json`
- `--cap-drop=ALL --security-opt=no-new-privileges`
- `CLAUDE_PLUGIN_OPTION_*` env forwarded for the sideloaded plugin

```bash
# Build the image (one-time, also done by setup.sh)
cd container && ./build.sh && cd ..

# Run
./claude.sh

# Shell access (for debugging)
./claude.sh --shell
```

## Updating

Pull the latest from upstream and rebuild the container if the Dockerfile changed:

```bash
git pull
cd container && ./build.sh && cd ..   # only if the Dockerfile changed
```

**What's safe:** all your data (`.multiplai/`, `.env`, sessions) lives in your workspace or is gitignored — updates never touch it.

## Customization

See `docs/CUSTOMIZATION.md` for adding skills, modifying hooks, and container configuration. Run `.venv/bin/python -m pytest evals/ -q` after changes to the kit's live code.

## Logging

**Kit hooks** log under `dotfiles/logs/` and `runtime/logs/` (gitignored).

**Plugin** logs under `<workspace>/.multiplai/data/logs/` — most useful is `activity.log`, a plain-language line per meaningful action (context injected and the exact files, nudges, diary written, learnings captured, catalog rebuilds). Watch it live from a second terminal:

```bash
tail -f <workspace>/.multiplai/data/logs/activity.log
```

`MULTIPLAI_DEBUG=1 claude` makes every plugin script emit DEBUG detail. See the plugin `README.md` → Observability for how to read a routing line.
