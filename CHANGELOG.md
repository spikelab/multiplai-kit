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

### Removed

- **The status line no longer carries a fleet reading.** The segment read a
  one-line `$WORKSPACE/.multiplai/data/fleet.txt` precomputed by the
  `multiplai-context` plugin; as of plugin `0.18.0` that file is retired (and
  actively deleted if left over) in favour of the richer `/fleet-status`
  digest and `AGENTS.md`, so the segment had nothing to display. The
  `evals/unit/test_statusline_fleet.py` suite went with it. Update the plugin
  to `0.18.0` alongside this pull — an older plugin would keep writing a file
  nothing reads.

### Security

- **A "never print a secret value" section now ships in the always-loaded
  `dotfiles/CLAUDE.md`.** The rule existed, but only in a memory file, and
  memory routing is prompt-driven — so it loaded only when the prompt already
  looked security-shaped. Every observed leak happened as a side effect of
  unrelated work (a sprint sync, a config edit), which is exactly the case
  retrieval-gated memory cannot cover. The section names the two allowlisted
  safe forms (names-only, presence-test) and forbids redaction-by-regex, which
  fails open whenever the variable *name* doesn't match the pattern keyword.

### Added

- **Your last session of the day now gets written up that evening, not the next
  time you open one.** The `multiplai-context` plugin defers diary/learnings
  extraction to a marker file, because the `SessionEnd` hook is killed within
  seconds — and until now the only thing that ever picked a marker up was the
  *next* `SessionStart`. Close your last tab on a Friday and Friday's diary
  entry appeared on Monday. It cannot be fixed inside the container either:
  `docker run --rm` tears everything down when the session's process exits.

  `claude.sh` now launches a **disposable drain container right after the
  session container exits** — same image the session ran in, detached
  (`docker run -d --rm`, named `multiplai-drain-<timestamp>-<pid>`), with the
  plugin's `drain_extractions.py` as its process instead of claude. No daemon,
  no timer, and only when a marker was actually written. It runs silently, and
  it never changes the exit status `claude.sh` reports.

  **Nothing plugin-resolved runs on the host — by decision, not accident.** An
  earlier design ran the drain directly on the Mac; it was rejected because
  that meant the host executing a script resolved from
  `installed_plugins.json` / the plugin cache — state that is writable from
  inside every container. The launcher now only checks for marker *filenames*
  and assembles the `docker run`; resolving and running the script happens
  inside the container, the trust domain built for it.

  The drain container is deliberately narrower than a session: it mounts only
  the workspace, the config dir, and the live OAuth credentials (the same
  renaming bind a session gets — never a copy, the CLI refreshes the token in
  place), and its environment is exactly `WORKSPACE` and `CLAUDE_CONFIG_DIR`.
  None of your `.env` secrets are forwarded, and
  `CLAUDE_PLUGIN_OPTION_anthropic_api_key` structurally cannot reach it — the
  drain always runs on your existing OAuth session, never a billed API key.

  Nothing to configure. It's inert unless a marker is queued and the installed
  `multiplai-context` is new enough to ship the script (0.11.0+); otherwise
  you simply get the old behaviour — drained at the next session start. Scope
  worth knowing: this fires for **container-mode sessions only**. `--local` /
  bare sessions and hub `driver` containers never return to the launcher, so
  they still drain at the next `SessionStart`.

  It also **repairs extractions that were interrupted**. When a container is
  torn down while an extraction is still running — which is the ordinary way a
  session ends — the child dies with it and leaves its marker behind, mid-flight
  rather than queued. The launcher counts that as work too, so the write-up is
  recovered on the next exit instead of waiting for whenever a new session
  happens to start. (Two launchers exiting at once may both fire; the queue's
  atomic-rename dequeue means each marker is processed exactly once.)

- **The status line now carries a fleet reading.** If you run several Claude
  Code tabs at once, every one of them ends with something like
  `6 fronts · 2 need you · oldest 3d · 1 collision` — how many sessions are
  live, how many are waiting on you, how long the quietest has been quiet, and
  how many files two live sessions are both holding. It is ambient: no
  thresholds, no warnings, nothing to dismiss.

  It costs one read of one small file. The multiplai-context plugin (v0.12.0+)
  precomputes the line into `$WORKSPACE/.multiplai/data/fleet.txt`; the status
  line only displays it, so nothing is scanned or summarized per prompt
  render. Without that plugin — or without `WORKSPACE`, or with no session
  live — the segment renders nothing and the rest of the line is unchanged.

  The full version of the same reading, one entry per agent with intent, next
  action, files and collisions, is `.multiplai/data/AGENTS.md`.

