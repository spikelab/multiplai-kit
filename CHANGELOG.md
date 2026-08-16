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

### Added

- **Any secret can live in the macOS Keychain: `FOO_KEYCHAIN=<item>` exports
  `<item>`'s value as `FOO`.** `GH_TOKEN_KEYCHAIN` was hand-wired to one
  variable; it is now one instance of a rule that applies to every name. Store
  the item and name it:

  ```bash
  security add-generic-password -a "$USER" -s "anthropic-key" -w "sk-ant-..." -U
  # .env or env.<profile>
  ANTHROPIC_API_KEY_KEYCHAIN="anthropic-key"
  ```

  and the container receives `ANTHROPIC_API_KEY`. Nothing about existing setups
  changes: `GH_TOKEN_KEYCHAIN` behaves exactly as before.

  - **An explicitly set `FOO` wins.** `FOO_KEYCHAIN` is consulted only when
    `FOO` is empty, so `FOO=x ./claude.sh` still overrides for one launch — and
    `security` never runs for a variable that already has a value. The lookup
    stays explicit-only: with nothing declared, the Keychain is not touched.
  - **The resolved value reaches the container.** A variable resolved this way
    was named by no env file (the file named `FOO_KEYCHAIN`) and is on no
    keep-list, so the launcher adds it to the forward set explicitly. Without
    that it would be looked up on the host and dropped at the boundary —
    `GH_TOKEN` only ever escaped that by being hand-listed.
  - **`FOO_KEYCHAIN` itself is never forwarded.** It names an item in a Keychain
    the container cannot reach. Every `*_KEYCHAIN` name is denied dynamically;
    the hardcoded `GH_TOKEN_KEYCHAIN` denylist entry is gone as redundant.
  - **One warning, not one per variable.** Over SSH the login keychain is locked
    and every lookup fails together, so failures are collected into a single
    message listing each `NAME_KEYCHAIN='item' -> NAME` — never a value. The
    launch still proceeds; a missing optional secret must not stop a session.
    The same collection applies to the two unavailability cases (a non-Mac host,
    and a Mac with `security` off `PATH`), which keep their separate messages.
  - **App mode still forbids a PAT fallback.** With `GH_TOKEN_APP` in play the
    resolver skips `GH_TOKEN` alone — a PAT appearing behind an App would swap
    the session's GitHub identity silently. Every other variable resolves
    normally in App mode.

### Fixed

- **A stopped Docker daemon now says so, in both scripts.** `setup.sh` tested
  `command -v docker` *and* `docker info`; `claude.sh` tested only the binary.
  On a host where Docker was installed but not running, setup printed
  "Docker not found or not running — setting up for bare mode", and then
  `./claude.sh` chose container mode anyway, failed `docker image inspect`, and
  said `Docker image '<name>' not found. Build it first: cd container &&
  ./build.sh` — a ten-minute build that could not have fixed it.

  Both scripts now split three ways instead of two, because whether Docker is
  *installed* is a durable property of the host and whether the daemon is *up*
  is not:

  - **No docker binary** → bare mode, as before. Unchanged.
  - **Binary present, daemon down** → `setup.sh` says the daemon is not running
    and skips the image build without claiming bare mode; `claude.sh` refuses
    and names the daemon, offering both exits (start Docker, or `--local` to
    run unsandboxed on purpose). It does **not** fall back to bare mode on its
    own — losing the sandbox because Docker Desktop was still starting is a
    downgrade nobody asked for.
  - **Daemon up, image missing** → the old `build.sh` message, which is correct
    only here.

  `docker info` is asked only *after* `docker image inspect` has already failed,
  so a healthy launch still pays a single daemon round-trip. Driver mode
  (`./claude.sh driver`) separates the same two causes at the door; it has no
  bare fallback for either. A new CI job (`linux-stopped-daemon-e2e`) stops the
  runner's daemon and pins both halves end to end.

### Documentation

- **The launcher-modes table now has a row for a stopped daemon.** It listed
  "No Docker installed → bare mode (a supported rung, not a failure state)" and
  nothing for the case above, so the table promised a fallback that does not
  happen. Both rows are there now, with the reason they differ: installed-ness
  is durable, daemon liveness is not.

- **`docs/SKILLS.md` was two packs and several skills out of date.** It had no
  `multiplai-messaging` and no `multiplai-apple` section at all, while
  `dotfiles/settings.json` enables both — so the kit shipped skills its own
  reference never mentioned. It also still listed `code-review` and
  `security-review`, retired in `multiplai-dev` 0.13.0, and `swift-build` under
  `multiplai-dev`, which is where it lived before the `multiplai-apple` split.
  `plan` was missing, and `multiplai-context` was a one-line list of eight
  namespaced commands against fourteen skills. All eight packs and all 44
  skills are now listed, with descriptions taken from each skill's own
  frontmatter.

- **`host-browser` is documented as opt-in in the three places the kit says
  anything about it** — the skills table, §"Host-bridge requirements", and the
  `WebFetch`-403 rule in `dotfiles/CLAUDE.md` that sends the agent to it.
  Container releases after `v0.9.6` deny `agent-browser` unless
  `~/.local/state/multiplai/host-browser-enabled` exists on the Mac. The
  `dotfiles/CLAUDE.md` change matters most: it told the agent to reach for the
  real browser on a 403 and would now walk it into a denial with no instruction
  for what to do next. It now says to ask the user to create the flag, and not
  to go hunting for another route.

### Added

- **The `multiplai-apple` plugin is enabled by default, so `swift-build` keeps
  working.** New line in `dotfiles/settings.json` → `enabledPlugins`:
  `"multiplai-apple@multiplai": true`.

  The marketplace moved the `swift-build` skill out of `multiplai-dev` and into
  a new mac-only `multiplai-apple` pack. `multiplai-dev` is enabled here and
  `multiplai-apple` was not, so without this line a `git pull && ./setup.sh`
  would have taken `swift-build` away from everyone who has it today — Xcode and
  Swift Package Manager builds, the simulator verbs, and the host bridge that
  runs them all disappear with no message.

  This keeps the status quo rather than changing it: the skill already shipped
  to every install as part of `multiplai-dev`, including Linux ones, where it
  reports that Swift and Xcode builds need macOS. Whether a mac-only pack should
  be enabled on Linux at all is a separate question this entry does not settle.

  **Merge order matters:** this depends on `multiplai-apple` existing in the
  marketplace. Land marketplace PR #208 first — enabling a plugin the
  marketplace does not publish resolves to nothing.

