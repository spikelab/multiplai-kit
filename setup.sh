#!/bin/bash
# setup.sh — One-time setup for multiplai-kit
#
# Creates workspace directories, installs Python dependencies, configures the
# kit to point at your workspace (via dotfiles/settings.json), installs the
# Multiplai plugins, and builds the Docker image if Docker is available.
# Identity is NOT sed'd into shipped files — it lives in the memory profile.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DOTFILES_DIR="$SCRIPT_DIR/dotfiles"
ENV_FILE="$SCRIPT_DIR/.env"

# --- Load .env ---
if [ ! -f "$ENV_FILE" ]; then
  echo "Error: .env file not found."
  echo "Copy .env.example to .env and fill in your details:"
  echo "  cp .env.example .env"
  exit 1
fi

# shellcheck source=/dev/null
source "$ENV_FILE"

# Expand ~ and $HOME in WORKSPACE, strip trailing slash
WORKSPACE=$(eval echo "${WORKSPACE:-}")
WORKSPACE="${WORKSPACE%/}"

if [ -z "${WORKSPACE:-}" ]; then
  echo "Error: WORKSPACE not set in .env"
  exit 1
fi

# Catch the shipped placeholder before mkdir fails with a raw permission error.
case "$WORKSPACE" in
  */youruser/*|/Users/youruser*)
    echo "Error: WORKSPACE still points at the placeholder ($WORKSPACE)."
    echo "  Edit WORKSPACE in .env to your real workspace path first."
    exit 1
    ;;
esac

if [ -z "${GIT_AUTHOR_NAME:-}" ]; then
  echo "Error: GIT_AUTHOR_NAME not set in .env"
  exit 1
fi

# --- Pre-flight checks ---
MISSING_DEPS=""
for cmd in git jq python3 curl; do
  if ! command -v "$cmd" &>/dev/null; then
    MISSING_DEPS="$MISSING_DEPS $cmd"
  fi
done
if [ -n "$MISSING_DEPS" ]; then
  echo "Error: Missing required tools:$MISSING_DEPS"
  echo ""
  if [[ "$(uname)" == "Darwin" ]]; then
    echo "Install with Homebrew:"
    echo "  brew install$MISSING_DEPS"
  else
    echo "Install with your package manager, e.g.:"
    echo "  apt-get install$MISSING_DEPS"
  fi
  exit 1
fi

# Check for uv or pip
if ! command -v uv &>/dev/null && ! command -v pip3 &>/dev/null; then
  echo "Error: Neither uv nor pip3 found."
  echo "Install uv (recommended): curl -LsSf https://astral.sh/uv/install.sh | sh"
  exit 1
fi

# Check for the claude CLI (needed on the host for plugin install + bare mode;
# the container ships its own copy, so this is a warning, not an error)
if ! command -v claude &>/dev/null; then
  echo "Warning: 'claude' CLI not found on the host."
  echo "  Plugin install will be deferred to your first session (claude.sh will remind you)."
  echo "  Install with: npm install -g @anthropic-ai/claude-code"
  echo ""
fi

# Check for ripgrep (used by Claude Code)
if ! command -v rg &>/dev/null; then
  echo "Warning: ripgrep (rg) not found — Claude Code needs it for search."
  if [[ "$(uname)" == "Darwin" ]]; then
    echo "  Install with: brew install ripgrep"
  else
    echo "  Install with: apt-get install ripgrep"
  fi
  echo ""
fi

# Three states, not two. Whether docker is INSTALLED is a durable property of
# the host; whether the daemon is UP right now is not, and collapsing them made
# this script promise bare mode to someone who had simply not started Docker
# Desktop yet — after which `claude.sh` (which tested only for the binary) went
# to container mode anyway and died on a missing image. Keep them apart here and
# in the launcher, and say which one you hit.
DOCKER_INSTALLED=false
HAS_DOCKER=false
if command -v docker &>/dev/null; then
  DOCKER_INSTALLED=true
  docker info >/dev/null 2>&1 && HAS_DOCKER=true
fi

if $HAS_DOCKER; then
  _docker_state='available (container mode)'
elif $DOCKER_INSTALLED; then
  _docker_state='installed, but the daemon is not running'
else
  _docker_state='not installed (bare mode)'
fi

echo "Setting up multiplai-kit..."
echo "  Workspace: $WORKSPACE"
echo "  Name: $GIT_AUTHOR_NAME"
echo "  Docker: $_docker_state"
echo ""

# Bare mode is a supported rung of the install ladder, not a degraded fallback:
# claude runs directly on this host with permission prompts on (the prompts are
# the boundary there). Container mode is the next rung up — it adds the sandbox,
# which is what makes skip-permissions safe. Say which rung this install is;
# don't dress a supported configuration up as a failure — and say what the next
# rung buys, or the reader has no basis for choosing between them.
if $DOCKER_INSTALLED && ! $HAS_DOCKER; then
  echo "Docker is installed but the daemon is not running — skipping the image build."
  echo ""
  echo "  This is a stopped daemon, not a missing one, so setup is NOT configuring"
  echo "  bare mode: ./claude.sh will still choose container mode on this host and"
  echo "  will tell you to start Docker rather than launch unsandboxed."
  echo ""
  echo "  Start Docker (Docker Desktop, OrbStack, or 'sudo systemctl start docker'),"
  echo "  then re-run ./setup.sh to fetch container/ and build the image."
  echo "  To run without a sandbox in the meantime: ./claude.sh --local"
  echo ""
elif ! $HAS_DOCKER; then
  echo "Docker is not installed — setting up for bare mode."
  echo ""
  echo "  Bare mode is a supported way to run the kit: ./claude.sh launches"
  echo "  Claude Code directly on this host, with your whole filesystem in reach."
  echo "  Permission prompts stay on and are the only boundary there is."
  echo ""
  echo "  Container mode adds a sandbox that bounds what a session can touch."
  echo "  To move up to it:"
  echo "    1. Install Docker"
  echo "    2. Re-run ./setup.sh (it fetches container/ and builds the image)"
  echo ""
fi

# --- Step 1: Create workspace directories ---
TOTAL_STEPS=$( $HAS_DOCKER && echo 9 || echo 8 )
STEP=1

echo "[$STEP/$TOTAL_STEPS] Creating workspace directories..."
# .multiplai/ is the multiplai-context plugin's state root: memory (you edit),
# diary/learnings/now (auto-captured), data (runtime: catalogs, logs, plugin venv).
# ARTIFACTS/ is where a finished piece of work is kept — an investigation, a
# measurement, a published artifact. INBOX/ is scratch and is gitignored, so
# anything that must survive has to leave it.
mkdir -p "$WORKSPACE"/{INBOX,PROJECTS,RESOURCES,ARTIFACTS,.multiplai/{memory,diary,learnings,now,data}}

# --- Step 2: Copy memory templates ---
STEP=$((STEP + 1))
echo "[$STEP/$TOTAL_STEPS] Setting up memory files..."
MEMORY_DIR="$WORKSPACE/.multiplai/memory"
mkdir -p "$MEMORY_DIR"

# Only copy templates if memory files don't already exist
for template in "$SCRIPT_DIR/workspace-scaffold/memory/"*.md; do
  basename=$(basename "$template")
  target="$MEMORY_DIR/$basename"
  if [ ! -f "$target" ]; then
    cp "$template" "$target"
    echo "  Created $basename"
  else
    echo "  Skipped $basename (already exists)"
  fi
done

# --- Step 3: Copy workspace CLAUDE.md template ---
STEP=$((STEP + 1))
echo "[$STEP/$TOTAL_STEPS] Setting up workspace CLAUDE.md..."
WS_CLAUDE="$WORKSPACE/CLAUDE.md"
if [ ! -f "$WS_CLAUDE" ]; then
  cp "$SCRIPT_DIR/workspace-scaffold/CLAUDE.md.template" "$WS_CLAUDE"
  echo "  Created workspace CLAUDE.md"
else
  echo "  Skipped (already exists)"
  # An existing CLAUDE.md is the user's — never rewrite it. But a workspace that
  # predates ARTIFACTS/ now has the directory and no rule pointing at it, and may
  # still route plans to PROJECTS/plans/, which setup no longer creates. Say so
  # once; the edit is theirs to make.
  if ! grep -q "ARTIFACTS" "$WS_CLAUDE" 2>/dev/null; then
    echo "  NOTE: your CLAUDE.md has no ARTIFACTS/ routing rule."
    echo "        ARTIFACTS/ now holds records of completed work (tracked);"
    echo "        plans live in INBOX/ (gitignored). PROJECTS/plans/ is retired."
    echo "        Compare against: $SCRIPT_DIR/workspace-scaffold/CLAUDE.md.template"
  fi
fi

# --- Step 4: Create Python venv and install dependencies ---
STEP=$((STEP + 1))
echo "[$STEP/$TOTAL_STEPS] Setting up Python virtual environment..."
VENV_DIR="$SCRIPT_DIR/.venv"
if [ ! -d "$VENV_DIR" ]; then
  if command -v uv &>/dev/null; then
    uv venv "$VENV_DIR"
  else
    python3 -m venv "$VENV_DIR"
  fi
  echo "  Created venv at $VENV_DIR"
else
  echo "  Venv already exists at $VENV_DIR"
fi

# Use uv if available, fall back to pip. Arrays, not strings, so a venv path
# with spaces doesn't word-split into broken arguments.
if command -v uv &>/dev/null; then
  PIP=(uv pip)
  PIP_ARGS=(--python "$VENV_DIR/bin/python")
elif [ -f "$VENV_DIR/bin/pip" ]; then
  PIP=("$VENV_DIR/bin/pip")
  PIP_ARGS=()
else
  echo "  Error: No pip or uv available to install dependencies."
  echo "  Install uv (https://docs.astral.sh/uv/) or ensure pip is in the venv."
  exit 1
fi

echo "  Installing dependencies from requirements.txt..."
"${PIP[@]}" install ${PIP_ARGS[@]+"${PIP_ARGS[@]}"} --quiet -r "$SCRIPT_DIR/requirements.txt"

# Optional: mlx-whisper (macOS only, needs Metal GPU)
if [[ "$(uname)" == "Darwin" ]]; then
  echo "  Attempting mlx-whisper (optional, macOS only)..."
  "${PIP[@]}" install ${PIP_ARGS[@]+"${PIP_ARGS[@]}"} --quiet mlx-whisper 2>/dev/null || \
    echo "  Skipped mlx-whisper (install manually if needed)"
fi

# --- Step 5: Write workspace path to dotfiles ---
STEP=$((STEP + 1))
echo "[$STEP/$TOTAL_STEPS] Linking config to workspace..."
echo "$WORKSPACE" > "$DOTFILES_DIR/.workspace"
mkdir -p "$SCRIPT_DIR/runtime/logs/state"

# Create symlink: dotfiles/memory/ → $WORKSPACE/.multiplai/memory/
# (compat shim for docs/skills that reference $CLAUDE_CONFIG_DIR/memory/)
# Migration-safe (same idea as the cc-state links below): a stale symlink is
# dropped, but a REAL directory from an older install is MOVED aside rather
# than rm -rf'd — it may hold the user's memory files.
if [ -L "$DOTFILES_DIR/memory" ]; then
  rm -f "$DOTFILES_DIR/memory"
elif [ -e "$DOTFILES_DIR/memory" ]; then
  mv "$DOTFILES_DIR/memory" "$DOTFILES_DIR/memory.pre-link-backup"
  echo "  Note: moved existing dotfiles/memory → dotfiles/memory.pre-link-backup"
fi
ln -s "$MEMORY_DIR" "$DOTFILES_DIR/memory"
echo "  Linked dotfiles/memory → $MEMORY_DIR"

# Durable Claude Code state (session transcripts, command history, todos) lives
# in the workspace and is symlinked into the runtime — same idea as the memory
# link above. This keeps the runtime clone disposable: swap, rebuild, or delete
# it and your session history survives (it's in the workspace, not the clone).
# Sessions are workspace-scoped: two runtimes pointed at the same workspace share
# history; different workspaces stay separate.
# Migration-safe: if the clone already holds real data (an existing install being
# upgraded), MOVE it into the workspace rather than clobber it.
CC_STATE_DIR="$WORKSPACE/.multiplai/cc-state"
mkdir -p "$CC_STATE_DIR"
link_cc_state() {
  local name="$1" kind="${2:-dir}"
  local src="$DOTFILES_DIR/$name" dst="$CC_STATE_DIR/$name"
  [ -L "$src" ] && rm -f "$src"                          # stale link → drop, repoint below
  if [ -e "$src" ]; then                                  # real data in the clone
    if [ ! -e "$dst" ]; then mv "$src" "$dst"             #   → migrate it out to the workspace
    else mv "$src" "$src.pre-link-backup"; fi             #   both exist → keep durable, stash clone copy
  fi
  if [ ! -e "$dst" ]; then
    if [ "$kind" = file ]; then : > "$dst"; else mkdir -p "$dst"; fi
  fi
  ln -s "$dst" "$src"
}
link_cc_state projects
link_cc_state todos
link_cc_state history.jsonl file
echo "  Linked sessions/history/todos → $CC_STATE_DIR"

# Never commit session transcripts or skill runtime state to the workspace repo
# (bulky + may hold PII / message content / tokens). The data bucket also
# self-protects — multiplai-core drops a `*` .gitignore at .multiplai/data/ on
# first use — but add a workspace-level rule too (belt and braces).
WS_GITIGNORE="$WORKSPACE/.gitignore"
grep -qxF ".multiplai/cc-state/" "$WS_GITIGNORE" 2>/dev/null || echo ".multiplai/cc-state/" >> "$WS_GITIGNORE"
grep -qxF ".multiplai/data/" "$WS_GITIGNORE" 2>/dev/null || echo ".multiplai/data/" >> "$WS_GITIGNORE"

# INBOX/ is scratch, and the routing rules in CLAUDE.md.template tell both the
# user and Claude so — "temporary and gitignored". That has to be true here or
# the whole INBOX-vs-ARTIFACTS split is a claim the install does not honour:
# plans routed to INBOX/ would be committed by the first `git add -A`.
grep -qxF "INBOX/" "$WS_GITIGNORE" 2>/dev/null || echo "INBOX/" >> "$WS_GITIGNORE"

# --- Step 6: Seed .claude.json (onboarding state) ---
STEP=$((STEP + 1))
echo "[$STEP/$TOTAL_STEPS] Seeding Claude Code configuration..."
CLAUDE_JSON="$DOTFILES_DIR/.claude.json"
if [ ! -f "$CLAUDE_JSON" ]; then
  if [ -f "$HOME/.claude.json" ]; then
    cp "$HOME/.claude.json" "$CLAUDE_JSON"
    echo "  Copied from host ~/.claude.json"
  else
    echo '{"hasCompletedOnboarding": true, "bypassPermissionsModeAccepted": true}' > "$CLAUDE_JSON"
    echo "  Created minimal .claude.json (skips onboarding)"
  fi
else
  echo "  Skipped (already exists)"
fi

# --- Step 7: Point the multiplai-context plugin at this workspace ---
# These paths go in the TRACKED dotfiles/settings.json, because that is the only
# settings file Claude Code reads at user scope. `settings.local.json` is a
# project-scope concept: under CLAUDE_CONFIG_DIR nothing reads it, so writing
# there — which this step used to do — meant a fresh install silently ran with
# empty workspace_dir/skills_dir/resources_dir while setup printed that it had
# configured them (kit #34). The same mistake once looked like a feature: moving
# enabledPlugins into that file on 2026-08-05 disabled every plugin, and the
# running session did not notice because it had already loaded them.
#
# The cost is a dirty worktree — settings.json is tracked, so a configured
# runtime carries this drift into every `git pull`. That is a real cost and it
# is still cheaper than config that does not work; README ▸ "Updating the
# runtime" covers the stash/rebase. Identity is unaffected: it lives in the
# memory profile and is never sed'd in.
STEP=$((STEP + 1))
echo "[$STEP/$TOTAL_STEPS] Configuring plugin options for this workspace..."
SETTINGS="$DOTFILES_DIR/settings.json"
[ -f "$SETTINGS" ] || echo '{}' > "$SETTINGS"
jq --arg ws "$WORKSPACE" \
   --arg skills "$DOTFILES_DIR/skills" \
   --arg res "$WORKSPACE/RESOURCES" \
   '.pluginConfigs["multiplai-context@multiplai"].options.workspace_dir = $ws
    | .pluginConfigs["multiplai-context@multiplai"].options.skills_dir = $skills
    | .pluginConfigs["multiplai-context@multiplai"].options.resources_dir = $res' \
   "$SETTINGS" > "$SETTINGS.tmp" && mv "$SETTINGS.tmp" "$SETTINGS"

# Read back what Claude Code will actually see. A step that reports success for
# config it never delivered is the bug this whole block exists to fix, so the
# claim is checked rather than asserted.
_opts='.pluginConfigs["multiplai-context@multiplai"].options'
for _pair in "workspace_dir=$WORKSPACE" \
             "skills_dir=$DOTFILES_DIR/skills" \
             "resources_dir=$WORKSPACE/RESOURCES"; do
  _key="${_pair%%=*}"; _want="${_pair#*=}"
  _got=$(jq -r "$_opts.$_key // \"\"" "$SETTINGS")
  if [ "$_got" != "$_want" ]; then
    echo "  ERROR: $_key did not land in settings.json (read back: '${_got:-<empty>}')" >&2
    exit 1
  fi
  printf '  %-14s = %s\n' "$_key" "$_want"
done

# An older setup wrote these options to settings.local.json, where nothing reads
# them. Leaving the file in place is not harmless: its presence is what invites
# the "local overrides tracked" model in the first place. Move it aside rather
# than delete it — it is the user's file — and name its keys, never its values,
# because an env block there may hold a secret.
LOCAL_SETTINGS="$DOTFILES_DIR/settings.local.json"
if [ -f "$LOCAL_SETTINGS" ]; then
  echo "  Found $LOCAL_SETTINGS, which Claude Code does not read at user scope."
  echo "  Keys it held (names only): $(jq -r 'keys | join(", ")' "$LOCAL_SETTINGS" 2>/dev/null || echo '<unparseable>')"
  echo "  Nothing in it was ever applied. Moving it to settings.local.json.unused;"
  echo "  delete it yourself once you have looked."
  mv "$LOCAL_SETTINGS" "$LOCAL_SETTINGS.unused"
fi

# --- Step 8: Install the Multiplai plugins (best effort) ---
STEP=$((STEP + 1))
echo "[$STEP/$TOTAL_STEPS] Installing Multiplai plugins..."
if command -v claude &>/dev/null; then
  if CLAUDE_CONFIG_DIR="$DOTFILES_DIR" claude plugin marketplace add spikelab/multiplai-cc-mktplace 2>/dev/null \
     && CLAUDE_CONFIG_DIR="$DOTFILES_DIR" claude plugin install multiplai-context@multiplai 2>/dev/null; then
    echo "  Installed multiplai-context from the marketplace."
    echo "  Optional skill packs (install the ones you want):"
    echo "    claude plugin install multiplai-pm@multiplai"
    echo "    claude plugin install multiplai-writing@multiplai"
    echo "    claude plugin install multiplai-research@multiplai"
    echo "    claude plugin install multiplai-dev@multiplai"
    echo "    claude plugin install multiplai-media@multiplai"
  else
    echo "  Could not install from the marketplace (offline, or claude not logged in)."
    echo "  Install later from inside Claude Code:"
    echo "    /plugin marketplace add spikelab/multiplai-cc-mktplace"
    echo "    /plugin install multiplai-context@multiplai"
  fi
else
  echo "  'claude' CLI not found on the host — install plugins later from inside Claude Code:"
  echo "    /plugin marketplace add spikelab/multiplai-cc-mktplace"
  echo "    /plugin install multiplai-context@multiplai"
fi

# --- Step 9: Build Docker image (if Docker available) ---
# Container tooling lives in its own repo (spikelab/multiplai-container),
# fetched here at a pinned tag. Override CONTAINER_REPO/CONTAINER_REF in .env
# to track a fork or a different version.
if $HAS_DOCKER; then
  STEP=$((STEP + 1))
  IMAGE_NAME="${IMAGE_NAME:-claude-multiplai:local}"
  CONTAINER_REPO="${CONTAINER_REPO:-https://github.com/spikelab/multiplai-container}"
  CONTAINER_REF="${CONTAINER_REF:-v0.10}"
  echo "[$STEP/$TOTAL_STEPS] Building Docker image ($IMAGE_NAME)..."
  # CONTAINER_AT_PIN tracks whether container/ is verifiably a git checkout at
  # $CONTAINER_REF — the gateway install below is gated on it, so an offline
  # or failed re-pin can never silently ship a version-skewed host gateway.
  CONTAINER_AT_PIN=false
  if [ ! -f "$SCRIPT_DIR/container/build.sh" ]; then
    echo "  Fetching container tooling ($CONTAINER_REPO @ $CONTAINER_REF)..."
    if git clone --quiet --depth 1 --branch "$CONTAINER_REF" "$CONTAINER_REPO" "$SCRIPT_DIR/container"; then
      CONTAINER_AT_PIN=true
    else
      echo "  WARNING: could not fetch multiplai-container. Container mode disabled."
      echo "  Fetch manually: git clone $CONTAINER_REPO container"
    fi
  elif [ -d "$SCRIPT_DIR/container/.git" ]; then
    # Already fetched — re-running setup.sh aligns it to the pinned ref (the
    # kit's update path: git pull + ./setup.sh).
    CURRENT_REF=$(git -C "$SCRIPT_DIR/container" describe --tags --exact-match 2>/dev/null || echo "")
    if [ "$CURRENT_REF" = "$CONTAINER_REF" ]; then
      CONTAINER_AT_PIN=true
    else
      echo "  Updating container tooling ($CURRENT_REF → $CONTAINER_REF)..."
      if git -C "$SCRIPT_DIR/container" fetch --quiet --tags origin \
         && git -C "$SCRIPT_DIR/container" checkout --quiet "$CONTAINER_REF"; then
        CONTAINER_AT_PIN=true
      else
        echo "  WARNING: container update failed — still on $CURRENT_REF."
      fi
    fi
  else
    echo "  NOTE: container/ exists but is not a git checkout — leaving as-is."
    echo "  For managed updates: rm -rf container && re-run setup.sh"
  fi
  # Heads-up if a newer container release exists than we're pinned to. The pin
  # (CONTAINER_REF) advances when you pull a kit that bumped it — release.sh in
  # multiplai-container does that bump. Cheap remote query; skipped if offline.
  # `|| true` keeps this non-fatal under `set -euo pipefail`: an offline or
  # transient ls-remote failure must skip the heads-up, not abort setup. The
  # query is time-bounded so a black-hole network (SYN drop, no RST) can't
  # stall setup: `timeout 10` where available (Linux, macOS w/ coreutils),
  # else git's own low-speed abort (HTTP transports).
  if command -v timeout >/dev/null 2>&1; then
    NEWEST_REF=$(timeout 10 git ls-remote --tags --refs "$CONTAINER_REPO" 'v*' 2>/dev/null \
      | awk -F/ '{print $NF}' | sort -V | tail -1 || true)
  else
    NEWEST_REF=$(GIT_HTTP_LOW_SPEED_LIMIT=1 GIT_HTTP_LOW_SPEED_TIME=10 \
      git ls-remote --tags --refs "$CONTAINER_REPO" 'v*' 2>/dev/null \
      | awk -F/ '{print $NF}' | sort -V | tail -1 || true)
  fi
  if [ -n "$NEWEST_REF" ] && [ "$NEWEST_REF" != "$CONTAINER_REF" ] \
     && [ "$(printf '%s\n%s\n' "$CONTAINER_REF" "$NEWEST_REF" | sort -V | tail -1)" = "$NEWEST_REF" ]; then
    echo "  NOTE: newer container release available: $NEWEST_REF (pinned: $CONTAINER_REF)."
    echo "        Update the kit to move the pin: git pull && ./setup.sh"
  fi
  BUILD_OK=false
  if [ ! -f "$SCRIPT_DIR/container/build.sh" ]; then
    # The clone/fetch above failed — there's nothing to build. Don't mislead
    # the user into debugging a "build failure" that never started.
    echo "  WARNING: container tooling not present (fetch failed above). Container mode disabled."
    echo "  Fetch manually: git clone $CONTAINER_REPO container   # then re-run ./setup.sh"
  elif bash "$SCRIPT_DIR/container/build.sh"; then
    BUILD_OK=true
    echo "  Image built successfully."
  else
    echo "  WARNING: Docker build failed. Container mode will not work."
    echo "  Fix the build and re-run: cd container && ./build.sh"
  fi
  # Install the host-side SSH gateway from the pinned checkout so the live copy
  # the bridge invokes always matches the released tooling — never hand-copied
  # (a stale hand-copy once stranded a security fix on the host). macOS-only:
  # the bridge is the Mac host bridge (Xcode, mlx-whisper, real Chrome).
  # Deliberately AFTER the build gate, and gated on the re-pin: installing
  # from an unverified or unbuilt checkout could leave the host gateway
  # version-skewed vs the image the bridge serves.
  #
  # `multiplai-gh-token` and `multiplai-docker.py` ride the same path for the same
  # reason: each host script and the gateway branch that allowlists it are two
  # halves of one contract, and shipping them from different generations is
  # exactly the version skew these gates exist to prevent. One loop, so a further
  # host file can never be added on weaker terms by copy-paste.
  install_host_tool() {  # $1 = filename under container/
    local src="$SCRIPT_DIR/container/$1"
    local dst="$HOME/.local/bin/$1"
    [ -f "$src" ] || return 0
    if [ "$CONTAINER_AT_PIN" = true ] && [ "$BUILD_OK" = true ]; then
      mkdir -p "$HOME/.local/bin"
      if ! cmp -s "$src" "$dst" 2>/dev/null; then
        cp "$src" "$dst"
        chmod 755 "$dst"
        echo "  Installed host tool → ~/.local/bin/$1 ($CONTAINER_REF)"
      fi
    elif ! cmp -s "$src" "$dst" 2>/dev/null; then
      echo "  WARNING: NOT installing ~/.local/bin/$1 — container/ is not verified"
      echo "           at $CONTAINER_REF (re-pin failed or unmanaged checkout) or the image"
      echo "           build failed. The copy at $dst may be stale vs the released"
      echo "           tooling; fix the issue above and re-run ./setup.sh."
    fi
  }
  # The sandbox profile is not a tool: it is data the gateway reads, and it
  # belongs beside the other host-owned bridge state rather than on $PATH. Same
  # verification gate as install_host_tool, for the same reason — a gateway that
  # references a profile and a profile from a different generation are exactly
  # the version skew that gate exists to prevent.
  install_host_state() {  # $1 = filename under container/
    local src="$SCRIPT_DIR/container/$1"
    local dst="$HOME/.local/state/multiplai/$1"
    [ -f "$src" ] || return 0
    if [ "$CONTAINER_AT_PIN" = true ] && [ "$BUILD_OK" = true ]; then
      mkdir -p "$HOME/.local/state/multiplai"
      if ! cmp -s "$src" "$dst" 2>/dev/null; then
        cp "$src" "$dst"
        chmod 644 "$dst"
        echo "  Installed host state → ~/.local/state/multiplai/$1 ($CONTAINER_REF)"
      fi
    elif ! cmp -s "$src" "$dst" 2>/dev/null; then
      echo "  WARNING: NOT installing ~/.local/state/multiplai/$1 — container/ is not"
      echo "           verified at $CONTAINER_REF or the image build failed."
    fi
  }
  # macOS only, and deliberately so: these are the Mac host-bridge tooling
  # (Xcode builds, Keychain-backed App tokens, host Compose stacks).
  # On a Linux host nothing consumes them — sessions run without the bridge —
  # so the sane else-path is to install nothing, not to warn.
  if [ "$(uname -s)" = "Darwin" ]; then
    install_host_tool container-build-gateway.sh
    install_host_tool multiplai-gh-token
    install_host_tool multiplai-docker.py
    install_host_state confine.sb

    # Declare the workspace to the host SSH bridge (mktplace#15).
    #
    # The gateway confines path-taking commands to this directory. It cannot
    # take the value from the container — a boundary supplied by the side being
    # confined is not a boundary — so it reads this file, which only the host
    # can write. setup.sh is the right writer: it already knows $WORKSPACE and
    # already installs the gateway that reads it.
    #
    # Written unconditionally rather than only-if-absent: $WORKSPACE is the
    # value this run was configured with, so a workspace that moved should move
    # the declaration with it. Written even when the container checkout is not
    # verified, because a stale gateway with a correct workspace still behaves,
    # while a correct gateway with no workspace denies every build.
    if [ -n "${WORKSPACE:-}" ] && [ -d "$WORKSPACE" ]; then
      # mkdir inside the branch that writes, not above the `if`: a redirection
      # into a missing directory fails without stopping the script, which would
      # print "Declared workspace" over a file that does not exist.
      mkdir -p "$HOME/.local/state/multiplai"
      printf '%s\n' "$WORKSPACE" > "$HOME/.local/state/multiplai/workspace"
      chmod 644 "$HOME/.local/state/multiplai/workspace"
      echo "  Declared workspace to the host bridge → $WORKSPACE"
    else
      echo "  WARNING: \$WORKSPACE is unset or not a directory — the host bridge"
      echo "           will refuse path-taking commands (swift, xcodebuild, xcrun,"
      echo "           mlx-whisper, qmd) until ~/.local/state/multiplai/workspace"
      echo "           names an existing absolute path."
    fi
  fi
fi

echo ""
echo "Setup complete!"
echo ""
echo "First run: launch ./claude.sh, then run /multiplai-context:setup to"
echo "populate your memory files."
echo ""
if $HAS_DOCKER; then
  echo "Run ./claude.sh to start Claude Code in a container."
else
  echo "Run ./claude.sh to start Claude Code in bare mode: directly on this host,"
  echo "whole filesystem in reach, permission prompts the only boundary. To add the"
  echo "container sandbox later: install Docker and re-run ./setup.sh."
fi
if ! git -C "$WORKSPACE" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo ""
  echo "Optional: Set up git in your workspace"
  echo "  cd $WORKSPACE && git init"
  echo "  git config user.name \"$GIT_AUTHOR_NAME\""
  echo "  git config user.email \"${GIT_AUTHOR_EMAIL:-your@email.com}\""
fi
