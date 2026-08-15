# multiplai-kit — Developer Guide

This is the distributable Claude Code kit. See `README.md` for what it is and how users install/run it. This file covers how to **develop** the kit itself.

## Project Structure

This is a standalone git repo with its own `.git/`. There is a single working tree — develop directly in it.

**Key distinction:** `dotfiles/CLAUDE.md` is the user-facing global instructions that ship with the kit. This file (`CLAUDE.md` at project root) is for developing the kit.

**Architecture note — the memory system is now a plugin.** The context-routing, diary, and learnings-extraction hooks that used to live in `dotfiles/hooks/` have been extracted into a standalone Claude Code plugin, **`multiplai-context`**, published in the marketplace repo (`spikelab/multiplai-cc-mktplace`, under `plugins/multiplai-context/`). Those hooks were removed from this kit entirely — there is no `_retired/` directory. This kit now only ships the launcher, container, in-tree skills, reference docs, kit config, and two runtime hooks (`validate-syntax`, `guard_destructive`) — and it installs the plugin from the marketplace. See `README.md` → "The Memory System (the `multiplai-context` plugin)". When the bug is in routing/diary/learnings, fix it in the **marketplace repo**, not here.

## Git

- Single working tree, single `main` branch. Develop here; commit and push as usual.
- Personal data (`.multiplai/`, `.env`, `env.<profile>`) is gitignored and never enters the repo.
- **Any user-visible change needs a `CHANGELOG.md` entry under `## [Unreleased]`**
  ([Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format,
  Added/Changed/Deprecated/Removed/Fixed/Security). "User-visible" means a user
  who runs `git pull && ./setup.sh` would notice: launcher flags, `setup.sh`
  behaviour, shipped defaults in `multiplai.conf` / `dotfiles/settings.json`,
  container pin bumps, and documented behaviour. Internal refactors and test-only
  changes don't need one. The repo has no tags — `main` is what users consume, so
  the changelog is the only way they can tell what they got.

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
| `env.<profile>` | **no** (gitignored) | Optional per-profile overlay (e.g. `env.work`, `env.personal`). Usually git identity + `GH_TOKEN_KEYCHAIN`, but any variable is allowed. Loaded by `claude.sh --profile <name>` AFTER `.env`, so overrides the fields it names. |
| `env.example` | **yes** | Template for profile files. Minimal — only the fields a profile is allowed to override. |

**Decision tree when adding a new env var:**

1. **Is it a secret or global config?** → `.env` (and mirror in `.env.example`)
2. **Is it a per-identity value that differs work vs personal?** → `.env` for the default, allowed in `env.<profile>` for overrides. Mirror in `env.example` if it's a new field profiles should support.
3. **Is it a skill-specific secret?** → `.env`. All skills load secrets from `.env` via `python-dotenv` (see the deep-research skill's `research_pipeline/env.py` in the `multiplai-research` plugin for the pattern: `$CLAUDE_MULTIPLAI_HOME/.env` first, then walk up from the script location).

**What NOT to do:**

- Don't create a new `.env.*` file for a specific skill. One `.env` at the project root, shared by all skills.
- Prefer `.env` for secrets, so they apply regardless of which profile is active. A profile *may* carry one (e.g. a client's `GCP_KEY_FILE`) when it genuinely belongs to that identity — profiles are no longer git-identity-only.
- Don't forget to update `.env.example` when you add a field to `.env`. The example file is the only thing new users see to know what keys are needed.
- **Don't add an `-e` line to `claude.sh` for a new variable.** Forwarding is dynamic — declaring it in `.env` is the whole job. Editing the launcher is only for changing the *rules* (the keep-list or the denylist).

**Shell env wins over `.env`.** All loaders use `override=False` semantics, and
since the dynamic-forwarding refactor `claude.sh` itself honours the same rule
(it used to be the one place that didn't). So `TAVILY_API_KEY=x python -m
research_pipeline ...` and `GH_TOKEN=$(mint) ./claude.sh` both override the file
for that single invocation.

**`claude.sh` launch flow:**

```
./claude.sh --profile personal
  ↓
1. source .env                    # WORKSPACE, default git, TAVILY_API_KEY, etc.
2. source env.personal            # overrides GIT_AUTHOR_NAME/EMAIL/GH_TOKEN_KEYCHAIN
3. restore anything exported in the launching shell  # shell wins over both files
4. start container, forwarding every var declared in (1)/(2) whose value is
   non-empty, minus a launcher-only denylist; by NAME, so no secret hits argv
5. inside container, skills call load_env() which re-reads .env
   (but override=False, so the values from steps 1-3 win)
```

The forwarding contract lives in one block in `claude.sh` (`_ENV_KEEP` /
`_ENV_DENY` under "Environment forwarding"). Two invariants to preserve if you
touch it: an **empty** value is never forwarded (a present-but-empty var in the
container defeats every `${VAR:-default}` downstream — this is what broke a
setup that minted `GH_TOKEN` in-container), and values are passed as `-e NAME`
without `=value` so they never appear in `ps`.

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

Evals live at `evals/` (project root, not inside dotfiles/) and cover the kit's **own live code** only — model-ceiling resolver and `multiplai.conf` loading. Free, fast, no API key. See `evals/README.md`.

```bash
# From the repo root
.venv/bin/python -m pytest evals/ -q
```

| File | Covers |
|------|--------|
| `evals/unit/test_model_resolver.py` | Model-ceiling logic (`dotfiles/hooks/model_resolver.py`) |
| `evals/unit/test_config_loading.py` | `multiplai.conf` parsing |
| `evals/unit/test_claude_sh_env.py` | `claude.sh` env forwarding + GitHub auth-mode selection (stub `docker`) |
| `evals/unit/test_claude_sh_crossplatform.py` | The `--add-host host.docker.internal:host-gateway` alias on **both** container argv compositions — the interactive `docker run` and the hub driver's, which is a separate call site reached only via the `driver` subcommand — plus GitHub-warning silence when nothing is configured, the two distinct Keychain-unavailable messages (non-Mac vs a Mac with `security` off `PATH`), and the explicit-only Keychain probe — `security` never runs unless `GH_TOKEN_KEYCHAIN` names an item (stub `docker` + stub `security` + stub `uname`) |
| `evals/unit/test_guard_destructive.py` | PreToolUse destructive-command guard |
| `evals/unit/test_guard_hook_wiring.py` | Whether the guard is reached at all (hook wiring, log-dir creation, fail-closed wrapper) |
| `evals/unit/test_log_retention.py` | Log rotation/retention helper |
| `evals/unit/test_gh_app_hooks.py` | GitHub App SessionStart/PreToolUse hooks (stub `gh-tok` + stub `gh`) |
| `evals/unit/test_claude_sh_roster.py` | The live-container roster `claude.sh` writes for the fleet view (stub `docker`) |
| `evals/unit/test_claude_sh_tmux.py` | tmux window naming — the container name, restored on exit, and never taken from a tab the user named (stub `tmux`) |
| `evals/unit/test_claude_sh_panes.py` | The launcher's half of the pane map — the `@cc` pane stamp, the two call points, and that none of it can cost a session (stub `tmux` + stub `docker`, real `fleet-panes.sh`) |
| `evals/unit/test_fleet_panes.py` | `dotfiles/scripts/fleet-panes.sh` — the pane→container join itself: what makes a pane an agent, the `docker ps` bound, the label rules, another tmux server's entries, and total silence on every path. Plus `TestOnARealTmuxServer`, which pins what a stub cannot — that `set-option -p` round-trips through `#{@cc}`, survives a rename, and that `#{automatic-rename}` renders as `0`/`1` |
| `evals/unit/test_fleet_viewed.py` | `dotfiles/scripts/fleet-viewed.sh` — the per-pane "viewed" marker, its silence on every failure path, and its 7-day prune (stub `tmux`) |
| `evals/unit/test_fleet_render.py` | `dotfiles/scripts/fleet-render.py` — line/width budget, column alignment across markers of different display widths, the summary growing with the terminal, tail-follows-the-list, ordering, overflow, staleness, not-collected-vs-none, sanitization, the live tab-name re-join (including the tmux-socket check that refuses a marker from another server), and the stdlib-only host boundary |
| `evals/unit/test_fleet_watch.py` | `dotfiles/scripts/fleet-watch` — the board in a terminal: workspace resolution, loud failure (the one fleet script a person reads), full-window sizing, draw-once off a tty, and the redraw loop itself on a real pty via `pty.fork` — keystroke-quits, no spin at `interval 0`, cursor restored on `SIGHUP`, and that the size is measured from the tty rather than from a fallback constant (stub renderer). Also the per-frame pane-map refresh, which is the one thing this script does *silently* (stub `fleet-panes.sh`) |

**The memory / routing / learnings evals are gone** — they tested the retired in-tree hooks and were removed with them. Those mechanisms now live in the `multiplai-context` plugin, which has its own `tests/` (run from the plugin dir). Threshold for the kit tests: 100% (any failure is a bug).

## Editing Hooks

**The memory/lifecycle hooks moved to the plugin.** Routing (`context_manager.py`), session lifecycle (`session_start.py`, `session_stop.py`, `session_end.py`, `pre_compact.py`), and learnings extraction (`extract_learnings.py`) now live in the marketplace repo (`multiplai-cc-mktplace`) under `plugins/multiplai-context/scripts/`, registered in that plugin's `hooks/hooks.json`. Edit and test them there.

What's left in this kit's `dotfiles/hooks/` and registered in `dotfiles/settings.json` is **`validate-syntax.sh`** (PostToolUse on Write|Edit), **`guard_destructive.py`** (PreToolUse on Bash), and the two GitHub App hooks — **`gh-app-auth.sh`** (SessionStart) and **`gh-app-refresh.sh`** (PreToolUse on Bash). Everything else in `dotfiles/hooks/` is a live helper: `run-hook-python`, `model_resolver.py`, `log_utils.py`, `gh-tok`.

**The GitHub App hooks.** Both exit 0 on their first line unless `GH_TOKEN_APP` is set, so PAT-mode users pay one test. `gh-app-auth.sh` mints via `gh-tok` and stores the token in gh's own credential store (a *file*, which is the point — the Bash tool starts a fresh shell per call, so an exported variable is gone by the next one). `gh-app-refresh.sh` runs before **every** Bash call, so its guard is a handful of shell builtins reading bare-integer sidecars against `$EPOCHSECONDS` — no `jq`, no `date`, no subshell. Keep it that way; `evals/unit/test_gh_app_hooks.py` fails if a fork creeps into the hot path. A failed mint writes a 60-second backoff marker (`<app>.json.fail`) that the guard honours — without it, a dead bridge stalls every Bash call on the SSH connect timeout. `gh-tok` is the shared minting primitive: it runs `multiplai-gh-token` directly when it is on PATH (bare on the Mac) and over the SSH bridge otherwise (shipped by `multiplai-container`), and prints **nothing** on stdout when it fails. The hooks must test that stdout for emptiness *before* handing it to `gh` — never `gh-tok | gh auth login`: on empty stdin, `gh auth login --with-token` starts the interactive device flow and hangs forever (see the 2026-07-30 entry in CHANGELOG.md). Both hooks also run bare on a Mac: /bin/bash 3.2, no coreutils, BSD date — `evals/unit/test_gh_app_hooks.py` pins the portability along with everything else. It lives here rather than in the image so it can never be a container release behind the hooks that call it.

**Why a PreToolUse guard exists at all.** Sessions run `--dangerously-skip-permissions`, so the `settings.json` allow-list never prompts and never blocks — the container is the sandbox. Hooks still run in bypass mode, which makes PreToolUse the only layer that can still say no. `guard_destructive.py` denies a curated set of *unrecoverable* commands (host-mount deletes, force-push to main, `docker prune`, `DROP TABLE`, …) and gets out of the way otherwise. Keep it small: it exists to stop the confident mistake, not a determined adversary, and a guard that blocks ordinary work gets disabled and then protects nothing. Calibration in both directions is pinned by `evals/unit/test_guard_destructive.py` — add a test on both sides when you add a rule.

**The guard must also be *reachable*, which is a separate failure mode.** It is registered as `dotfiles/hooks/guard-destructive.sh`, a wrapper that runs `guard_destructive.py` and **denies if it could not run at all** — the guard exits 0 on every path by contract, so a non-zero exit means no verdict was reached, and only a verdict may let a command through. Its hook command in `settings.json` carries **no `2>>` redirect**: the shell opens a redirect before exec'ing anything, so when `runtime/logs/` did not exist (a fresh clone or worktree — only `setup.sh` creates it) the hook died at `Directory nonexistent` and every Bash call in the session ran unguarded behind one line of stderr (kit #26). `run-hook-python` now creates that directory and takes the redirect on itself. Don't re-add a redirect to that line, and don't "fix" a failing guard with `|| true` — `evals/unit/test_guard_hook_wiring.py` fails on both.

**Hook protocol:** Hooks receive JSON on stdin, write JSON to stdout. See Claude Code docs for the schema per event type.

**Key constraint (plugin side):** SessionEnd hooks are killed within seconds — they cannot run long-running scripts. The plugin uses the deferred pattern: write a marker at SessionEnd, process it later via a detached subprocess. See the plugin's `scripts/session_end.py` and `scripts/extract_learnings.py`.

**The kit is one of the two drains.** Processing "later" used to mean the next `SessionStart`, which is why closing the last tab of the day left its write-up until the next session. `post_exit_drain()` in `claude.sh` now launches a disposable drain container (same image, `docker run -d --rm`, `drain_extractions.py --wait` as its process) once a container-mode session has exited. The host never executes plugin-resolved code — an earlier host-side design was rejected because the plugin manifest/cache are container-writable; the launcher only checks marker filenames and assembles the `docker run`, and script resolution happens inside the container. `--wait` is load-bearing: the session container can't drain itself because `--rm` takes detached children down with PID 1, and the drain container avoids the same fate by staying in the foreground until its children finish. `--local`/bare and hub driver sessions `exec` and never reach the drain. Both drain paths call the same `lib/extraction_drain.py`, so the dequeue (an atomic rename) is race-safe and the two cannot diverge — which is also why two launchers exiting at once need no host-side lock. The launcher's decision logic — when it fires, the drain container's exact mounts and two-variable env (no `.env` secrets, no API key), the in-container resolution payload, that it never changes the exit status — is pinned by `evals/unit/test_claude_sh_drain.py` against a stub `docker`; whether extraction then succeeds depends on a real docker daemon and host OAuth, neither of which exists in CI.

**The kit is also the only thing that can see a session die.** Every liveness
signal the `multiplai-context` plugin has is a hook — code running *inside* the
session — so a reboot, a closed terminal, a `docker kill` or an OOM produces no
event at all, and the fleet view was left inferring death from silence. The
container cannot ask: no docker binary, no socket, not root, and the build
gateway's allowlist has never carried `docker`. So `write_container_roster()`
in `claude.sh` writes `docker ps --format '{{.Names}}'` to
`$WORKSPACE/.multiplai/data/live_containers.json` — **before** the session
`docker run` (which is what makes it seconds old at the SessionStart that
renders `AGENTS.md`, with no daemon and no timer) and **again after it exits**
(`--rm` has reaped the container by then, so this is the first reading that can
see it gone). The reading carries `kind` and `observer` so a reader can refuse
one it cannot interpret — a container name is globally meaningful, a pid only
means something in the namespace that observed it, and session identity moves to
a pid under the SDK. Best-effort on every path; it may cost accuracy in a status
view, never a session. Pinned by `evals/unit/test_claude_sh_roster.py`. This is
a **poll**, deliberately not the write-on-exit marker dropped in 0.15.1: that
one died with the launcher, so it covered none of the cases it existed for.

**Testing the in-tree hook locally:**
```bash
# Syntax validation (PostToolUse)
echo '{"hook_event_name":"PostToolUse","tool_name":"Write","tool_input":{"file_path":"/tmp/x.json","content":"{}"}}' | \
  bash dotfiles/hooks/validate-syntax.sh
```

To test the memory/lifecycle hooks, run them from the plugin repo (it has its own `tests/`).

## Editing Skills

The skill library ships as themed marketplace plugins (`multiplai-pm`, `multiplai-writing`, `multiplai-research`, `multiplai-dev`, `multiplai-media`) developed in the marketplace repo (`multiplai-cc-mktplace`), not here. `dotfiles/skills/` is reserved for the user's own local skills: one directory per skill with a `SKILL.md` (frontmatter + prompt) and optionally `scripts/`, `references/`, or supporting `.md` files. The `/multiplai-context:*` skills live in the marketplace repo too.

## Editing the Output Style

`dotfiles/output-styles/clear-writing.md` holds the writing rules, and
`"outputStyle": "Clear Writing"` in `dotfiles/settings.json` turns it on for
every project. `CLAUDE_CONFIG_DIR` *is* `dotfiles/`, so the directory ships as
`$CLAUDE_CONFIG_DIR/output-styles/` with no `setup.sh` change.

**Why the rules live here and not in `dotfiles/CLAUDE.md`.** That file is read
once, at session start. In a long session the rules end up hundreds of thousands
of tokens back and the model drifts. An output style goes into the core system
prompt *and* is re-stated every turn — the emitter builds
`` `${t.name} output style is active. ${e.turnReminder ?? "Remember to follow the
specific guidelines for this style."}` `` next to the other per-turn reminders.
`dotfiles/CLAUDE.md` keeps two rules as a fallback and points here for the rest;
don't re-add the full list there.

**Three things to know before writing another one:**

- **`keep-coding-instructions: true` is mandatory.** The gate is
  `c === null || c.keepCodingInstructions === !0`, so a custom style *without*
  it silently drops Claude Code's own software-engineering system prompt. All
  three built-in styles set it.
- **`turn-reminder` is not a frontmatter key.** Only `keep-coding-instructions`
  and `force-for-plugin` are read from a custom style's frontmatter;
  `turnReminder` is set on built-in styles only. A custom style always gets the
  generic sentence, so the **name** is the only part of the reminder you control.
  Name it so that sentence reads well.
- **The setting takes the `name` from frontmatter, not the filename.** Styles are
  keyed `[t.name]=t`. `clear-writing.md` declares `name: Clear Writing`, which is
  why the setting says `"Clear Writing"`.

## Configuration

`multiplai.conf` (at the kit project root, NOT in dotfiles/) sets the model/effort ceilings for hooks and the buildme / deep-research SDK pipelines, plus log level/retention and per-task model tiers. Changes take effect on next invocation. See the file for documentation on each setting.

**It does not configure Claude Code skills.** A skill's `model` and `effort` come from its own `SKILL.md` frontmatter and nothing else — Claude Code offers no override (`skillOverrides` is on/off/user-invocable-only and short-circuits to "on" for plugin skills; `pluginConfigs.options` are handed to the plugin, never read to pick a model). To retune a skill, edit its frontmatter in `multiplai-cc-mktplace`.

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
| `dotfiles/settings.json` | Registers the `validate-syntax` + `guard_destructive` hooks; selects the `Clear Writing` output style; `pluginConfigs["multiplai-context@multiplai"]`; statusline; permissions |
| `dotfiles/output-styles/clear-writing.md` | The writing rules — in the core system prompt and re-stated every turn, which `dotfiles/CLAUDE.md` cannot do |
| `multiplai.conf` | Kit config (model/effort ceiling for hooks + SDK pipelines, per-task tiers) — at project root, NOT in dotfiles/ |
| `dotfiles/hooks/validate-syntax.sh` | Runtime hook (PostToolUse Write\|Edit) — YAML/JSON syntax validation |
| `dotfiles/hooks/guard-destructive.sh` | The registered PreToolUse(Bash) entry point — runs the guard and denies if it could not run |
| `dotfiles/hooks/guard_destructive.py` | The guard itself — denies unrecoverable commands; the only enforcement layer in bypass-permissions mode |
| `dotfiles/hooks/gh-app-auth.sh` | Runtime hook (SessionStart) — mints a GitHub App token into gh's credential store; inert without `GH_TOKEN_APP` |
| `dotfiles/hooks/gh-app-refresh.sh` | Runtime hook (PreToolUse Bash) — re-mints when the cached token has run out; zero-fork hot path |
| `dotfiles/hooks/gh-tok` | Minting primitive both App hooks call — SSH bridge → host `multiplai-gh-token`; not a user-facing idiom |
| `dotfiles/hooks/model_resolver.py` | Model-ceiling logic for in-tree skills |
| `dotfiles/hooks/log_utils.py` | Shared logging helper (used via PYTHONPATH by plugin skills — buildme, deep-research) |
| `multiplai-cc-mktplace` → `plugins/multiplai-context/` | The memory/context/learning plugin (marketplace repo) — routing, diary, learnings now live here |
| `evals/conftest.py` | Test infra — `sys.path` wiring + LLM bypass for the kit unit tests |
| `container/` | Container tooling — fetched at setup from spikelab/multiplai-container |
| `setup.sh` | First-time setup with prerequisite validation |
| `claude.sh` | Launcher (container/local/shell modes) |

## Reference-doc count

The README says "20+ reference docs" on purpose — growth-tolerant, no stale
number to maintain. Derive the exact count when needed:

```bash
ls dotfiles/reference/dev/*.md | wc -l
```

## Hub integration docs — held back until multiplai-gui releases; restore to README then

The `driver` subcommand and the adoption take-back loop are real, shipped code
in `claude.sh` and `scripts/claude-wrapped` — the kit half of a handshake with
the multiplai native cockpit (multiplai-gui), which is not yet released. Per
the suite rule, public material presents the GUI as *coming*, never available,
so the two README sections below were removed from `README.md` → "Launcher
Modes" (replaced by one roadmap-ceiling paragraph) and preserved here
verbatim. When multiplai-gui releases, restore them to the README.

### Driver subcommand (hub-launched)

`./claude.sh driver --sid <uuid|new> --port <n> --runner <path>` starts a detached, non-interactive driver container for the multiplai hub (multiplai-gui, ADR 0002) — the hub owns its lifecycle. Notes:

- `driver` must be the **first** argument; anywhere else it is treated as a claude prompt/passthrough.
- Driver flags accept only the space-separated form (`--sid x`, not `--sid=x`).
- `--plugin-dir` / `--add-dir` are rejected in driver mode (they are claude-CLI flags; the driver runs the hub's runner, not claude).
- Driver containers **intentionally omit the SSH agent mount** that interactive containers get: a hub-owned driver should never perform SSH-authenticated operations with the user's agent. This parity gap vs interactive mode is deliberate.

### Hub adoption take-back (optional)

If you run the multiplai hub (multiplai-gui), it can **adopt** a session you
started from a terminal — e.g. you walk away and continue it from your phone.
The multiplai-context plugin's hooks keep a session registry under
`$WORKSPACE/.multiplai/data/sessions/`; the hub drops a `<session-id>.adopt`
marker there when it takes the driver seat. When claude exits and a marker
addressed at your container exists, `claude.sh` offers:

```
Session adopted by multiplai hub. Press Enter to take it back, Ctrl-C to leave it.
```

Enter asks the hub to release the session (`POST /v1/sessions/<id>/release`,
hub URL/token from the environment or `multiplai.conf`, silently skipped if
the hub is unreachable), deletes the marker, and relaunches the container
with `claude --resume <session-id>`. Without a hub, a marker, or the plugin,
nothing changes — the launcher behaves exactly as before.

**No-Docker parity:** running claude bare on the host? `scripts/claude-wrapped`
wraps `claude "$@"` in the same take-back loop (`alias claude-w=".../scripts/claude-wrapped"`).
Host adoption is *cooperative*: with no container to kill, the hub only adopts
host sessions that are idle or ended — in practice, after you exit claude —
and the wrapper handles the take-back half of that handshake.