- **`GH_TOKEN_APP` — GitHub App authentication, as an alternative to a PAT**
  (macOS + host bridge). Set `GH_TOKEN_APP=<app>` in `.env` or an
  `env.<profile>` and the session authenticates `gh` and `git` off a fresh
  **~1-hour GitHub App installation token**, minted on the Mac and renewed in
  place. The App's private key never enters the container, and no long-lived
  token exists to leak.

  How it works, in three parts: `claude.sh` forwards only the profile **name**;
  a new `SessionStart` hook (`dotfiles/hooks/gh-app-auth.sh`) mints via the SSH
  bridge and stores the token in **gh's own credential store**, so it survives
  every Bash call and — through the `gh auth setup-git` helper the kit already
  installs — serves `git clone/fetch/push` over https with no token in the URL;
  a new `PreToolUse(Bash)` hook (`gh-app-refresh.sh`) re-mints when the cached
  token has run out, decided at the moment of use so an idle session recovers.
  Nothing to type, nothing to prefix, no wrapper, no bespoke credential helper.
  The minting primitive is `dotfiles/hooks/gh-tok` (a kit file, bind-mounted, so
  it can never be a container release behind the hooks that call it).

  **PAT and App modes are mutually exclusive and the launcher enforces it.**
  Declaring `GH_TOKEN_APP` *in configuration* alongside `GH_TOKEN` or
  `GH_TOKEN_KEYCHAIN` is a hard launch error naming both variables and the file
  each came from — they select different GitHub identities, and a silent winner
  means running as the wrong user. Give each identity its own profile (see
  `docs/PROFILES.md`). A shell export is still an override, not a conflict, in
  **either direction** — `GH_TOKEN` from the shell wins over a file-declared
  `GH_TOKEN_APP` and vice versa — and the launcher prints a notice naming the
  variable being dropped and the file that declared it, so the override is
  never silent. PAT mode is otherwise unchanged and remains the default.

  A dead bridge degrades, it never blocks: a failed mint writes a 60-second
  backoff marker beside the token cache, so `gh` runs unauthenticated and the
  renew path is retried at most once a minute — instead of every Bash call
  paying the SSH connect timeout inside the PreToolUse hook.

  Host-side setup (creating the App, installing its key) lives in the container
  repo: `container/docs/gh-app-token.md`. `setup.sh` installs the host minting
  script `multiplai-gh-token` into `~/.local/bin/` from the pinned `container/`
  checkout, under the same verification gates as the SSH gateway.

### Fixed

- **A failed App-token mint hung the session instead of degrading it.** In App
  mode a mint failure — a wrong `org` in the host profile, a dead bridge, a
  revoked key — made sessions **unstartable**: `SessionStart` stalled before
  Claude was usable and, once past it, every Bash call stalled again. The only
  way out was deleting both hooks from `settings.json`.

  Cause: both hooks piped `gh-tok` straight into `gh auth login --with-token`,
  on the documented assumption that an empty stdout plus a non-zero status would
  make the store call "abort visibly". It does not. Measured on gh 2.96.0,
  `gh auth login --with-token` treats **empty stdin as "no token supplied"** and
  falls through to the interactive OAuth **device flow** — it prints a one-time
  code and then blocks forever on a terminal a hook does not have. `exit 0 on
  every path` never helped, because a hook that hangs never reaches its exit.

  Both hooks now mint into a variable and only invoke `gh` once it is non-empty
  (still piped, never on argv), and the store call is time-bounded so no
  future change in how `gh` reads its stdin can stall a session again. The two
  hook entries in `dotfiles/settings.json` also carry an explicit
  `"timeout": 30`. Eleven tests were added, including a `gh` stub that models
  the real device-flow block: the previous stub accepted empty stdin and exited
  0, which is why 179 green tests said nothing about any of this.

