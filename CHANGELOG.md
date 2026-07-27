# Changelog

All notable changes to multiplai-kit are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This repo carries **no release tags** — the kit is consumed by tracking `main`
(`git pull && ./setup.sh`), so sections below are dated by the commit date on
which the change landed rather than by a version number.

History starts at the first public commit (2026-07-05). The extraction of the
memory/context/learning system out of the kit and into the `multiplai-context`
plugin happened **before** that commit, so it has no entry of its own: the
public repo has shipped without in-tree memory hooks from day one (see the
2026-07-05 section).

## [Unreleased]

### Changed

- README: hub-integration documentation (the "Driver subcommand" and "Hub
  adoption take-back" sections) is held back until multiplai-gui releases —
  replaced by a one-paragraph roadmap note. The full text is preserved in
  `CLAUDE.md` for restore-on-release; the code paths themselves are unchanged.
- README: entry-path de-escalation (marketplace plugin vs full kit, umbrella
  repo link) moved into the intro, before Prerequisites, so newcomers meet the
  lighter path before the clone-and-Docker quickstart.
- README: reference-doc count is growth-tolerant "20+" instead of an exact
  figure; the derive command moved to `CLAUDE.md`.
- README: `MULTIPLAI_LOG_RETENTION_DAYS` is documented as its shipped default
  `90` in the Kit Configuration table. It previously said `0` ("keep forever"),
  contradicting the Data & retention section — a privacy-relevant default,
  since the setting governs how long rotated logs holding prompt excerpts
  survive.
- README: the skill library is **six** themed marketplace packs, not five —
  `multiplai-messaging` ships and was omitted from both enumerations.
- README: the reference-doc figure is 21 `.md` files in
  `dotfiles/reference/dev/` (including the README index), was 20.
- README: Prerequisites and Quick Start moved above "How It Works" and "The
  Memory System", and a Contents list was added after the intro. Prose
  unchanged — a reorder, not a rewrite.

### Added

- `CHANGELOG.md` (this file).
- `SECURITY.md` — supported versions, reporting contact, and the threat model
  the README already implies.
- `.github/workflows/ci.yml` — runs `pytest evals/` and a `bash -n` syntax
  check over `claude.sh` and `setup.sh` on every push to `main` and every PR.

## 2026-07-26

### Added

- **PreToolUse destructive-command guard** (`dotfiles/hooks/guard_destructive.py`),
  registered in `dotfiles/settings.json`. Sessions run with permissions
  bypassed, so this is the only layer that can still refuse an unrecoverable
  command. Calibration is pinned by `evals/unit/test_guard_destructive.py`.
- **Rotated-log retention** — `MULTIPLAI_LOG_RETENTION_DAYS` in
  `multiplai.conf`, shipped default `90` days, enforced once per process on the
  first `setup_logging()` call.
- **Credential minimization** — `MULTIPLAI_SKILL_SECRETS` gates which messaging
  secret groups (`gmail`, `slack`) are forwarded into the container; the
  launcher prints what went in and what was withheld.
- **`--net <profile>` stub** — `unrestricted` is the default and the only
  implemented value; asking for `restricted` exits with an error rather than
  silently falling back.
- `docs`/`skill-dev` reference: tool-shape policy and a model-upgrade re-test
  checklist.

### Changed

- `CONTAINER_REF` pinned to container `v0.6`.
- README: newcomer-oriented reframe of the memory-plugin section, stale
  in-tree-hook claims removed, link to the umbrella `multiplai` repo added.

## 2026-07-25

### Removed

- The skill model/effort sync in `setup.sh` — it never patched anything. A
  skill's model and effort come from its own `SKILL.md` frontmatter; Claude Code
  offers no override.

## 2026-07-16

### Fixed

- Launcher: driver containment checks canonicalize paths; claude-CLI-only flags
  (`--plugin-dir`, `--add-dir`) are rejected in driver mode; driver-mode limits
  documented.
- Launcher: hub take-back loop hardened against prompt replay and a
  concurrent-terminal session-id grab.
- `setup.sh`: host-gateway install is gated on a verified re-pin plus build;
  the container staleness probe is bounded.
- `setup.sh` executable bit restored.
- `dotfiles/settings.json`: dropped the `CLAUDE_CODE_MAX_OUTPUT_TOKENS` cap
  that truncated long SDK generations.

## 2026-07-15

### Added

- `setup.sh` installs the host build gateway from the container pin, and the
  three-part update model (kit / container / plugins) is documented.

### Changed

- `CONTAINER_REF` pinned to container `v0.5`.

## 2026-07-14

### Added

- `./claude.sh driver --foreground` — attached driver run with logs visible,
  for debugging.
- Shipped global instructions (`dotfiles/CLAUDE.md`): worktrees-by-default
  policy.

### Fixed

- `requirements.txt`: floor `claude-agent-sdk` at `0.2.116` — earlier versions
  never carry the session id in the init message, so hub-commissioned sessions
  hung at start.
- Launcher: claude CLI flags are no longer hijacked outside the `driver`
  subcommand; driver mode runs the kit venv python explicitly; driver port
  range is validated and new container names are collision-free.
- `claude.sh` forwards only credential env vars that are actually set.
- Auto-compact is steered from the tracked `settings.json`, not
  `settings.local.json`.

## 2026-07-13

### Added

- `./claude.sh driver --sid <uuid|new> --port <n> --runner <path>` — detached,
  non-interactive driver containers for the multiplai hub (multiplai-gui
  ADR 0002).

### Fixed

- Take-back loop review fixes: session id validated as a UUID before URL /
  `--resume` use; hub token passed via `curl -H @-` stdin instead of argv;
  fail-closed on release timeout/5xx; one-shot `-p/--print` prompt no longer
  replayed on resume; prompt skipped on non-tty stdin; exit status preserved on
  Ctrl-C; registry lookup whitespace-tolerant and mtime-ordered.
- `scripts/claude-wrapped`: session-id discovery scoped to the session that just
  ran; always sources `.env` with shell env keeping precedence; exports
  `CLAUDE_CONFIG_DIR` and bare-mode flags like `claude.sh`.

## 2026-07-12

### Added

- **Hub adoption take-back** — when the multiplai hub adopts a terminal-started
  session, `claude.sh` offers to take it back on exit and relaunches with
  `claude --resume <session-id>`. `scripts/claude-wrapped` gives the same loop
  to bare host runs.

## 2026-07-09

### Added

- `multiplai.conf`: documented `pick_model` per-task tier overrides.

## 2026-07-08

### Added

- Launcher and env support for the `multiplai-messaging` plugin.

### Changed

- The `multiplai-context` plugin is enabled by default.
- `CONTAINER_REF` pinned to container `v0.4` (adds pandoc + typst and the
  `md2pdf` wrapper).

### Fixed

- `setup.sh` gitignores `.multiplai/data/` in the workspace repo.
- `claude.sh` env plumbing: exported on source, forwarded via an allowlist.

## 2026-07-07

### Added

- Git credential helper auto-configured via a `SessionStart` hook.

### Changed

- `md2pdf` documented as the canonical markdown → PDF path.

### Fixed

- `runtime/logs/hook-errors.log` oversize truncation is actually enforced.

## 2026-07-06

### Changed

- `CONTAINER_REF` pinned to container `v0.3`.

### Fixed

- `DISABLE_AUTOUPDATER=1` passed into the container.
- Per-runtime venv volume — parallel runtimes no longer collide.
- Venv-volume ownership prep now runs on fresh volumes.
- Assorted correctness and doc fixes across `setup.sh`, `claude.sh`, and hooks.

## 2026-07-05

### Added

- **Initial public release of the kit**: the `claude.sh` launcher
  (container/local/shell modes, git-identity profiles, GCP overlays),
  `setup.sh`, the self-contained `dotfiles/` used as `CLAUDE_CONFIG_DIR`, the
  `dotfiles/reference/dev/` best-practice docs, `multiplai.conf` model/effort
  ceilings, the `evals/` unit suite, and the `workspace-scaffold/` templates.
- The memory / context-routing / diary / learnings system is **not** in this
  repo: it ships as the `multiplai-context` plugin from the Multiplai
  marketplace (`spikelab/multiplai-cc-mktplace`), which `setup.sh` installs.
  The kit registers only `validate-syntax.sh` directly.

### Fixed

- Code-review findings across security, hook protocol, and stale docs.
