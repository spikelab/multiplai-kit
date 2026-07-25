#!/bin/bash
# setup.sh — One-time setup for multiplai-kit
#
# Creates workspace directories, installs Python dependencies, configures the
# kit to point at your workspace (via settings.local.json), installs the
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

HAS_DOCKER=false
if command -v docker &>/dev/null && docker info >/dev/null 2>&1; then
  HAS_DOCKER=true
fi

echo "Setting up multiplai-kit..."
echo "  Workspace: $WORKSPACE"
echo "  Name: $GIT_AUTHOR_NAME"
echo "  Docker: $( $HAS_DOCKER && echo 'available' || echo 'NOT FOUND' )"
echo ""

if ! $HAS_DOCKER; then
  echo "================================================================"
  echo "  WARNING: Docker not found or not running."
  echo ""
  echo "  Container mode (the default) will not work."
  echo "  ./claude.sh will fall back to bare mode without a sandbox."
  echo "  This means Claude runs directly on your host with full"
  echo "  filesystem access and permission prompts enabled."
  echo ""
  echo "  To enable container mode later:"
  echo "    1. Install Docker"
  echo "    2. Re-run ./setup.sh (it fetches container/ and builds the image)"
  echo "================================================================"
  echo ""
fi

# --- Step 1: Create workspace directories ---
TOTAL_STEPS=$( $HAS_DOCKER && echo 9 || echo 8 )
STEP=1

echo "[$STEP/$TOTAL_STEPS] Creating workspace directories..."
# .multiplai/ is the multiplai-context plugin's state root: memory (you edit),
# diary/learnings/now (auto-captured), data (runtime: catalogs, logs, plugin venv).
mkdir -p "$WORKSPACE"/{INBOX,PROJECTS,PROJECTS/plans,RESOURCES,.multiplai/{memory,diary,learnings,now,data}}

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
# The shipped settings.json carries empty path placeholders. Rather than
# rewriting that tracked file (which would leave the tree permanently dirty and
# make `git pull` updates conflict), write the machine-local paths to
# settings.local.json — a gitignored overlay. Identity lives in the memory
# profile (never sed'd in).
#
# CAUTION: at the user level (CLAUDE_CONFIG_DIR), Claude Code does NOT apply
# the `env` block from settings.local.json — only settings.json's env lands
# (verified empirically on CLI 2.1.207, 2026-07-14; settings.local.json is a
# project-level overlay for env). Anything that must reach the process
# environment (e.g. CLAUDE_CODE_AUTO_COMPACT_WINDOW steering) belongs in the
# tracked settings.json. Only pluginConfigs paths go here.
STEP=$((STEP + 1))
echo "[$STEP/$TOTAL_STEPS] Configuring plugin options for this workspace..."
LOCAL_SETTINGS="$DOTFILES_DIR/settings.local.json"
[ -f "$LOCAL_SETTINGS" ] || echo '{}' > "$LOCAL_SETTINGS"
jq --arg ws "$WORKSPACE" \
   --arg skills "$DOTFILES_DIR/skills" \
   --arg res "$WORKSPACE/RESOURCES" \
   '.pluginConfigs["multiplai-context@multiplai"].options.workspace_dir = $ws
    | .pluginConfigs["multiplai-context@multiplai"].options.skills_dir = $skills
    | .pluginConfigs["multiplai-context@multiplai"].options.resources_dir = $res' \
   "$LOCAL_SETTINGS" > "$LOCAL_SETTINGS.tmp" && mv "$LOCAL_SETTINGS.tmp" "$LOCAL_SETTINGS"
echo "  workspace_dir  = $WORKSPACE   (written to settings.local.json)"
echo "  skills_dir     = $DOTFILES_DIR/skills"
echo "  resources_dir  = $WORKSPACE/RESOURCES"

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
  CONTAINER_REF="${CONTAINER_REF:-v0.5}"
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
  GATEWAY_SRC="$SCRIPT_DIR/container/container-build-gateway.sh"
  GATEWAY_DST="$HOME/.local/bin/container-build-gateway.sh"
  if [ "$(uname -s)" = "Darwin" ] && [ -f "$GATEWAY_SRC" ]; then
    if [ "$CONTAINER_AT_PIN" = true ] && [ "$BUILD_OK" = true ]; then
      mkdir -p "$HOME/.local/bin"
      if ! cmp -s "$GATEWAY_SRC" "$GATEWAY_DST" 2>/dev/null; then
        cp "$GATEWAY_SRC" "$GATEWAY_DST"
        chmod +x "$GATEWAY_DST"
        echo "  Installed host SSH gateway → ~/.local/bin/container-build-gateway.sh ($CONTAINER_REF)"
      fi
    elif ! cmp -s "$GATEWAY_SRC" "$GATEWAY_DST" 2>/dev/null; then
      echo "  WARNING: NOT installing the host SSH gateway — container/ is not verified"
      echo "           at $CONTAINER_REF (re-pin failed or unmanaged checkout) or the image"
      echo "           build failed. The gateway at $GATEWAY_DST"
      echo "           may be stale vs the released tooling; fix the issue above and re-run ./setup.sh."
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
  echo "Run ./claude.sh to start Claude Code (bare mode — no Docker)."
  echo "Install Docker and re-run setup.sh to enable container mode."
fi
if ! git -C "$WORKSPACE" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo ""
  echo "Optional: Set up git in your workspace"
  echo "  cd $WORKSPACE && git init"
  echo "  git config user.name \"$GIT_AUTHOR_NAME\""
  echo "  git config user.email \"${GIT_AUTHOR_EMAIL:-your@email.com}\""
fi