- **App mode now works bare on a Mac (no container).** The App hooks and
  `gh-tok` quietly assumed the container's toolchain, and every assumption
  broke under a bare-Mac launch (`--local`, or Docker absent): GNU `timeout`
  does not exist on macOS (the store call died with exit 127, turning a valid
  mint into a failed store); `/bin/bash` is 3.2, so `$EPOCHSECONDS` is silently
  empty (the renew guard compared against nothing) and `printf '%(...)T'` is a
  printf error; BSD `date` has no `-d` (every mint fell to the 30-minute cache
  fallback, with a warning each time); and `gh-tok` ssh'd to
  `host.docker.internal`, which only resolves from inside a container. Now: the
  store call goes through `bounded()` — GNU `timeout` where present, else a
  perl `alarm`, which survives `exec` and so is a real bound; the clock is
  `${EPOCHSECONDS:-$(date +%s)}` (one `date` fork on bash 3.2, still zero forks
  on the container's bash 5); log timestamps come from `date -u`; expiry
  parsing tries BSD `date -j -f` after GNU `-d`; and `gh-tok` calls
  `multiplai-gh-token` directly when it is on PATH (the bare-Mac case) instead
  of ssh'ing to a bridge hostname that cannot resolve there.

- **A hook killed by its `settings.json` timeout no longer forfeits the
  backoff marker.** The marker was written on the failure branch — but a slow
  bridge plus a slow store can exceed the entry's `"timeout": 30`, and a hook
  Claude Code kills mid-mint never reaches any branch. The next Bash call then
  re-paid the very stall the marker exists to prevent. Both hooks now write the
  marker BEFORE attempting the mint and remove it on success, so being killed
  leaves the backoff behind — one extra tiny write per renewal (hourly).

- **`gh-app-refresh.sh` spammed the hook log on the missing-cache path.**
  `read -r x < missing 2>/dev/null` does not silence the shell: bash applies
  redirections left to right, so the failing `<` is reported before the stderr
  redirect takes effect. Every session with no token cache yet wrote two
  `No such file or directory` lines into `hook-errors.log` — noise in exactly
  the file you open to debug the cache. Now a brace group carries the redirect.

### Removed

- **`--gcp <name>` flag and the `env.gcp.*` overlay convention.** GCP wiring is
  now activated by `GCP_KEY_FILE` alone, from wherever it is set — `.env`, a
  profile, or an export for one launch (`GCP_KEY_FILE=~/k.json ./claude.sh`).
  With dynamic forwarding and shell-env-wins there was nothing left for a
  selector flag to do. **Migration:** move the contents of your `env.gcp.<name>`
  into `.env` or the relevant `env.<profile>`, and rename `GCP_PROJECT` to
  `CLOUDSDK_CORE_PROJECT` (the launcher no longer translates it). A
  `GCP_KEY_FILE` pointing at a missing file is now a hard error rather than a
  silent launch without credentials. The `-gcp<name>` container-name suffix is
  gone with the flag.
- **`--net <profile>` flag.** Its only implemented behaviour was refusing
  `restricted`, which the `MULTIPLAI_NET` environment variable already covers.
  Set `MULTIPLAI_NET` in `.env` or export it per launch; the value validation and
  the loud refusal of `restricted` are unchanged.
- **`MULTIPLAI_SKILL_SECRETS`.** The gate is deleted, and `SLACK_TOKEN` /
  `GMAIL_*` are forwarded like any other declared variable. It read as a
  confinement it never provided: `.env` sits on the bind-mounted kit root and the
  skills read it from there, so a session could obtain any credential in the file
  regardless of what was forwarded. The honest boundary is `.env` itself —
  narrow by keeping a credential out of it until the launch that needs it. If you
  had it set, delete the line; nothing else is required.

### Changed

- **Container environment is forwarded dynamically.** Every variable assigned in
  `.env` or `env.<profile>` reaches the container when its value is non-empty,
  minus a denylist of launcher-only settings and host paths the mounts remap.
  Previously an enumerated list in `claude.sh` decided, so any new secret needed
  a matching launcher edit and silently never arrived without one. Values are
  passed as `-e NAME` (no `=value`), so they are read from the launcher's
  environment and never appear on a command line in `ps`.
- **The shell environment now overrides the env files.** `.env` and
  `env.<profile>` provide defaults; anything exported before launch wins,
  including `WORKSPACE`. This is the precedence the kit already documented and
  that the in-container loaders already used (`override=False`) — the launcher
  was the one place that violated it. If you relied on `.env` overriding an
  exported variable, unset it in your shell.
- A profile (`env.<profile>`) may now carry any variable, not just git identity —
  e.g. a client's `GCP_KEY_FILE`. Documented in `docs/PROFILES.md`.
- README, `SECURITY.md`, `docs/PROFILES.md`, `CLAUDE.md`, `.env.example` and
  `env.example` updated for all of the above: a new "How variables reach the
  container" section, `.env` named as the credential boundary, and the removed
  flags struck from every launch example and threat-model row.
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

### Fixed

- **Empty variables are no longer forwarded into the container.** `-e NAME=`
  makes a variable *present but empty*, which beats every `${NAME:-fallback}` and
  `os.environ.get(NAME, default)` downstream. Concretely: an unset `GH_TOKEN` was
  forwarded as empty and shadowed a token the container mints for itself, leaving
  `gh` unauthenticated with no visible cause. Empty or unset now means not
  forwarded, so in-container defaults apply as intended.
- `--profile` overrides are no longer at risk from the new precedence rule: the
  launching shell's snapshot is taken once, before `.env` is sourced, so a
  profile still overrides `.env` while the shell still overrides both.
- `claude.sh` no longer runs `eval` on `WORKSPACE` or `GCP_KEY_FILE` to expand
  `~`; a leading tilde is expanded with parameter substitution instead, so a
  command substitution in a config value is no longer executed.

### Added

- `CHANGELOG.md` (this file).
- `SECURITY.md` — supported versions, reporting contact, and the threat model
  the README already implies.
- `.github/workflows/ci.yml` — runs `pytest evals/` and a `bash -n` syntax
  check over `claude.sh` and `setup.sh` on every push to `main` and every PR.
- `evals/unit/test_claude_sh_env.py` — 35 tests pinning the env-forwarding
  contract (empty-var rule, shell-wins precedence, dynamic forwarding, the
  denylist, GCP activation, profile layering, the removed flags). It runs the
  launcher against a stub `docker` that records the argv *and the environment
  docker was handed* — which is what real docker resolves a value-less
  `-e NAME` against — so the rules are checked without a daemon or an image and
  the suite runs in CI. Verified by mutation: breaking each of the seven rules
  in turn makes the corresponding tests fail.
- `scripts/verify-env-forwarding.sh` — answers "is my variable actually reaching
  the container?" by launching real containers and reading the environment from
  inside them, which the stub-based tests cannot do. Prints PASS/FAIL per check
  and exits non-zero on any failure; restores `.env` on every exit path.

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