- **Container launches carry `--add-host host.docker.internal:host-gateway`, so
  the name resolves on native Linux (docker-ce).** In-container code addresses
  the host as `host.docker.internal` — the SSH build bridge,
  `CLAUDE_CODE_IDE_HOST_OVERRIDE`, an `ANTHROPIC_BASE_URL` proxy. Docker
  Desktop and OrbStack resolve that name natively; native Linux docker-ce does
  not, so on a Linux host the name did not exist at all. The flag is passed
  unconditionally rather than gated on `uname`: `host-gateway` is a
  daemon-side special value (Docker 20.10+) that macOS engines accept and
  resolve to the same place their built-in alias points, so one argv works
  everywhere. Applies to interactive session containers and hub driver
  containers; the drain container receives none of the env that could address
  the host and is unchanged.

  **What this fixes, and what it does not.** The flag buys *resolution*: the
  name now points at the host's gateway address. That reaches host services
  listening on a non-loopback address, which is why the SSH build bridge works
  on docker-ce — sshd binds `0.0.0.0`. It does **not** reach a service bound to
  the host's own `127.0.0.1`, and two of the three examples above usually are:
  the VS Code extension binds loopback only, and a local LLM proxy does by
  default. OrbStack bridges loopback as a separate, OrbStack-specific
  behaviour; this flag neither provides nor replaces it. On docker-ce those
  services have to be re-bound to `0.0.0.0`, and a host firewall can still
  block the `docker0` interface (ufw's default policy does). Setting
  `CLAUDE_CODE_IDE_HOST_OVERRIDE` on a Linux host and expecting `/ide` to
  connect is the phantom this paragraph exists to prevent.

- **CI now exercises the two install rungs end-to-end on Linux.** One job runs
  `./setup.sh` against a throwaway workspace on a runner with real docker —
  the pinned `multiplai-container` image builds for real — then launches the
  built image through `./claude.sh --shell` on docker-ce and resolves
  `host.docker.internal` inside it, which is the one assertion only a real
  daemon can settle. It separately asserts the composed `docker run` argv
  (stub docker) carries the host alias, on the flag rather than merely
  somewhere in the line, and skip-permissions only where the container is the
  sandbox. A second job
  removes docker from the runner and verifies the bare rung: `setup.sh` exits
  0, `claude.sh` launches without `--dangerously-skip-permissions`, and a
  launch with no GitHub config prints nothing about GitHub.

- **The writing rules moved into a Claude Code output style, and are now on by
  default.** New file: `dotfiles/output-styles/clear-writing.md`, selected by
  `"outputStyle": "Clear Writing"` in `dotfiles/settings.json`.

  They moved because `CLAUDE.md` is read once, at the start of a session. In a
  long session the rules end up hundreds of thousands of tokens behind, and
  Claude drifts back to dense, jargon-heavy replies. Claude Code puts an output
  style in the core system prompt and re-states it every turn, so the rules stay
  in front of the model. Verified in the CLI binary: the style emitter produces
  `"<name> output style is active. Remember to follow the specific guidelines
  for this style."` alongside the other per-turn reminders.

  The rules themselves are the same ones, reordered by how often they break, and
  with one rewritten. "No coined vocabulary" said only what to avoid; it now says
  what to do instead — never invent a name for a thing, say what it does with a
  verb, and describe the thing every time even when that costs more words. It
  carries measured evidence that brevity is not the goal: every reply flagged as
  unreadable was *shorter* than the 11-word median.

  `dotfiles/CLAUDE.md` keeps two of the rules as a fallback and points at the
  style for the rest, so the section cannot drift out of sync with it.

  **If you write your own output style, set `keep-coding-instructions: true` in
  its frontmatter.** Without it Claude Code drops its own software-engineering
  system prompt — the gate is `c === null || c.keepCodingInstructions === !0`.
  All three built-in styles set it. This one does too.

  To turn it off, run `/output-style` and pick another, or drop the
  `outputStyle` key from `dotfiles/settings.json`.

- **`setup.sh` creates `ARTIFACTS/` in the workspace.** It holds the record of
  work you did — an investigation, a set of measurements, benchmark data, a
  published Artifact page. It is tracked and committed, which is the difference
  that matters: `INBOX/` is gitignored, so anything left there is one cleanup
  away from gone.

  The dividing line against `RESOURCES/` is who produced the subject matter.
  Research about something external stays in `RESOURCES/`. A record of work done
  in the workspace goes to `ARTIFACTS/`.

  Existing workspaces get the directory on the next `./setup.sh` — `mkdir -p` is
  idempotent and nothing is moved for you. They do **not** get the routing rules
  that explain it: setup never overwrites a `CLAUDE.md` you already have. It now
  prints a notice when yours has no `ARTIFACTS/` rule, pointing at the template
  to diff against. The edit is yours to make.

### Changed

- **The kit venv now requires `claude-agent-sdk>=0.2.139` (was `>=0.2.116`).**
  `multiplai-core`'s `run_agent` forwards a `thinking` setting into
  `ClaudeAgentOptions`, and an SDK without that field raises `TypeError` on
  every call that sets it — which the plugin skills now do. A `git pull &&
  ./setup.sh` re-syncs the venv and picks up a new enough SDK. If you run the
  skills from a venv you provisioned by hand, upgrade it or they will fail at
  the first model call. The earlier reason for `>=0.2.116` (the init message
  must carry the session id, or a commissioned session hangs at start) still
  holds underneath.

- **The `WebFetch`-failure rule in `dotfiles/CLAUDE.md` now branches by status,
  and the `host-browser` mention shrinks to one conditional clause.** The old
  bullet spent a paragraph of always-loaded context teaching the skill — the
  `ab` quick path, the settle delay for heavy SPAs, the two block classes, a
  pointer to the host prerequisites — which the skill explains for itself once
  it loads (see *Removed*). What stays is the one decision that has to be made
  mid-turn, when the tool result comes back: on 403/429, use
  `/multiplai-media:host-browser` if the `multiplai-media` pack is installed,
  otherwise drop the URL and say so. A `SKILL.md` cannot carry that clause —
  skill routing runs on `UserPromptSubmit`, before any tool call in the turn,
  so nothing inside a skill file is in context at the moment a 403 arrives.

  Two branches the rule never had. **5xx, a DNS failure and a timeout are the
  one case where re-fetching the same URL verbatim is right** — the previous
  blanket "never retry verbatim" turned a single transient 503 into a dropped
  URL and a page reported unreachable. And a **200 with an empty or skeletal
  body is a failure too**: the page is client-rendered and `WebFetch` cannot
  run its JS, so it takes the same remedy as a 403. Nothing had marked that one
  as a failure at all, which left an empty JS shell to be reported as the
  page's content.

  This supersedes one clause of the tool-usage audit entry further down this
  section ("a `WebFetch` 403 is a signal to switch to `host-browser` rather
  than retry"): the escalation still stands, but it is now conditional on the
  pack being installed and sits alongside the other status branches.

  It does **not** change what the container can reach. `agent-browser`/`ab`
  stays on the container build gateway's argv allowlist, `docs/SKILLS.md` still
  lists the skill and its `SSH_BUILD_USER`/`SSH_BUILD_KEY` prerequisite, and
  the plugin's own skill description still reaches every prompt-routing pass.
  Making the host browser an explicit opt-in means a gate in the gateway
  allowlist or in the pack install; that is separate work and is not attempted
  here.

- **Bare mode (no Docker) is presented as what it is: a supported rung of the
  install ladder, not a failure state.** `setup.sh` and `claude.sh` framed the
  no-Docker path as a WARNING with degraded-mode language, which told a Linux
  user without Docker that their supported configuration was broken. Both now
  say which mode the install/launch is and how to add the container sandbox
  later. They also still say what the rung *costs*: claude runs with your whole
  filesystem in reach, and the permission prompts are the only boundary there
  is — which is the one fact a reader needs to choose between the rungs, since
  it is exactly what the container rung changes. The behaviour is unchanged:
  permission prompts stay on in bare mode, and container mode remains the
  default when Docker is present.

- **Launch-time GitHub warnings only fire for misconfiguration, never for
  absence.** A GitHub credential is optional, but every launch without one
  warned about it. Now a launch with nothing GitHub-related configured — no
  `GH_TOKEN`, `GH_TOKEN_APP`, or `GH_TOKEN_KEYCHAIN` in the environment or any
  env file — prints nothing. Half-configured states keep their noise: a
  `GH_TOKEN_KEYCHAIN` item that does not resolve warns (naming the item, and
  noting that Keychain lookups fail over SSH where the login keychain is
  locked), and a `GH_TOKEN_KEYCHAIN` set on a non-Mac host warns that there is
  no Keychain to probe.

- **"Keychain lookups need macOS" is no longer said to a Mac.** That warning
  covered one branch guarded by `Darwin` AND `security`, so a Mac launched with
  a trimmed `PATH` — a cron job, an SSH forced command — fell into it and was
  told its platform was the problem. The two failures now have separate
  messages: a non-Mac is told the Keychain is macOS-only and is given the
  host's actual platform name, and a Mac missing `security` is told the tool is
  off `PATH` and where to put it back.

- **Context overflow is now handled by native autocompaction, not a hard stop.**
  `dotfiles/settings.json` no longer sets `DISABLE_AUTO_COMPACT=1`; it sets
  `"autoCompactEnabled": true` with `"autoCompactWindow": 400000`, and the
  `checkpoint_hard_stop_tokens` plugin option is removed. Before this, a session
  past 250K tokens refused new prompts until a manual `/clear` or `/compact` —
  which also stalled overnight goal runs, with nobody there to hand off. Now the
  multiplai-context handoff nudge stays advisory from its 200K default, and the
  CLI compacts on its own near the 400K window (the actual trigger sits ~33K
  below it: a 20K output reserve plus a 13K margin, per the binary formula the
  plugin mirrors in `lib/checkpoint.py`).

  The window is steered via the `autoCompactWindow` settings key on purpose,
  not the `CLAUDE_CODE_AUTO_COMPACT_WINDOW` env var. The plugin's nudge hook
  detects only env-var steering (`autocompact_trigger_tokens()`), so with the
  settings key it keeps nudging every 25K past 200K instead of going silent
  until compaction is overdue. Both behaviours are wanted: advice from 200K,
  enforcement near 400K. Verified against Claude Code 2.1.226, whose own
  diagnostics list the settings key as a window source alongside the env var.

- **The writing rules in `dotfiles/CLAUDE.md` now cover documents, not just
  chat.** The scope line read "all console output". On a literal reading that
  left out plans, reports, README and doc-site pages, commit bodies, PR
  descriptions, and published Artifacts. Those are named explicitly now. The
  closing line states the general case: if the user will read it, the rules
  apply.

  Three rules join the list. Never open with a correction or a revision note.
  Never report what is good. Cut context that does not change a decision.

### Fixed

- **`setup.sh` now adds `INBOX/` to the workspace `.gitignore`.** It only ever
  wrote `.multiplai/cc-state/` and `.multiplai/data/`, so on a fresh install
  `INBOX/` was tracked — while the workspace `CLAUDE.md` told both you and Claude
  it was "temporary and gitignored". Every plan routed there would have been
  committed by the first `git add -A`, which is the opposite of the documented
  contract and the premise the `INBOX/`-vs-`ARTIFACTS/` split rests on.

  Existing workspaces pick the rule up on the next `./setup.sh`. If you have
  already committed files under `INBOX/`, the new rule does not untrack them —
  `git rm -r --cached INBOX/` does.

- **Published Artifacts route to `ARTIFACTS/`, not `INBOX/`.** The workspace
  `CLAUDE.md` template now says so directly. The file Claude writes before
  calling the Artifact tool is the source behind a URL someone may hold for
  months; parking it in a gitignored scratch directory means losing the ability
  to update that URL later.

### Removed

- **The `host-browser` how-to is out of always-loaded context.** The `ab` quick
  path (`ab open <url>` → `ab snapshot -i`), the settle delay heavy SPAs need,
  the behavioral-wall-vs-policy-wall distinction, and the list of tasks that
  want a real browser (logins, signups, fetching a verification email) all sat
  in `dotfiles/CLAUDE.md`, which every session on every install pays for —
  including installs with no `multiplai-media` pack and no SSH bridge, where
  none of it can run. The skill's own `SKILL.md` documents its operation, and
  its description already names those tasks, so prompt routing still finds it.
  The always-loaded file keeps only the mid-turn pointer (see *Changed*).

- **The implicit `gh-token` Keychain probe.** The launcher used to query macOS
  Keychain for a default item named `gh-token` even when `GH_TOKEN_KEYCHAIN`
  was never set — an invisible lookup that also made the no-config launch warn
  about a Keychain item nobody had created. The Keychain is now probed only
  when `GH_TOKEN_KEYCHAIN` names an item. **Migration:** if you relied on the
  default, set `GH_TOKEN_KEYCHAIN=gh-token` in `.env` to keep the old
  behaviour. Keychain support itself is unchanged.

  **This change is silent, deliberately.** A setup that was nothing but
  `security add-generic-password -s gh-token …` goes from authenticated to not,
  and the launcher says nothing — the absence rule above covers it, and the
  alternative is probing a Keychain nobody pointed the launcher at. Set
  `GH_TOKEN_KEYCHAIN=gh-token` and it works again.

- **`setup.sh` no longer creates `PROJECTS/plans/`.** Nothing in the kit ever
  read it, wrote to it, or referred to it — the sole mention in the repo was the
  `mkdir` that created it. Plans now live in `INBOX/` and are disposable by
  design: a plan either materialises into work or goes stale, and what is worth
  keeping afterwards is the record of the work, in `ARTIFACTS/`.

  An existing `PROJECTS/plans/` is left alone. Delete it yourself if it is empty.

### Security

- **The destructive-command guard closes four bypass classes** in
  `guard_destructive.py` (2026-08-10 hooks review, C1/M9/K1). Rules and
  allowlist now match each shell segment with quotes stripped and `$WORKSPACE`
  expanded, so `rm -rf '/etc'` reads as `rm -rf /etc`; the rm rule accepts
  long flags (`rm --recursive --force /etc`, `rm -r --interactive=never
  /etc`, `rm -rf --no-preserve-root /`) and `${HOME}`; a target containing
  `..` is never allowlisted and the `/tmp` / `/var/folders` exemptions no
  longer cover traversals (`rm -rf /tmp/../etc`, `rm -rf $WORKSPACE/../..`);
  the force-push rule now catches `git push --force origin refs/heads/main`
  and the refspec force syntax (`git push origin +main:main`) while still
  allowing `--force-with-lease` and forced pushes of non-protected branches;
  `docker container prune` joins the prune rule.

- **New guard rule: `git-hook-bypass`.** `git -c core.hooksPath=…`,
  `--no-verify`, and `GIT_CONFIG_NOSYSTEM=` prefixes all skip the git hooks
  that gate commits — including the container's pre-commit secret scan — and
  bypassing that gate is the user's call, not the agent's. Query forms
  (`git config core.hooksPath`) and prose mentions (`git commit -m 'no-verify
  discussion'`) stay allowed.

### Added

- **The launcher stamps the container name onto its tmux pane**
  (`tmux set-option -p @cc "$CONTAINER_NAME"`), which makes "which container is
  in this pane" a property of the pane rather than a line in a file. Rename a
  tab to whatever the work actually is and the fleet board follows on its next
  redraw instead of losing the session; a non-empty `@cc` *is* the definition of
  an agent pane, so `tmux list-panes -a -F '#{pane_id}|#{@cc}'` prints the fleet.
  Needs tmux 3.0; on anything older the stamp silently does not land and the
  behaviour is exactly what it was before.

- **`dotfiles/scripts/fleet-panes.sh`** — the pane→container join, extracted from
  `claude.sh` so the launcher and `fleet-watch` run the same code. Two copies of
  a join is how the two come to disagree about which pane is which.

- **`/ide` now works from inside the container.** The launcher mounts the host's
  `~/.claude/ide/` read-only at `/home/agent/.claude/ide` whenever it exists, so
  the containerised CLI can find the lockfiles your editor extension writes —
  which is what lets diffs open in VS Code / Cursor instead of scrolling past in
  the chat log. No setting to enable, and nothing happens if you have no
  extension installed. `IDE_LOCK_DIR` overrides the host directory.

  The container path is `/home/agent/.claude/ide`, **not** `$DOTFILES_DIR/ide`:
  the CLI searches the resolved config dir plus `$HOME/.claude/ide` whenever
  `CLAUDE_CONFIG_DIR` is set, which the kit always sets.

  The mount is only half of it — also set
  `CLAUDE_CODE_IDE_HOST_OVERRIDE="host.docker.internal"` in `.env` (an ordinary
  forwarded variable). Without it the CLI dials `127.0.0.1`, which inside a
  container is the container, and `/ide` fails in a way that looks identical to
  a missing lockfile.

  **Requires OrbStack.** The editor extension binds the host's `127.0.0.1`, and
  OrbStack routes `host.docker.internal` to host-loopback services. Rootless
  Docker and Docker Desktop sandboxes block precisely this, so there the
  override resolves but nothing answers.

### Changed

- **`gh-app-auth.sh` no longer re-mints on every SessionStart.** SessionStart
  also fires on `resume` and after a compaction, when the token minted at the
  real session start is usually still live; the hook now runs the same
  builtin-only freshness check as `gh-app-refresh.sh` against the `.exp`
  sidecar and exits before forking anything while the cached token comfortably
  outlives the skew window. A missing or stale sidecar mints exactly as
  before.

- **The App hooks' mint/store block now lives once, in
  `dotfiles/hooks/gh-store-token`.** `gh-app-auth.sh` and `gh-app-refresh.sh`
  carried byte-identical copies (backoff pre-write, mint, emptiness check,
  bounded store); both now source the shared helper, so the check that ended
  the 2026-07-30 device-flow hang cannot drift between them. The helper also
  validates `GH_TOKEN_APP` against `[A-Za-z0-9._-]+` before the app name
  reaches any filesystem path — previously a malformed name reached the
  backoff-marker path unvalidated.

- **The shipped `memory_router` default is now `token_overlap`, not `llm`**
  (`dotfiles/settings.json`). The `llm` router spawns the Agent SDK as a
  subprocess per prompt, and that spawn — not the model — is the cost: measured
  over five real prompts, uncapped routing takes a median **27.4 s** (range
  14.8–52.6 s) against a 30 s hook kill. No timeout value fixes that, so the
  shipped default should not be a router that usually loses its race. `llm`
  remains a one-line opt-in for anyone who wants the smaller injection it
  produces when it does finish. Nobody who has already set `memory_router` in
  their own `settings.local.json` is affected.

- **`dotfiles/CLAUDE.md` replaces "be concise" with six mechanical rules for how
  Claude writes to you** (new top section, "How to respond to the user"). The old
  rule — *"You MUST save tokens. Be concise…"* — named an intent, not a
  mechanism, and only ever targeted length. The complaint it failed to fix was
  density: replies that are hard to read, not merely long. The replacement is
  checkable — answer first, one idea per sentence with a 50-word cap, concrete
  subject and active verb, no invented vocabulary, no "the key insight is",
  numbers instead of adjectives. `Save tokens` stays as tiebreaker 4 under "When
  rules conflict". **User-visible**: replies get shorter and plainer after the
  next session start.

- **Container names are now `cc-p-08015414`, not `claude-personal-08015414`** —
  `cc-<profile initial>-<DDHHMMSS>`. **User-visible**: this is the string in your
  tmux tab bar, in `docker ps`, and in the OrbStack hostname, so
  `claude-personal-08015414.orb.local` becomes `cc-p-08015414.orb.local`. If you
  have a bookmark, a script, or a `curl` pointing at one of those URLs, it will
  need the new name; sessions already running keep the old one until relaunched.

  Safe to do because **nothing parses it**. Every consumer — in this kit, in the
  `multiplai-context` plugin, in the pane map and the container roster — compares
  the name whole, as an opaque join key, so this is a rename and not a schema
  change: no migration, no deprecation window, and old sessions go on joining
  correctly among themselves because every record for one was written with the
  same string.

  The profile survives as its initial rather than being dropped, because
  `cc-w-04221854` tells you at a glance that it is the work identity and the
  fleet board has no other field carrying that. Two profiles whose first letter
  matches are indistinguishable in the name — that is the one cost.

  The fleet board's label column goes 24 → 16 with it, handing eight columns
  back to the checkpoint summary. 24 was never a width anyone wanted; it was the
  length of `claude-personal-08015414`, and below it every unlabelled agent
  rendered as `claude-personal…`.

- **The fleet board spends the whole window.** The checkpoint summary was
  capped at 44 characters — a tmux status bar's column budget, kept after the
  status bar was deleted — and now takes whatever the fixed fields leave, so a
  wider terminal buys more of the sentence instead of more blank space. (The tab
  label's own width moved with the container name — see the naming entry above.)
  And the board is
  now a block at the top of the window rather than a fixed number of rows: the
  tail line (`+N more`, `👀N seen`, PRs) follows the last agent instead of being
  pinned to the bottom with blank rows between. `--lines` is a budget, not a
  shape.
- **The shipped `dotfiles/settings.json` now matches how the kit is actually
  run**, folding in what had accumulated as local drift on the reference
  runtime: all six multiplai skill packs enabled alongside `multiplai-context`,
  `model: "claude-opus-5[1m]"`, deep-research disabled at both layers
  (`skillOverrides` + `permissions.deny` — the SDK pipeline is invoked
  explicitly, not as a skill), and multiplai-context options `enable_costs`,
  `memory_router: "llm"`, `checkpoint_timeout_s: 480`. Also
  `remoteControlAtStartup: false`, `agentPushNotifEnabled: true`, and
  `policy-limits.json` gains `"monitoring_notice": null`. Less noise in
  `git status` on a live runtime; override any of these locally as before.

- **Runtime state files no longer show as untracked churn.**
  `dotfiles/projects` and `dotfiles/todos` are symlinks into cc-state on live
  machines, and the old `dir/`-style ignore patterns do not match symlinks;
  both lost the trailing slash, and `dotfiles/.timezone` (statusline timezone
  marker) is now ignored too.

- **The kit now hands off instead of compacting.** Native auto-compaction is
  disabled in the shipped `dotfiles/settings.json` (`DISABLE_AUTO_COMPACT=1`
  and `autoCompactEnabled: false`), reversing the previous default of steering
  it to fire early. Compaction replaces your conversation with a lossy summary,
  costs a visible pause and a full summarization call each time, and degrades
  over successive cycles — while the `multiplai-context` checkpoint system is
  already keeping a structured record of the session's working state. The new
  loop: checkpoint in the background → handoff advice at 200K → prompts refused
  at 250K → you `/clear` → the fresh window is seeded from the checkpoint.

  **You will notice this**: long sessions now stop and ask for a `/clear`
  instead of silently compacting. Slash commands are never blocked, and
  `!keepgoing` in a prompt overrides the stop for one refresh band. Manual
  `/compact` is unaffected.

  To restore the old behaviour, remove the two disable settings and put
  `CLAUDE_CODE_AUTO_COMPACT_WINDOW` / `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` back in
  the `env` block; the plugin detects which mode is active. To keep compaction
  off but make the handoff advisory rather than enforced, set
  `checkpoint_hard_stop_tokens` to `0`. Both documented in README →
  "Context: the kit hands off, it does not compact".

- **Shipped plugin option `checkpoint_hard_stop_tokens: "250000"`.** Requires
  `multiplai-context` 0.32.0+; on older plugin versions the option is ignored
  and sessions stay advisory-only.

- Removed `CLAUDE_CODE_AUTO_COMPACT_WINDOW` and `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE`
  from the shipped env block. They only ever fed the auto-compaction trigger,
  so with it disabled they are inert — and the window value in particular reads
  like a context cap it never was (the real threshold is the minimum of that
  setting and the model's own context window).

### Fixed

- **A typo'd model or effort ceiling no longer reaches the API.**
  `model_resolver.py` returned an unrecognized `MULTIPLAI_MODEL` string
  verbatim whenever it downgraded a request — the typo then travelled to the
  API as a model id and failed as a 404, the worst place to learn about a
  config error. Ceilings naming no known tier now fall back to the default
  ceiling with a stderr note (which run-hook-python routes to
  `hook-errors.log`); `resolve_effort(None)` returns the default effort
  instead of raising.

- **`log_utils.py` no longer dies on import when
  `CLAUDE_MULTIPLAI_HOME` is unwritable.** The module-scope `mkdir` is now
  best-effort; `setup_logging` keeps the loud failure for callers that
  actually need the log directory. Previously every hook and plugin skill
  that merely imported the module crashed.

- **Log-retention config is read the same way everywhere.** `log_utils.py`'s
  lightweight conf reader now drops inline `#` comments and refuses negative
  values, matching `run-hook-python`'s parser — a value like `7  # one week`
  used to fail `int()` and silently land on the default. `run-hook-python`
  also exports `MULTIPLAI_LOG_RETENTION_DAYS`, so hooks it launches read the
  conf through one parser instead of two.

- **The guard's deny-on-failure message now names a guard crash as a cause**
  and points at `runtime/logs/guard-destructive.log` alongside
  `hook-errors.log`. The deny-on-crash behaviour itself is unchanged and
  intentional: only a verdict may let a command through.

- **`gh-tok` now bounds the mint itself, on both routes.** `ssh -o
  ConnectTimeout=10` bounds only the TCP connect — a bridge that accepts and
  then stalls held the mint (and the hook waiting on it) indefinitely, and the
  bare-Mac route had no bound at all. Both routes now run under the same
  bounded-execution idiom the App hooks use for the store call (GNU `timeout`,
  perl-alarm fallback on a coreutils-free Mac). Failure semantics unchanged:
  nothing on stdout, diagnosis on stderr, non-zero exit.

- **`validate-syntax.sh` no longer goes silent on unexpected parse failures.**
  Under `set -euo pipefail`, the message probe caught only the expected
  exception class (`json.JSONDecodeError` / `yaml.YAMLError`); anything else —
  demonstrated with a non-UTF-8 `.json` file — killed the `ERROR=$(...)`
  assignment before `emit_error` ran: exit 1, empty stderr, the model never
  told the file it just wrote is broken. Each format is now parsed exactly
  once by a probe that prints the diagnosis and exits non-zero, captured with
  `|| true` and a bare `except Exception` fallback. The hook also gains its
  first test suite (`evals/unit/test_validate_syntax.py`).

- **`NotebookEdit` results are now syntax-checked too.** The PostToolUse
  matcher in `dotfiles/settings.json` was `Write|Edit`, and the hook only read
  `file_path`; it now also matches `NotebookEdit`, reads `notebook_path`, and
  validates `.ipynb` files as the JSON they are.

- **The guard's SQL rule no longer fires on prose.** `DROP TABLE` in a commit
  message, an `echo`, or a heredoc-written migration file was denied — the
  false-positive class that trains whoever hits it to disable the hook. The
  rule now requires a SQL client in the same segment (`psql`, `mysql`,
  `sqlite3`, `mongosh`, `clickhouse-client`, `bq`, `manage.py dbshell`);
  `psql -c 'DROP TABLE foo'` is still denied.

- **The guard hook entry in `dotfiles/settings.json` now carries
  `"timeout": 10`** like the other hook entries, so a wedged guard cannot
  hold a Bash call for the harness's much longer default hook timeout.

- **The fleet board can now label a session it did not watch start.** The pane
  map was a launch-time record: `claude.sh` wrote the entry for the pane it was
  launching in and carried every other tab forward by `grep`-ing the file it had
  written last time, so an entry could be *preserved* but never acquired.
  Anything already running when the map was created — or when the feature first
  shipped — was permanently stuck showing its container name, because its
  launcher was long past the only moment that knew which pane it was in. On
  2026-08-08 that was three of four live containers.

  The map is now a live `tmux list-panes -a` query over the `@cc` pane stamps,
  re-run by the launcher at both of its usual points *and* by `fleet-watch`
  before every redraw. A pane missing yesterday appears at the next tick; a
  renamed tab relabels within one frame; there is no migration and no repair
  path, because there is nothing accreted left to repair. Sessions started
  before this shipped carry no stamp and still need a relaunch — that is the one
  case nothing can reach.

  Two guards keep it from being worse than what it replaced: `fleet-watch` run
  **outside tmux** does not write at all (`list-panes -a` enumerates one server,
  and a plain terminal has no claim on which), and entries belonging to a
  **different tmux server** are carried forward untouched rather than dropped or
  relabelled — pane ids are recycled per server.

- **`fleet-watch` drew an 80×24 board into whatever size terminal you gave
  it.** `draw()` measured the window with `tput`, but it is only ever called as
  `board=$(draw)` — inside a command substitution stdout is a pipe, so `tput`
  has nothing to measure and answers with terminfo's `lines#24` / `cols#80`. In
  a 165×30 terminal that clipped every summary at the 80th column and left the
  tail line stranded on row 23, halfway up the screen. The size now comes from
  `stty size </dev/tty`, which asks the terminal rather than stdout, with
  `tput` and then the built-in constants behind it. The existing size tests
  could not have caught this: they export `LINES`/`COLUMNS`, which `tput` reads
  before asking anything.
- **The board's rows did not line up.** `✋` and `👀` are two columns wide and
  `●` and `⚠` are one, and the marker was joined to the row without padding —
  so every working row sat one column left of every needs-you row, all the way
  down the board.
- **A renamed tmux tab kept its old name on the board.** The rename hook was
  working; `fleet.json` was not being rewritten. It is a cache the plugin
  produces in a container at SessionStart, so nothing on the host recomputes
  it, and a five-second redraw loop re-rendered the same document with only the
  clock moving. `fleet-render.py` now re-reads the tab name — and only the tab
  name — from `tmux/panes.json` and `tmux/viewed/*` on every redraw. Both are
  host-side kit data files, so the renderer's stdlib-only boundary is
  unchanged. Everything else still ages with the document, and the header still
  says how old it is.
- **The tmux fleet board rendered permanently empty for everyone who followed
  the documented wiring.** `fleet-bar` and `fleet-viewed.sh` resolved the
  workspace via `$CLAUDE_CONFIG_DIR/.workspace`, but `setup.sh` writes that
  marker to `dotfiles/.workspace`, and `$CLAUDE_CONFIG_DIR` is exported by the
  launcher *for the container* — it does not exist in a tmux server's
  environment on the host. Both scripts now also read `.workspace` relative to
  their own location, which needs no environment at all. Both exit silently by
  contract, so the symptom was a blank status bar and a `viewed/` directory
  that was never created — indistinguishable from an idle fleet.
  `docs/TMUX-FLEET-BOARD.md` gains a resolution diagnostic for the same reason,
  since a hook's failure cannot announce itself. (The board's half of that
  problem is gone rather than documented — see *Removed*: `fleet-watch` prints
  its failures, so a blank board is no longer indistinguishable from an idle
  fleet.)

### Added

- **The launcher now records which tmux pane each container is in.** Launching
  from inside tmux writes `$WORKSPACE/.multiplai/data/tmux/panes.json` — one
  entry per running container, carrying its pane id, the tmux socket that
  issued that pane id, the tmux session, and — only if you pinned it — the
  window's name. This is the
  enabling half of an always-visible fleet board: nothing inside a container
  can see tmux (`$TMUX_PANE` is a fact about your Mac, and the plugin's hooks
  run in the container), so a session can only ever be labelled with the tab
  name you gave it if the launcher writes that down host-side.

  It **merges** — your other nine tabs stay in the file when one of them
  launches — and an entry lives only as long as `docker ps` still lists its
  container, which is what retires a tab you closed. Written at the same two
  moments as `live_containers.json`: once before the session container starts,
  once after it exits.

  The window name is recorded **only when `automatic-rename` is off** — i.e.
  when you typed that name yourself. Left on (tmux's default), `#{window_name}`
  is whatever tmux derived from the running process, so recording it would
  label the board `project@bash`; leaving it empty lets the reader fall back to
  the worktree/branch label it already builds.

  The socket path is not decoration, and it is stored **per entry**. tmux
  recycles pane ids per server, so `%12` means nothing on its own; a reader
  joining anything to a pane id must check the server first, and degrade to
  "unknown" rather than to the wrong session. Per-entry because the file merges
  across tabs, which may be on different servers — one top-level socket path
  would mislabel every carried-forward entry as this launch's. Best-effort throughout — no tmux, no `$TMUX_PANE`, no workspace, or
  a failing tmux or docker are silent no-ops, and none of them can change a
  session's exit status. Pinned by `evals/unit/test_claude_sh_panes.py`.

- **`dotfiles/scripts/fleet-viewed.sh` records when you last looked at a tab.**
  The other half of the fleet board: with the pane map saying *which* pane holds
  which container, this says *when* each pane was last on screen. Bound to
  tmux's `after-select-pane`, `after-select-window`, `client-focus-in` and
  `after-rename-window`, it writes a three-line marker per pane under
  `$WORKSPACE/.multiplai/data/tmux/viewed/<n>` — the view timestamp, the
  window's name at that moment, and the tmux socket that issued the pane id.
  The fleet renderer joins the two later to answer the only question that
  matters with six tabs running: which of these has done something since I last
  looked?

  It fires on **every** pane switch, so it is pure bash — no `python`, no `jq`,
  one batched `tmux display-message`, one `printf` — and that `display-message`
  is targeted at the pane tmux named in the hook, not at the client's current
  pane, which during a window switch is still the one you left. It also never prints: tmux
  puts a hook's stderr in your terminal, so a missing workspace, an unwritable
  data dir, a pane id that is not a pane id, or no tmux at all are all silent
  exits. Markers older than **7 days** are pruned on each run — pane ids climb
  for the life of a tmux server, and a marker's question is about the last few
  minutes.

  **You have to wire it up yourself.** The kit does not touch `~/.tmux.conf` —
  it is your file, outside the workspace, and invisible to a container-side
  session. The four lines to paste (and why `set-hook -g`, not `-ga`) are in
  `docs/TMUX-FLEET-BOARD.md`. Pinned by `evals/unit/test_fleet_viewed.py`.

- **A fleet board you can keep on screen.** `dotfiles/scripts/fleet-watch
  [interval]` draws the agents that have a claim on you, in a plain terminal,
  redrawn on a timer. Any key quits — a single keystroke, not a line. Redirected
  or piped it draws once and exits, so `fleet-watch > board.txt` is a snapshot.
  Nothing to wire up — it finds your workspace the way the marker script does.

  An interval of `0` is treated as junk and falls back to 5: `read -t 0` does
  not wait, so it would spin rather than redraw. A renderer that fails ends the
  run with its diagnostic on screen, instead of painting the error into a frame
  that the next redraw wipes. The cursor is restored on any exit, including the
  window simply being closed.

  ```
  FLEET 6 fronts · 2 need you · ⚠1 collision · upd 12s
  ✋ pi-eval          DolceEngine   18m  permission — bash
  ✋ fleet-readable   mktplace       3m  approve edit to fleet.py
  +3 more · 👀2 seen · ⚠fleet.py · PRs 3 14m
  ```

  Needs-you first, then unseen, then seen. Ages are recomputed every tick from
  the scan's own stamp, so the clock stays live between scans and the header
  says `⚠stale` once the data passes ten minutes.

  It never recommends, and it never hides silently — overflow is an explicit
  `+N more`, and `AGENTS.md` stays the full list. A section nobody scanned
  reads `not collected`, not `none`.

  Widths are measured in **terminal columns**, not characters: `✋` and `👀`
  are East_Asian_Wide and take two each, so a character-counted line ran a
  column long and lost its rightmost field off the right edge — the staleness
  marker, the one whose absence changes what the numbers to its left mean.

  **This shipped first as the tmux status bar itself** (`fleet-bar`, three
  `status-format` lines), and that version is gone — see *Removed*. The
  renderer, now `dotfiles/scripts/fleet-render.py`, keeps its budget: no
  scrolling, no wrapping, checkpoint text clipped at 44 columns. It is
  **stdlib-only and reads data files only** — no plugin imports, no `uv`, no
  shelling out to `fleet_status.py`, because the plugin's manifest and cache
  are container-writable. Pinned by `evals/unit/test_fleet_render.py` and
  `evals/unit/test_fleet_watch.py`.

  Unlike `fleet-viewed.sh`, which is a tmux hook and silent on every failure
  path, `fleet-watch` **prints** its failures: a person ran it and is looking
  at the output, and a silent one is indistinguishable from an idle fleet.

- **`multiplai-docker.py` is installed as a host tool on macOS.** The container
  release ships a host-side runner for pre-frozen Docker Compose stacks, letting
  a session start, inspect and tear down parallel named instances of allowlisted
  stacks over the existing SSH bridge (`multiplai-docker up dolce --instance
  wt1`). `setup.sh` now copies it into `~/.local/bin/` inside the same gated loop
  as `container-build-gateway.sh` and `multiplai-gh-token` — the host script and
  the gateway branch that allowlists it are two halves of one contract and must
  never ship from different generations. **After updating, each stack must be
  frozen once on the Mac** (`multiplai-docker freeze <name> -f <compose>…`); see
  the container repo's `docs/multiplai-docker.md`. No `authorized_keys` change is
  needed.

- **The statusline now shows plan usage limits and reasoning effort.** Two new
  segments — `5h 72% ⟳1h30m` (the session window, as time remaining) and
  `7d 52% ⟳Mon 06:00` (the weekly all-models window, as a weekday) — plus an
  abbreviated effort level (`lo`/`med`/`hi`/`xhi`/`max`). Both usage windows use
  the same green/yellow/red thresholds as the context percentage, so a limit
  about to bite looks like one. This is the same information `/usage` shows,
  without leaving the prompt.

  The data comes from `rate_limits` in the statusline payload (Claude Code
  2.1.80+), which carries **only** the combined five-hour and seven-day windows —
  there is no per-model split, so the Opus/Fable breakdown `/usage` renders
  cannot be reproduced here without a second, authenticated data source. The
  field is absent for non-subscribers and until the session's first API
  response, and `effort` is absent on models without the parameter; each segment
  simply doesn't render in those cases.

  Reset clock-times need a timezone, since containers run UTC: set
  `STATUSLINE_TZ`, or write a zone name to `$CLAUDE_CONFIG_DIR/.timezone`.
  Without either, the weekly reset reads in UTC. Pinned by
  `evals/unit/test_statusline.py`.

- **tmux tabs are now named after the session's container.** Launching from
  inside tmux renames the window to the container name — `claude-personal-05212125`,
  the *same* string the `multiplai-context` fleet view prints — so a tab and an
  `AGENTS.md` row match by eye instead of by lookup. The original name is
  restored when the session exits; a window tmux was auto-naming is handed back
  to `automatic-rename` rather than pinned to whatever it was called at launch.

  It is deliberately **not** the Claude session id: `/clear` mints a fresh
  session (one container in a real registry carried nine session UUIDs), so a
  session-named tab would rename itself mid-work and would need a host-side
  watcher polling the session registry for the whole run. The container is what
  the tab actually is — one tab, one `docker run`, one name, stable across every
  `/clear` inside it.

  Container mode only, and best-effort: `--local`, in-container bare sessions
  and `driver` all `exec` away (no EXIT trap could fire, so the tab would keep a
  dead session's name), and no tmux, no `$TMUX`, no `$TMUX_PANE` or a tmux that
  errors are silent no-ops. A tab name can never change a session's exit status.
  Pinned by `evals/unit/test_claude_sh_tmux.py`.

- **The launcher now records which containers are actually running**, so the
  fleet view can stop guessing. `claude.sh` writes `docker ps` names to
  `$WORKSPACE/.multiplai/data/live_containers.json` twice per launch — once
  before starting the session container, once after it exits. A session cannot
  observe its own death (a reboot, a closed terminal, a `docker kill` kills the
  hooks too), and the container has no docker to ask, so only the host can
  answer. With this, `multiplai-context` 0.22.0+ retires a session the moment
  its container is gone instead of waiting out a 12-hour quiet window; on one
  real registry that was 49 entries stuck in limbo. Parked sessions are never
  retired this way — parking is a stated intent, not an inference.

  Best-effort throughout: no docker, no `.multiplai/data/`, or a daemon that has
  gone away are silent no-ops, and none of them can change a session's exit
  status. Without the plugin the file is simply never read. This is a poll, not
  the exit-marker design dropped in 0.15.1 — a marker dies with the launcher and
  so covered nothing.

### Changed

- **The global tool-usage rules are now written from measurement, and the
  "never use Bash for file operations" rule is gone.** An audit of 111,780 real
  tool calls across 5,809 sessions found that rule was ignored in 99% of
  sessions — and was mostly wrong to ignore it *correctly*: 97% of shell greps
  are composite pipelines the `Grep` tool cannot express, and a bounded shell
  probe returns ~640 B where `Read` returns ~5.6 KB. `Read` alone accounts for
  72% of every byte of tool output that has ever entered a context window.

  `dotfiles/CLAUDE.md` now says what the old rule was reaching for — **bound
  your output** — plus five things the data actually supports: read a file
  whole only to work on it whole; `Read` before you `Edit` or `Write` (a shell
  read does not satisfy the harness guard, which bounced 206 edits and 55
  writes); never re-read a path already read this session (30.5% of reads were
  repeats, 41 MB of duplicate context); navigate code through the cheapest of
  three tiers rather than by reading whole files; and put independent tool
  calls in one message (only 16.5% of tool-using turns did).

  The navigation tiers are named with the numbers that justify them, measured
  on one 53.8 KB Python file: the harness's **`LSP` tool** (a deferred tool —
  `ToolSearch("select:LSP")`) answers "what is in this file" in ~350 B and has
  worked all along against the `pyright` and `typescript-language-server` the
  container image already ships; **`ast-grep`** returns a definition node in
  2.6 KB and covers the languages those two servers do not; and **`grep`**
  remains the cheapest answer to "where is this mentioned" at 264 B. The point
  is not that grep is bad — it is that reading a 53.8 KB file to find a
  function was never any of these.

  Also new, each from a measured failure: skills must be invoked by
  fully-qualified `plugin:skill` name (the sole cause of a 23% `Skill` failure
  rate), a `WebFetch` 403 is a signal to switch to `host-browser` rather than
  retry (483 measured 403s), and absolute paths beat `cd` (26% of Bash calls
  opened with one).

  The audit, its baselines, and the re-runnable extract/analyse scripts live in
  the user's workspace at `RESOURCES/claude-perf-analysis/`.

- **A tmux window you named yourself is no longer renamed.** The launcher used
  to take every tab, call it `claude-personal-06175625` for the session, and put
  the old name back on exit — including tabs you had deliberately named
  `pi-eval` or `notes`, which meant the whole session showed the one name you
  had already rejected. Now it only claims a window tmux is still auto-naming.
  `rename-window` is what turns `automatic-rename` off, so `off` is exactly the
  signal that a human claimed this tab; the launcher leaves it, and leaves the
  restore path inert too, so nothing is un-pinned on the way out. No config
  knob: the pane map above reads your real tab name back out of tmux, so a name
  you chose is better input to the fleet view than the container name ever was.
  A tab tmux is auto-naming behaves exactly as before.

- **The statusline dropped the session cost and shortened the model name and
  path** (`Opus 5 (1M context)` → `Opus 5 1M`, workspace root → `~`). Width is
  the binding constraint: everything past the terminal's last column is silently
  truncated, and the new usage segments are at the far right, so the line was
  landing at ~115 columns and losing exactly the part that was just added. It
  now fits in 80.

- **`reference/dev/` docs now document how they are actually loaded.** The old
  claim — "Claude Code agents automatically load relevant docs based on task
  triggers defined in the global CLAUDE.md" — was not true of anything
  executable: the table in `dotfiles/CLAUDE.md` is a hint to the model, and
  nothing read it. There are two real mechanisms, both in
  `multiplai-cc-mktplace` and both keyed on the project's manifests rather than
  on prompt wording: a per-session pointer block from the `multiplai-context`
  hook, and inlining into buildme's spec-generation prompts.

  `reference/dev/README.md` now describes all three paths (including which docs
  no stack map covers), and `dotfiles/CLAUDE.md` says what to do when the
  `DEV REFERENCES` block appears instead of asking Claude to remember to go
  looking.

  It also states **the renaming contract**: two maps in the marketplace repo
  name these files as literal strings and skip a name with no file on disk, so
  renaming a doc here without updating them silently drops it from every session
  and every build. That is not hypothetical — `django-best-practices.md` and
  `react-best-practices.md` were renamed in July and both keys resolved nothing
  until 2026-08-05.

### Fixed

- **The launcher misread `automatic-rename`, and got two opposite things wrong
  with it.** `tmux_capture_window` read the option with
  `show-window-options -v`, which returns the **window-local** value and prints
  nothing when it was only ever set globally — which is how anyone with
  `set -g automatic-rename off` in `~/.tmux.conf` has it. It now reads
  `show-options -w -Av`, the *resolved* value: the window-local setting if there
  is one, else the global, else tmux's own default.

  Three flags claim to answer this and only one does. Verified on tmux 3.4 with
  a global `off` and a window-local `on`: `show-window-options -v` → `on`
  (window-local only — and **empty** when only the global was ever set),
  `show-window-options -gv` → `off` (the global set only — blind to the local
  override), `show-options -w -Av` → `on`. Note `-A` is rejected by the
  `show-window-options` alias on 3.4 (`unknown flag -A`), so the resolved read
  has to be spelled `show-options -w`.

  The empty answer was read in both directions, so one misread option produced
  two opposite wrong answers:

  - **Your tab names were taken.** The rename guard fires when the option is
    *not* `off`, so it always fired: every tab you had deliberately named was
    renamed to the container name for the length of the session (restored on
    exit). The one state that means "a human typed this string" was invisible.
  - **…and never recorded.** `write_pane_map` records the window name only
    when the option *is* `off`, so it never did. Every entry in `panes.json`
    carried `"window": ""`, and the fleet board fell back to
    `claude-personal-07213856` for every agent instead of the tab name.

  A window set back to `automatic-rename on` under a global `off` is now
  handled correctly too: it is naming itself, so the launcher renames it and
  does **not** record its derived name as though a human chose it.

  The stub `tmux` in `evals/unit/test_claude_sh_tmux.py` and
  `test_claude_sh_panes.py` answered every scope identically, which is why the
  tests passed throughout. It now models the global set, the window-local
  override and the resolved read separately, and five cases pin the fix — two
  per direction, one on the mechanism.

- **The statusline's `~` abbreviation never applied.** `${cwd/#$HOME/~}`
  tilde-expands its *replacement*, so the collapsed path expanded straight back
  to `$HOME` — invisible, because the result was the string it started with. The
  replacement is now quoted. The workspace root is collapsed too (from
  `$WORKSPACE`, falling back to `$CLAUDE_CONFIG_DIR/.workspace`): in a container
  `$HOME` is `/home/agent` and never matches the host paths the payload reports.

- **Bare launches now make the same GitHub-auth decision as containerised
  ones.** The mode-selection block sat *after* every bare-mode `exec`, and
  `exec` replaces the process — so `--local`, launching from inside a
  container, and the Docker-missing fallback all skipped it entirely. Three
  consequences, all silent: a `.env` declaring both `GH_TOKEN` and
  `GH_TOKEN_APP` handed the session both, and `gh` prefers an environment PAT
  over the App credential the hooks store, so the session ran as the wrong
  GitHub identity with nothing said; the App-mode preflight checks never ran,
  so a misconfigured launch degraded at hook time instead of failing at launch
  with a usable message; and the `GH_TOKEN_KEYCHAIN` lookup never happened, so
  a profile relying on it launched unauthenticated. The decision now runs
  before any launch path forks.
- **A Keychain lookup no longer aborts the launcher when `USER` is unset.**
  The lookup passes `-a "$USER"` under `set -u`, which is fine from a login
  shell and fatal from cron or an SSH forced command. It falls back to
  `id -un`. Previously unreachable on the bare paths; reachable now that they
  run the same block.

- **The destructive-command guard no longer switches itself off in a fresh
  clone or worktree.** Every hook command in `dotfiles/settings.json` ended
  with `2>>$CLAUDE_MULTIPLAI_HOME/runtime/logs/hook-errors.log`, and the shell
  opens that redirect *before* running anything. `runtime/logs/` is created by
  `setup.sh`, so in a checkout where setup had never run the command died at
  `Directory nonexistent` and the hook never executed. A `PreToolUse` hook
  that errors is reported once and then ignored, so the practical effect was
  that **every Bash call in that session ran with the guard inert** — with one
  line of stderr on the first call and silence after. Sessions run
  `--dangerously-skip-permissions`, which makes this guard the only layer that
  can still refuse an unrecoverable command.

  Three changes, none of which is `|| true` on the failing line (that would
  hide the failure rather than fix it):

  - `run-hook-python` now creates `runtime/logs/` and redirects its own stderr
    there, so a Python hook needs no shell redirect and cannot fail for a
    logging reason.
  - The guard is invoked through a new `dotfiles/hooks/guard-destructive.sh`,
    which **denies** if the guard could not run at all. The guard exits 0 on
    every path by contract, so a non-zero exit means it never reached a
    verdict — and a verdict is the only thing that may let a command through.
    Bash then fails loudly instead of silently going unguarded.
  - The remaining hook commands that still log via a redirect create the
    directory first.

  Pinned by `evals/unit/test_guard_hook_wiring.py`.

- **The post-exit drain container actually drains now.** Closing the last tab
  of the day was supposed to produce that day's diary entry and learnings via a
  disposable drain container; instead the container started, failed on
  `import multiplai_core`, and exited — every time, since 2026-08-04. The
  command ran `uv run --no-project`, which disables resolution of the plugin's
  `scripts/pyproject.toml`, the very file that provides that package. Nothing
  surfaced it: the container's output is discarded and its exit status
  deliberately ignored so a drain can never change what the launcher reports.
  It now runs `uv run --project <install_path>/scripts`, the member-directory
  form that resolves both in-repo and on an installed plugin.

  This is the launcher half of the same defect in the plugin's own in-code
  spawn sites (`multiplai-cc-mktplace#135`); both halves are needed for
  deferred extraction to run at all. Pending markers were not lost — they queue
  up and drain once both are in place.

### Removed

- **The fleet board is no longer the tmux status bar.** `dotfiles/scripts/fleet-bar`
  and its test are gone; `fleet-bar-render.py` is renamed
  `dotfiles/scripts/fleet-render.py` and now has one caller, `fleet-watch`.
  If you wired the board into `~/.tmux.conf`, remove the `status-format` lines
  and put `status` back where you had it — and note that **sourcing the file
  again does not retract them**: a running tmux server needs
  `tmux set -g status on` and `tmux set -gu 'status-format[N]'` for each line.

  The bar was the better placement on paper — ambient, in every window, with
  `status-interval` as a free scheduler and nothing to start or supervise. It
  did not survive contact: three rows of every window, permanently, to show
  two agents; a hard cap of five status lines; and a `#()` job that can neither
  wrap nor scroll, so half a wide terminal sat empty while the checkpoint text
  was cut at 44 characters. The board wants height, and a status bar is the one
  place that cannot give it any.

  Going with it: the pre-rendered `bar.txt` cache and its `mkdir` lock, which
  existed because tmux called the script once per line per tick per attached
  client. One process redrawing on its own timer needs neither.

- **The kit no longer ships an output style.** `dotfiles/output-styles/assistant.md`
  (an "Assistant" mode that turned off the coding defaults) is gone, and with it
  the directory. Nothing in the kit consumed it — `setup.sh` never referenced it
  and `settings.json` never selected it; it was only an entry in Claude Code's
  `/output-style` picker. If you had it selected, pick another style; the
  statusline still reports whatever style is active, from any source.

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
