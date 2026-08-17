# multiplai-kit

> Part of the **[Multiplai suite](https://github.com/spikelab/multiplai)** — what the suite is, how the five repos fit together, and which part you need.

A distributable Claude Code kit — launcher, container, reference docs, and workspace conventions as a self-contained package. Clone it, run setup, launch via the wrapper script, and get the full system without touching your existing `~/.claude/`.

**Installing for the first time? Read [GETTING-STARTED.md](GETTING-STARTED.md) instead of this file.** It walks you from nothing to a working setup and through your first week, in order. This README is organised by subsystem and is the reference you come back to.

The skill library and the memory/context layer ship as **Claude Code plugins from the Multiplai marketplace** (`spikelab/multiplai-cc-mktplace`): the [`multiplai-context`](#the-memory-system-the-multiplai-context-plugin) plugin (memory, routing, lifecycle) plus seven themed skill packs (`multiplai-dev`, `multiplai-research`, `multiplai-writing`, `multiplai-pm`, `multiplai-media`, `multiplai-messaging`, `multiplai-apple`). `setup.sh` installs the marketplace and the context plugin; you pick the skill packs you want.

**Not sure you want the whole kit?** Just want memory on your existing Claude Code? That's one command via the plugin marketplace — no Docker, no clone. [`multiplai`](https://github.com/spikelab/multiplai) is the umbrella repo — it explains what the suite is, which part you actually need, and the adoption ladder from plain Claude Code up to this kit (the full sandboxed environment).

## Contents

[**Getting started**](GETTING-STARTED.md) · [Prerequisites](#prerequisites) · [Platforms](#platforms) · [Quick Start](#quick-start) · [How It Works](#how-it-works) · [The Memory System](#the-memory-system-the-multiplai-context-plugin) · [The Workspace Model](#the-workspace-model) · [Launcher Modes](#launcher-modes) · [Environment Configuration](#environment-configuration) · [Architecture](#architecture) · [What's Included](#whats-included) · [Container Mode](#container-mode) · [How the pieces fit together](#how-the-pieces-fit-together--and-stay-current) · [Customization](#customization) · [Logging](#logging) · [What credentials enter the container](#what-credentials-enter-the-container) · [Data & retention](#data--retention)

## Prerequisites

**Required** — `setup.sh` stops without these:
- Claude Code CLI (`npm install -g @anthropic-ai/claude-code`)
- Claude Max plan or API key (the plugin's LLM calls use the Agent SDK, with an API-key fallback)
- Python 3.12+ and uv (uv fetches its own interpreter if yours is older)
- git
- jq
- curl

**Recommended:**
- Docker / OrbStack (container mode is the default — without it, Claude runs unsandboxed on your host)
- ripgrep (`rg`) — setup warns and carries on without it
- ffmpeg (for youtube-transcript audio fallback and the transcribe skill)

**Optional (macOS only):**
- mlx-whisper (for local audio transcription via Metal GPU) — `setup.sh` attempts this automatically

## Platforms

macOS and Linux. Everything that matters — the memory loop — is identical on
both; what differs is the host-side extras, all of which are macOS-only
because they wrap macOS-only tools.

| | macOS | Linux |
|---|---|---|
| **Container runtime** | OrbStack preferred — containers resolve as `<name>.orb.local` from the host, no port publishing | Docker engine or Podman. **Not Docker Desktop for Linux** — its VM indirection breaks the loopback bridging some features assume |
| **Host bridge** | Opt-in. Lets a session run an allowlisted set of host tools: Xcode builds, browser automation, local transcription | None. Nothing on a Linux host needs reaching out for |
| **Bridge write-jail** | `setup.sh` declares your workspace to the host and installs `confine.sb`, so bridge commands cannot write outside it | N/A — no bridge to confine |
| **GitHub auth** | GitHub App (`GH_TOKEN_APP`) or a PAT | **PAT only.** `claude.sh` exits with an explanation if `GH_TOKEN_APP` is set — the App's private key lives in the macOS Keychain |
| **Credential lookup** | `FOO_KEYCHAIN` resolves any variable from the Keychain | Not available. Set the variables directly in `.env` or `env.<profile>`; the launcher warns once and continues |
| **Local transcription** | `mlx-whisper` installed at setup (Metal) | Skipped |

Windows via WSL2 runs the Linux path from inside the distribution — clone,
configure and launch there, not from PowerShell. It has had no real-world
testing yet, so treat anything you hit as worth reporting rather than as your
mistake.

Per-platform detail, and what to do when a step fails, is in
[GETTING-STARTED.md](GETTING-STARTED.md#what-runs-where).

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

First run prompts for authentication via `/login`. Credentials persist in `~/.claude-container/credentials.json` across container restarts.

You do not install Python dependencies by hand. The marketplace is a single `uv` workspace: each script directory that needs dependencies declares them in its own `pyproject.toml`, and one committed `uv.lock` at the marketplace root fixes the exact versions for all of them. Scripts run under `uv run --project <that directory>`, so `uv` installs what a script needs the first time it runs, from that lock, and reuses it after that.

## How It Works

Sets `CLAUDE_CONFIG_DIR` to the included `dotfiles/` directory before launching Claude Code. This makes Claude Code use the kit's settings, skills, reference docs, and config instead of `~/.claude/`. Your existing Claude Code config is completely untouched.

The kit is responsible for:
- **Launcher** (`claude.sh`) — container/local/shell modes, per-identity profiles (git, GitHub auth, GCP keys, image selection).
- **Container** — a sandboxed Docker/OrbStack image (fetched from [`multiplai-container`](https://github.com/spikelab/multiplai-container) at setup) that runs Claude with `--dangerously-skip-permissions` safely. [Overlay images](#custom-environments-overlay-images) build any project- or task-specific environment on top of it.
- **Reference docs** (20+ reference docs in `dotfiles/reference/dev/`, including the README index) — prescriptive engineering standards. Stack-specific ones load mechanically: the `multiplai-context` hook detects a project's stack from its manifests and points Claude at the matching docs, and buildme inlines them into spec generation. See `dotfiles/reference/dev/README.md` for the mechanisms and the renaming contract.
- **Kit config** (`multiplai.conf`) — model/effort ceilings and per-skill overrides.
- **Installing and configuring the Multiplai plugins** — the `multiplai-context` memory/lifecycle plugin and the themed skill packs (see `docs/SKILLS.md`).

## The Memory System (the `multiplai-context` plugin)

Memory, context routing, session diary, learnings, and dream consolidation are not part of this repo — they come from **`multiplai-context`**, a normal Claude Code plugin published in the marketplace repo (`spikelab/multiplai-cc-mktplace`). `setup.sh` installs it for you. The only hooks the kit registers directly are `validate-syntax.sh` (syntax validation) and `guard_destructive.py` (destructive-command guard) — so if something is off in routing, diary, or learnings, the fix belongs in the **marketplace repo**, not here.

Inside the marketplace repo:

```
multiplai-cc-mktplace/
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

## The Workspace Model

Setup creates a workspace with `INBOX/`, `PROJECTS/`, `RESOURCES/`, `ARTIFACTS/`, and the plugin's `.multiplai/` state directory. The key concept: **everything you work on is a project.**

Two of those are easy to confuse. `RESOURCES/` is research about things *outside* your workspace; `ARTIFACTS/` is the record of work you actually did — what you measured, what you tried, and any Artifact page Claude published. `INBOX/` is scratch and is gitignored, so anything that must survive has to leave it.

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
| No Docker installed | Bare mode (a supported rung, not a failure state): claude runs directly on the host with the whole filesystem in reach, permission prompts the only boundary |
| Docker installed, daemon stopped | **Error — not bare mode.** Start Docker, or ask for bare mode explicitly with `--local` |

Those last two rows look identical from the outside — `docker` does not answer
either way — and lead to deliberately different outcomes. Whether Docker is
*installed* is a durable fact about the machine; whether the daemon is *running*
is not. A machine with Docker installed has a sandbox, so a stopped daemon is a
state to fix in ten seconds, and falling back would drop you onto your real
filesystem with only permission prompts between the agent and it, because you
forgot to start Docker Desktop. The two errors name which case you are in and
give different fixes. `setup.sh` draws the same line: with the daemon down it
skips the image build and says so, rather than reporting that it set you up for
bare mode.

```bash
./claude.sh                         # container (default)
./claude.sh --profile work          # container, work git identity
./claude.sh --local                 # bare mode, host permissions
./claude.sh --shell                 # container bash shell
./claude.sh --profile work --shell  # work profile, bash shell
```

**In tmux, the tab names itself.** Launching a container session from inside tmux renames the window to the container name — `cc-p-05212125`, i.e. `cc-<profile initial>-<DDHHMMSS>` — which is the same string the fleet view (`AGENTS.md`, `/multiplai-context:fleet-status`) uses to identify the session, so a tab and a fleet row match by eye. The original name comes back when the session exits. It is the *container* name and not the Claude session id on purpose: `/clear` starts a new session id, and a tab that renamed itself mid-work would be worse than no name at all. Container mode only; without tmux, nothing happens.

**Rename the tab freely.** The launcher also stamps the container name onto the pane itself (`tmux set-option -p @cc`), so calling a tab `inbox-cleanup` changes the label without losing track of which container is in it — the fleet board picks the new name up on its next redraw. It also means the board can label a session it was not running when you started: `tmux list-panes -a -F '#{pane_id}|#{@cc}'` shows you the same thing it reads.

`claude.sh` also passes through `--plugin-dir` / `--add-dir` to the underlying `claude` invocation (and keeps them out of `bash` in `--shell` mode), plus `--strict-mcp-config` to isolate account-level MCP integrations.

`claude.sh` also ships the kit half of a session-orchestration handshake (a `driver` subcommand and an adoption take-back loop) for the multiplai native cockpit — on the roadmap, not yet released. These code paths are inert without it; full documentation lands with the release.

## Environment Configuration

The kit uses **two kinds of env files** with similar names — intentional but confusing at first glance:

| File | Committed? | Purpose | Loaded |
|---|---|---|---|
| `.env` | gitignored | **Base config** — workspace path, default git identity, GH token, container settings, **and secrets (API keys for skills)** | Always, by `claude.sh` |
| `.env.example` | committed | Template for `.env` | Manual: `cp .env.example .env` |
| `env.<profile>` (e.g. `env.work`, `env.personal`) | gitignored | **Optional override layer** — typically git identity and GH token. Does NOT replace `.env`, just overrides the fields it names. | Only when `--profile <name>` is passed |
| `env.example` | committed | Template for profile files | Manual: `cp env.example env.<name>` |

**Rule of thumb — where does a new value belong?**

| New value | Where it goes |
|---|---|
| Secret (API key, token) used by a skill | `.env` (add matching entry to `.env.example`) |
| Global config (workspace path, container settings) | `.env` |
| Per-identity value (git name/email/GH token) that changes between work/personal | `.env` (default) + `env.<profile>` (overrides) |
| Plugin option you want forwarded to the container | export `CLAUDE_PLUGIN_OPTION_<NAME>` before launch (`claude.sh` forwards it) |

**The dot matters.** `.env.example` (leading dot) is the template for the base config. `env.example` (no dot) is the template for profile overrides. They are NOT duplicates.

### How variables reach the container

Two rules, and they are the whole model:

1. **Anything you declare gets forwarded, if it has a value.** Every variable assigned in `.env` or `env.<profile>` is passed into the container when its value is non-empty. Adding a key to `.env` is sufficient — there is no list in the launcher to update. A commented-out line assigns nothing, so uncommenting it is what turns forwarding on.

   Empty counts as absent: an empty variable is *not* forwarded, because a variable that is present-but-empty inside the container beats every `${VAR:-fallback}` and `os.environ.get(VAR, default)` downstream. Leaving it out is what lets the default apply.

   The exceptions are variables that only configure the launcher (`IMAGE_NAME`, `CONTAINER_REF`, `KIT_VENV_VOLUME`, `MULTIPLAI_NET`, every `*_KEYCHAIN` name, `MULTIPLAI_MOUNT_GEMINI`, `MULTIPLAI_HUB_*`) and ones holding a **host** path that the container mounts elsewhere (`WORKSPACE`, `SSH_BUILD_KEY`, `GCP_KEY_FILE`, `CLAUDE_CREDENTIALS_FILE`, `GEMINI_CONFIG_DIR`). Those still take effect — they just arrive as the container's path, not the host's.

   `GH_TOKEN_APP` is deliberately *not* one of those exceptions: it is forwarded, because the hooks inside the container read it to know which GitHub App profile to mint against. It is a profile **name**, not a secret.

2. **Your shell wins over the files.** A variable exported before launch overrides whatever `.env` or the profile says:

   ```bash
   GH_TOKEN="$(mint-a-short-lived-token)" ./claude.sh   # the minted one is used
   GCP_KEY_FILE=~/.gcp/other.json ./claude.sh           # this key, this launch
   ```

   This is the same precedence the in-container loaders use when they read `.env` (`override=False`), so one rule holds end to end. A variable exported in your shell but named in no file is *not* swept up — the file is still where you declare intent — apart from a few that legitimately live nowhere else (`TERM`, the `GIT_*` identity fields, `GH_TOKEN`, `GH_TOKEN_APP`, `SSH_BUILD_USER`, `CLOUDSDK_CORE_PROJECT`, `ANTHROPIC_BASE_URL`, `CLAUDE_PLUGIN_OPTION_*`).

Values are handed to Docker by name, not on the command line, so secrets never appear in `ps` output.

### Creating a Profile (optional)

Profiles switch git identity and GitHub token for different contexts (personal vs work). They layer on top of `.env`:

```bash
cp env.example env.work
# Edit env.work: set GIT_AUTHOR_NAME, GIT_AUTHOR_EMAIL, GH_TOKEN_KEYCHAIN

./claude.sh --profile work
```

What a profile typically overrides:
- `GIT_AUTHOR_NAME` / `GIT_AUTHOR_EMAIL`, `GIT_COMMITTER_NAME` / `GIT_COMMITTER_EMAIL`
- `GH_TOKEN_KEYCHAIN` — macOS Keychain key for the GitHub token. One instance of the general rule: **`FOO_KEYCHAIN=<item>` looks `<item>` up in the login Keychain and exports the result as `FOO`**, for any variable, so a per-identity secret can live in the Keychain instead of the profile file. An explicitly set `FOO` wins; `FOO_KEYCHAIN` itself is never forwarded (it names an item the container cannot reach). See [`docs/PROFILES.md`](docs/PROFILES.md)
- `CLAUDE_CREDENTIALS_FILE` — separate Claude OAuth credentials file per profile
- `GEMINI_CONFIG_DIR` — optional separate Gemini CLI config dir (only mounted when `MULTIPLAI_MOUNT_GEMINI=1`; see [What credentials enter the container](#what-credentials-enter-the-container))
- `GCP_KEY_FILE` / `CLOUDSDK_CORE_PROJECT` — when a client's cloud credentials should follow their identity rather than apply to every launch

Any variable is allowed in a profile; those are just the ones that usually differ per identity.

Without `--profile`, only `.env` is loaded. For a full walkthrough — Keychain setup, separate Claude login, a worked example — see [`docs/PROFILES.md`](docs/PROFILES.md).

### Custom environments (overlay images)

Because sessions run in Docker images, "give Claude a different environment"
is just "launch a different image". An **overlay image** is the base container
plus whatever a project or task needs — a database server, a cloud CLI, a
locale, build headers — defined by a small Dockerfile kept in that project's
own repo and versioned with the code that needs it.

Register overlays once in `overlays.conf` at the kit root
(`cp overlays.conf.example overlays.conf`):

```
# name:path — built as claude-multiplai-<name>:local
myproject:PROJECTS/myproject/claude-overlay
```

`./setup.sh` then rebuilds the base **and** every registered overlay on every
run — unchanged entries are Docker-cache no-ops, so this costs seconds. Select
per launch via a profile:

```bash
# env.myproject
IMAGE_NAME="claude-multiplai-myproject:local"

./claude.sh --profile myproject
```

The launcher warns at launch if an overlay was left behind on an older base
(e.g. its build failed during setup). The overlay Dockerfile contract and
worked examples are in the
[multiplai-container README](https://github.com/spikelab/multiplai-container#overlay-images--build-any-environment-for-claude-code).

### How Skills Access Secrets

Skills that need secrets (e.g. `deep-research` uses `TAVILY_API_KEY`, `EXA_API_KEY`; optionally `BRAVE_API_KEY`, `SERPER_API_KEY`) load them from `.env` automatically via `python-dotenv`. No per-skill config files. Add the key to `.env` (and document it in `.env.example`) and the skill picks it up on next launch. Shell-exported env vars take precedence over `.env` values:

```bash
TAVILY_API_KEY=override-key ./claude.sh
```

> **`SLACK_TOKEN` and the `GMAIL_*` trio deserve a moment's thought** before you
> add them: they can post and send mail as you, and every session gets them,
> including sessions doing unrelated work. Putting them in `.env` *is* the
> decision to hand them over — see
> [What credentials enter the container](#what-credentials-enter-the-container).

## Architecture

```
multiplai-kit/                          # = the "runtime" / kit repo
├── claude.sh              # Single entrypoint (container default, --local, --shell, --profile)
├── setup.sh               # One-time: prerequisite checks, workspace, memory templates, Docker build
├── multiplai.conf         # Kit config (model/effort ceilings, per-skill overrides) — project root, NOT in dotfiles/
├── requirements.txt       # Kit venv deps
├── .env.example           # Base config template (becomes .env — workspace, secrets)
├── env.example            # Profile template (becomes env.<name> — per-identity overrides)
├── overlays.conf.example  # Overlay image registry template (becomes overlays.conf — name:path per line)
│
├── dotfiles/              # = CLAUDE_CONFIG_DIR (Claude Code reads everything from here)
│   ├── CLAUDE.md          # Global instructions (personalized by setup.sh)
│   ├── settings.json      # Registers validate-syntax + guard_destructive hooks; pluginConfigs["multiplai-context@multiplai"]; statusline; permissions
│   ├── hooks/             # validate-syntax.sh, guard_destructive.py, run-hook-python, model_resolver.py, log_utils.py
│   ├── skills/            # Your own local skills (the skill library ships as marketplace plugins)
│   ├── reference/dev/     # 20+ best-practice docs, incl. the README index
│   ├── scripts/           # statusline.sh, file-suggestion.sh
│   ├── templates/         # Project templates
│   ├── plugins/           # Claude Code plugin state (marketplaces, cache) — incl. the loaded plugin
│   └── logs/              # Hook logs (validate-syntax, errors)
│
├── runtime/
│   └── logs/              # Component logs (deep-research, build-pipeline, …)
│
├── evals/                 # Unit tests for the kit's own live code (project root, NOT in dotfiles/)
├── container/             # Dockerfile, build.sh, venv-sync-entrypoint.sh, apple-containers-experiment.sh
├── scripts/               # claude-wrapped (session launcher helper)
├── workspace-scaffold/    # Templates for a new workspace (CLAUDE.md.template, memory/)
│
├── docs/                  # SKILLS.md, HOOKS.md, CUSTOMIZATION.md, PROFILES.md
│
└── (installed from the marketplace)
    multiplai-cc-mktplace → plugins/multiplai-context/   # the memory/context/learning plugin
```

## What's Included

### Hooks (in-tree)

The kit registers exactly two runtime hooks in `settings.json`; everything else in `dotfiles/hooks/` is a live helper:

| File | Role |
|------|------|
| `validate-syntax.sh` | PostToolUse (Write\|Edit) — validates YAML/JSON syntax. |
| `guard_destructive.py` | PreToolUse (Bash) — denies a curated set of unrecoverable commands. Sessions run with permissions bypassed (the container is the sandbox), so this is the one layer that can still say no. |
| `run-hook-python` | Wrapper that routes Python hook scripts to the kit venv |
| `model_resolver.py` | Model-ceiling logic (caps a requested tier via `MULTIPLAI_MODEL`) |
| `log_utils.py` | Shared logging helper used via PYTHONPATH by plugin skills (buildme, deep-research) |

Memory routing, diary, learnings extraction, and the autodream gate now live in the **`multiplai-context` plugin**, not here. The old in-tree hooks and catalog generators have been removed along with the tests that targeted them.

### Skills (themed marketplace packs)

The skill library ships as seven themed plugins from the Multiplai marketplace — `multiplai-pm`, `multiplai-writing`, `multiplai-research`, `multiplai-dev`, `multiplai-media`, `multiplai-messaging`, `multiplai-apple` (macOS only) — install the ones you want. See `docs/SKILLS.md` for the pack index. `dotfiles/skills/` stays available for your own local skills. The `multiplai-context` plugin adds its namespaced commands under `/multiplai-context:*` (below).

### Memory, Context & Learning (provided by the plugin)

All of the following is the **`multiplai-context` plugin** — summarized here; see its `README.md` for the authoritative version.

**Per-prompt context routing.** A `UserPromptSubmit` hook routes every prompt against indexed catalogs (memory, and optionally skills/resources) and injects only what's relevant — no memory dump. Two routing strategies:
| | `token_overlap` (default) | `llm` |
|---|---|---|
| How | Offline keyword overlap | One Haiku call per prompt (`router_model`) |
| Added latency | None | **~2.9 s** median |
| Cost | None | **~$0.035/prompt** API-equivalent |
| Accuracy (F1) | **20.0** | **48.6** |

`llm` is **2.4× more accurate** and injects fewer bytes — both from one backtest of 300 real prompts drawn from 273 chats over 21 days, scored against a hindsight oracle. It is a real steady-state option, not an experiment: extended thinking is disabled on the routing call, which took the median from 18.4 s to 2.9 s and is what makes it viable inside a blocking hook.

The default stays `token_overlap` because it is free and because a new install's memory is mostly templates — there is little for a smarter router to be smarter about yet. **Switch to `llm` once your memory is real and you notice the wrong files being injected.** Cost sizing against your own volume is in [GETTING-STARTED.md → Choosing a memory router](GETTING-STARTED.md#choosing-a-memory-router).

**Re-recommendation cooldown.** After a file is injected, it's suppressed from re-injection for `recommend_cooldown_turns` turns (default 4) — it's already in the conversation. The `PreCompact` hook clears the map after compaction (the content was summarized away), so a longer cooldown can never starve the model.

**Catalogs.** Memory/skills/resources catalogs are generated and cached by the plugin under `.multiplai/data/` (regenerate with `/multiplai-context:refresh-catalogs`). The kit no longer carries its own catalog generators.

### Session Lifecycle (plugin hooks)

| Event | Plugin script | Role |
|-------|---------------|------|
| `SessionStart` | `session_start.py` | Init session state; drain deferred extractions; emit dream-due nudge |
| `UserPromptSubmit` | `context_manager.py` | Route the prompt and inject relevant memory |
| `Stop` | `session_stop.py` | Lightweight checkpoint; handoff advice at the threshold |
| `UserPromptSubmit` | `checkpoint_nudge.py` | Handoff notice to Claude; enforces `checkpoint_hard_stop_tokens` |
| `SessionEnd` | `session_end.py` | Write a deferred-extraction marker for a drain to pick up |
| `PreCompact` | `pre_compact.py` | Enqueue a deferred-extraction marker; clear the cooldown map |

### Context: the kit hands off, it does not compact

**Shipped default:** native auto-compaction is **off** (`DISABLE_AUTO_COMPACT=1`
plus `autoCompactEnabled: false` in `dotfiles/settings.json`). This is a
deliberate reversal of the kit's earlier default, which steered compaction to
fire early via `CLAUDE_CODE_AUTO_COMPACT_WINDOW` / `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE`.

Compaction replaces your conversation with a summary of it. That is strictly
lossy, it costs a long visible pause and a full summarization call every time,
and quality degrades further with each cycle — the plugin's checkpoint system
already keeps a structured record of the session's real working state, so the
summary is buying redundancy at a price. The kit's answer is to **hand off**
instead: keep the checkpoint fresh, then start a clean window that gets seeded
from it.

The loop you'll actually see:

1. The plugin checkpoints in the background as the session grows (100K, 200K,
   then every 25K).
2. At 200K it tells you a handoff is due.
3. At 250K (`checkpoint_hard_stop_tokens`, shipped default) it stops accepting
   new prompts until you act. Slash commands still work — that's the door.
4. You run `/clear`. The next `SessionStart` consumes the pending marker and
   injects the checkpoint, so the fresh window opens knowing the task tree,
   next action, involved files, and decisions.

Manual `/compact` is untouched and still works if you'd rather stay in one
session — the checkpoint is re-injected afterwards either way.

**To go back to steered compaction** (fully unattended, no keystroke at the
threshold, at the cost of summarized context), drop the two disable settings
and restore the steering pair:

```json
{ "env": {
    "CLAUDE_CODE_AUTO_COMPACT_WINDOW": "300000",
    "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE": "80"
} }
```

The plugin detects which mode you're in and adjusts: under steering it stays
quiet and lets `SessionStart(source="compact")` do the rebuild; with compaction
disabled it resumes the handoff advice. Set `checkpoint_hard_stop_tokens` to
`0` if you want the handoff advisory rather than enforced. Requires
`multiplai-context` 0.32.0+.

⚠️ **`CLAUDE_CODE_AUTO_COMPACT_WINDOW` is not a context limit.** It only feeds
the compaction trigger — per the CLI's own help text, the real threshold is the
minimum of that setting and the model's context window. With auto-compaction
disabled it does nothing at all, which is why it is not in the shipped defaults
any more: a session runs to the model's actual ceiling regardless of what that
number says.

Heavy LLM extraction never runs inside a kill-within-seconds hook — it's deferred via a marker queue (`data/pending_extractions/`) and run by `extract_learnings.py` as a detached subprocess.

Two things drain that queue, through the same code so they cannot drift apart: the next `SessionStart` in any project, and — since the queue would otherwise sit untouched from the moment you close your last tab until you open the next one — `claude.sh`, which launches a disposable, detached drain container (same image as the session, with `drain_extractions.py` as its process) right after a **container-mode** session exits. The host never executes plugin code itself — it only checks whether markers exist and starts the container; script resolution happens inside. The launcher half needs `multiplai-context` 0.11.0+; without it — or for `--local`/bare sessions and hub driver containers, which never return to the launcher — you get the old session-start-only behaviour.

### How It Learns

```
Session conversation
    ↓
SessionEnd / PreCompact writes a marker  (instant — no LLM in the hook)
    ↓
a drain spawns extract_learnings.py (detached) → diary + learnings
  · claude.sh, via a disposable drain container, once the session
    container exits — same evening
  · or the next SessionStart, if the launcher couldn't (older plugin,
    or a --local / bare / driver session that never returns to it)
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

Set via `settings.json → pluginConfigs["multiplai-context@multiplai"].options` (and/or forwarded `CLAUDE_PLUGIN_OPTION_*` env vars). `setup.sh` writes the three path options there for you, and reads them back before claiming success.

`settings.json` is tracked, so a configured checkout has a permanently dirty
worktree. That is unavoidable — it is the only settings file Claude Code reads
at user scope — and it is why updating a runtime is
`git stash push dotfiles/settings.json && git pull --rebase && git stash pop`,
or a local `chore(runtime)` commit you rebase each time. Do **not** move these
options to `settings.local.json`: at user scope nothing reads that file, so the
config silently stops applying.

The options you'll actually touch:

| Option | Default | Purpose |
|--------|---------|---------|
| `workspace_dir` | `""` | Anchor for all state — memory/diary/now/learnings default under `<workspace_dir>/.multiplai/` |
| `memory_router` | `token_overlap` | Routing strategy: `token_overlap` (offline, fast) or `llm` (one model call/prompt) |
| `router_model` | `claude-haiku-4-5` | Model for the `llm` router (ignored under `token_overlap`) |
| `recommend_cooldown_turns` | `4` | Turns to suppress re-injecting a just-injected file (`0` disables) |
| `catalog_model` | `claude-sonnet-4-6` | Model for LLM catalog generation |
| `enable_skills` / `skills_dir` | `false` / `~/.claude/skills` | Optionally catalog skills for routing (the kit points `skills_dir` at `dotfiles/skills`) |
| `enable_resources` / `resources_dir` | `false` / `""` | Optionally retrieve a research/reference corpus per prompt, through a qmd index you build on the host. Not a one-command feature yet — leave off unless you want to run `setup_qmd.sh`. |
| `checkpoint_hard_stop_tokens` | `250000` (kit default; `0` upstream) | Stop accepting new prompts above this many context tokens until you hand off. `0` makes the handoff advisory. See [Context: the kit hands off](#context-the-kit-hands-off-it-does-not-compact) |
| `anthropic_api_key` | _(sensitive)_ | API-key fallback when the Agent SDK is unavailable |

### Kit Configuration (`multiplai.conf`)

Separate from the plugin. `multiplai.conf` (project root, **not** in `dotfiles/`) sets model/effort ceilings and per-skill overrides for the **in-tree skills**. Changes take effect on next invocation.

| Setting | Default | Purpose |
|---------|---------|---------|
| `MULTIPLAI_DEBUG` | `false` | Verbose logging |
| `MULTIPLAI_MODEL` | `claude-opus-4-6` | Model ceiling — caps the tier a skill/hook can request (`haiku < sonnet < opus`) |
| `MULTIPLAI_EFFORT` | `high` | Effort ceiling (`low < medium < high < max`) |
| `MULTIPLAI_LOG_LEVEL` | `INFO` | Component log verbosity |
| `MULTIPLAI_LOG_RETENTION_DAYS` | `90` | Rotated-log retention in days — shipped default 90; `0` means keep forever (see [Data & retention](#data--retention)) |

These ceilings apply to hooks and to the buildme / deep-research SDK pipelines. They do **not** configure Claude Code skills — a skill's model and effort come from its `SKILL.md` frontmatter and nothing else. Retune a skill by editing its frontmatter in the `multiplai-cc-mktplace` repo.

### Eval Suite

Unit tests at `evals/` (project root) covering the kit's **own live code** — the model-ceiling resolver and `multiplai.conf` loading. Free, fast, no API key.

```bash
.venv/bin/python -m pytest evals/ -q
```

The memory/routing/learnings mechanisms (and their tests) moved to the **`multiplai-context` plugin** in the marketplace repo (`multiplai-cc-mktplace`), which has its own `tests/` suite under `plugins/multiplai-context/`.

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

`container/` is a **pinned checkout** managed by `setup.sh` (see [How the
pieces fit together](#how-the-pieces-fit-together--and-stay-current)) — to
*update* the container, `git pull && ./setup.sh`, not the manual build below.

```bash
# Manually rebuild the current pinned image (setup.sh does this for you)
cd container && ./build.sh && cd ..

# Run
./claude.sh

# Shell access (for debugging)
./claude.sh --shell
```

The image the launcher starts is not fixed: [overlay
images](#custom-environments-overlay-images) let each project or task have its
own environment on top of the base, selected per launch with `IMAGE_NAME` in a
profile.

## How the pieces fit together — and stay current

The system is **three independently-versioned parts**. Knowing which is which
tells you how each updates:

| Part | Source | Pinned by | You update it with |
|------|--------|-----------|--------------------|
| **Kit** — launcher, `setup.sh`, `dotfiles/`, reference docs, and the container pin | this repo (`multiplai-kit`) | your local clone's `main` | `git pull` |
| **Container** — the Docker image + host SSH gateway | `multiplai-container`, fetched into `container/` | an **immutable tag**, `CONTAINER_REF` in `setup.sh` | `./setup.sh` (re-pins + rebuilds) |
| **Plugins** — `multiplai-context` + the themed skill packs | marketplace (`multiplai-cc-mktplace`) | plugin versions in the marketplace | the `/plugin` menu |

They version independently on purpose: a container rebuild, a kit config
change, and a plugin skill fix are separate concerns on their own cadence.

### The one-liner (kit + container)

```bash
git pull && ./setup.sh
```

`git pull` advances the **kit** — including the `CONTAINER_REF` pin, if a new
container release bumped it. `./setup.sh` then re-aligns `container/` to that
pin, rebuilds the image, and reinstalls the host gateway. It also prints a
**NOTE** when a newer container tag exists than you're pinned to.

**What's safe:** your data (`.multiplai/`, `.env`, sessions, memory) lives in
your workspace or is gitignored — updates never touch it.

### How the container stays current (the tag-pin model)

The container is **not** tracked from `main`. `setup.sh` fetches it at an
**immutable tag** (`CONTAINER_REF`, e.g. `v0.4`) into a shallow `container/`
checkout — giving every install a reproducible, known-good image and shielding
it from in-flight `main` changes. The delivery chain, end to end:

1. A fix merges to `multiplai-container` `main`. **This alone changes nothing
   for you** — the runtime consumes tags, not `main`.
2. A maintainer runs `multiplai-container/release.sh`: build-gated, it cuts a
   new tag **and** bumps `CONTAINER_REF` here in the kit.
3. You `git pull` the kit → your pin advances.
4. You `./setup.sh` → `container/` is re-checked-out to the new tag, the image
   rebuilds, and `~/.local/bin/container-build-gateway.sh` (the host SSH
   gateway the bridge invokes) is reinstalled from it, along with the
   `~/.local/state/multiplai/confine.sb` sandbox profile it applies. A tag that
   predates the profile installs no profile; setup.sh says so rather than
   skipping in silence.

> **Never hand-edit `container/`.** It's a pinned, detached-HEAD checkout that
> `setup.sh` re-aligns to `CONTAINER_REF` — a manual edit is transient (reverted
> the next time the pin advances and `setup.sh` re-checks out `container/`) and
> invisible to everyone else. To change
> container tooling, PR `multiplai-container` and cut a release.

Pin an exact version or roll back by setting `CONTAINER_REF` in `.env` (e.g.
`CONTAINER_REF=v0.4`); it overrides the kit default.

### Updating the plugins

The memory/context plugin and skill packs come from the marketplace and update
separately from the kit. Run `/plugin`, refresh the marketplace
(`multiplai-cc-mktplace`), then update the installed plugins from the menu.
Because `CLAUDE_CONFIG_DIR` points at the kit's `dotfiles/`, updates land in
`dotfiles/plugins/` — nothing touches `~/.claude/`.

## Customization

See `docs/CUSTOMIZATION.md` for adding skills, modifying hooks, and container configuration. Run `.venv/bin/python -m pytest evals/ -q` after changes to the kit's live code.

## Logging

**Kit hooks** log under `dotfiles/logs/` and `runtime/logs/` (gitignored).

**Plugin** logs under `<workspace>/.multiplai/data/logs/` — most useful is `activity.log`, a plain-language line per meaningful action (context injected and the exact files, nudges, diary written, learnings captured, catalog rebuilds). Watch it live from a second terminal:

```bash
tail -f <workspace>/.multiplai/data/logs/activity.log
```

`MULTIPLAI_DEBUG=1 claude` makes every plugin script emit DEBUG detail. See the plugin `README.md` → Observability for how to read a routing line.

## What credentials enter the container

Sessions run with tool permissions bypassed — the container is the sandbox, so
anything mounted or forwarded into it is reachable by the agent, and by any
prompt injection that lands in a page it fetches. This is the complete list, so
you can decide what to hand over before you hand it over rather than after.

| Credential | How it enters | Default | Blast radius |
|---|---|---|---|
| Claude credentials | mount → `.credentials.json` | **always** | Your Claude subscription. Required — this is the product. |
| `GH_TOKEN` | `-e` from `.env` or macOS Keychain | when set | Whatever the token is scoped to. Use a **fine-grained** token limited to the repos you work on; a classic `repo` token exposes every repo your account can reach. Better still on macOS with the host bridge: `GH_TOKEN_APP=<app>` mints a fresh ~1-hour **GitHub App installation token** per session and renews it in place — the App's private key never enters the container, and no long-lived token exists to leak. The two are mutually exclusive; declaring both in config is a launch error. |
| SSH agent socket | mount → `/ssh-agent.sock` | when `SSH_AUTH_SOCK` set | Every key in your agent, usable for the container's lifetime (keys aren't copied, but signing requests are honoured). `ssh-add -D` before an autonomous run if that matters. |
| SSH build key | mount `:ro` | when `SSH_BUILD_KEY` set | The host bridge account. Deny-by-default on the host side (`container-build-gateway.sh`): argv is checked against a fixed allowlist, and path-taking commands additionally run under a `sandbox-exec` profile confined to the workspace `setup.sh` declared in `~/.local/state/multiplai/workspace`. That profile denies **writes** outside the workspace; it does not restrict reads, network, or process execution, so a bridge command can still read anything on the Mac your account can. |
| Search API keys | `-e` from `.env` | when set | Metered spend on Tavily/Exa/Brave/Serper. |
| `SLACK_TOKEN` | `-e` | when set | Posting as you in your workspace. |
| `GMAIL_*` trio | `-e` | when set | Reading and sending as your account. |
| Any other var in `.env` / `env.<profile>` | `-e` | when non-empty | Whatever that credential is for. You declared it; it is forwarded. |
| `~/.gemini/` | mount **rw**, **opt-in** | off | OAuth refresh tokens + `history/` of past prompts. Requires `MULTIPLAI_MOUNT_GEMINI=1`. |
| GCP service-account key | mount `:ro` | when `GCP_KEY_FILE` set | Whatever the service account can do. |
| Workspace | mount **rw** | **always** | Your files. This is the point of the tool. |

**`.env` is the boundary, not the forwarding list.** Earlier versions gated the
messaging tokens behind an allowlist. That gate has been removed, because it
never bought what it appeared to: `.env` lives on the bind-mounted kit root, and
the skills read it from there directly, so a session that can read files can
obtain any credential in it whether or not the launcher forwarded it as an
environment variable. Keeping the gate meant maintaining a control that a
one-line `Read` defeats, while implying a confinement that did not exist.

So the honest rule is the simple one: **a credential in `.env` is a credential
you have handed to every session.** Narrow by not putting it there — keep a
second `.env` for the launches that need Slack or Gmail, or export the token for
just that launch (`SLACK_TOKEN=xoxp-… ./claude.sh`) instead of storing it.

**What never happens:** the kit has no telemetry and phones nothing home. No
credential is written into the image, into git, or into any log.

### Network egress

`MULTIPLAI_NET` (in `.env`, or exported for one launch) selects how much of the
internet the container can reach. Today `unrestricted` is the default and the
only implemented value: normal Docker networking, any host reachable.

`restricted` — an internal network with no route out plus a proxy sidecar
holding a hostname allowlist (Anthropic API, GitHub, PyPI, npm, and your own
additions) — is planned but **not built yet**, and asking for it exits with an
error. That is deliberate: silently falling back to unrestricted would leave you
believing egress was filtered when it wasn't, which is worse than not having the
feature.

## Data & retention

The kit keeps everything it records on your own disk — there is no telemetry and
nothing is sent anywhere. But "local" is not the same as "ephemeral": these
files hold prompt text, tool output and full session transcripts, and by default
some of them were kept forever. Here is the complete surface and how long each
part lives.

| Surface | What's in it | Retention |
|---|---|---|
| `runtime/logs/*-YYYY-MM-DD.log` | Rotated hook/skill logs — routing decisions, prompt excerpts, errors | `MULTIPLAI_LOG_RETENTION_DAYS` (default **90**) |
| `runtime/logs/hook-errors.log` | Shared error sink, append-only | Size-capped at ~100 KB, not by date |
| `<workspace>/.multiplai/data/logs/` | Plugin logs, incl. `activity.log` | Same setting (the plugin reads it too) |
| `<workspace>/.multiplai/cc-state/projects/<slug>/*.jsonl` | **Claude Code's own session transcripts** — the full text of every message and tool result, including per-request token usage | `cleanupPeriodDays` in `dotfiles/settings.json` (default **365**) |
| `<workspace>/.multiplai/{memory,diary,learnings}/` | The knowledge corpus you deliberately accumulate | Never auto-deleted — it's the point of the system |

**`MULTIPLAI_LOG_RETENTION_DAYS`** (in `multiplai.conf`) sets how many days
rotated log files survive. Enforcement runs once per process on the first
`setup_logging()` call, so old files disappear as sessions run — no cron, no
daemon. `0` means keep forever; set it only if you actually want a permanent
archive.

**`cleanupPeriodDays`** (in `dotfiles/settings.json`) is a *Claude Code* setting,
not a kit one, and it governs the largest and most sensitive surface: the raw
session transcripts under `.multiplai/cc-state/`. These are verbatim — anything
you pasted into a session is in there. The kit ships 365 because the cost and
usage reporting reads these files; lower it if you'd rather keep less. That
directory is gitignored by `setup.sh`, so it never reaches a remote.

If you're handing this kit to someone else, or running it against a shared
workspace, review both numbers before the first run rather than after.
