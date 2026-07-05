#!/bin/bash
# setup.sh — One-time setup for multiplai-kit
#
# Creates workspace directories, installs Python dependencies,
# configures the kit to point at your workspace, personalizes
# the global CLAUDE.md, and builds the Docker image if Docker is available.

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
WORKSPACE=$(eval echo "$WORKSPACE")
WORKSPACE="${WORKSPACE%/}"

if [ -z "${WORKSPACE:-}" ]; then
  echo "Error: WORKSPACE not set in .env"
  exit 1
fi

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
  echo "    2. Run: cd container && ./build.sh"
  echo "================================================================"
  echo ""
fi

# --- Step 1: Create workspace directories ---
TOTAL_STEPS=$( $HAS_DOCKER && echo 10 || echo 9 )
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

# Use uv if available, fall back to pip
if command -v uv &>/dev/null; then
  PIP="uv pip"
  PIP_ARGS="--python $VENV_DIR/bin/python"
elif [ -f "$VENV_DIR/bin/pip" ]; then
  PIP="$VENV_DIR/bin/pip"
  PIP_ARGS=""
else
  echo "  Error: No pip or uv available to install dependencies."
  echo "  Install uv (https://docs.astral.sh/uv/) or ensure pip is in the venv."
  exit 1
fi

echo "  Installing dependencies from requirements.txt..."
$PIP install $PIP_ARGS --quiet -r "$SCRIPT_DIR/requirements.txt"

# Optional: mlx-whisper (macOS only, needs Metal GPU)
if [[ "$(uname)" == "Darwin" ]]; then
  echo "  Attempting mlx-whisper (optional, macOS only)..."
  $PIP install $PIP_ARGS --quiet mlx-whisper 2>/dev/null || \
    echo "  Skipped mlx-whisper (install manually if needed)"
fi

# --- Step 5: Write workspace path to dotfiles ---
STEP=$((STEP + 1))
echo "[$STEP/$TOTAL_STEPS] Linking config to workspace..."
echo "$WORKSPACE" > "$DOTFILES_DIR/.workspace"
mkdir -p "$SCRIPT_DIR/runtime/logs/state"

# Create symlink: dotfiles/memory/ → $WORKSPACE/.multiplai/memory/
# (compat shim for docs/skills that reference $CLAUDE_CONFIG_DIR/memory/)
if [ -L "$DOTFILES_DIR/memory" ] || [ -e "$DOTFILES_DIR/memory" ]; then
  rm -rf "$DOTFILES_DIR/memory"
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

# Never commit session transcripts to the workspace repo (bulky + may hold PII).
WS_GITIGNORE="$WORKSPACE/.gitignore"
grep -qxF ".multiplai/cc-state/" "$WS_GITIGNORE" 2>/dev/null || echo ".multiplai/cc-state/" >> "$WS_GITIGNORE"

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
# The shipped settings.json carries empty path placeholders; fill them from
# .env so the plugin routes memory/skills/resources for THIS machine. Identity
# lives in the memory profile (never sed'd into shipped files).
STEP=$((STEP + 1))
echo "[$STEP/$TOTAL_STEPS] Configuring plugin options for this workspace..."
SETTINGS="$DOTFILES_DIR/settings.json"
jq --arg ws "$WORKSPACE" \
   --arg skills "$DOTFILES_DIR/skills" \
   --arg res "$WORKSPACE/RESOURCES" \
   '.pluginConfigs["multiplai-context@multiplai"].options.workspace_dir = $ws
    | .pluginConfigs["multiplai-context@multiplai"].options.skills_dir = $skills
    | .pluginConfigs["multiplai-context@multiplai"].options.resources_dir = $res' \
   "$SETTINGS" > "$SETTINGS.tmp" && mv "$SETTINGS.tmp" "$SETTINGS"
echo "  workspace_dir  = $WORKSPACE"
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

# --- Step 8: Sync skill model/effort from multiplai.conf ---
STEP=$((STEP + 1))
echo "[$STEP/$TOTAL_STEPS] Syncing skill config from multiplai.conf..."
if ! compgen -G "$DOTFILES_DIR/skills/*/SKILL.md" > /dev/null; then
  echo "  No local skills yet — nothing to sync (skill packs come from the marketplace)."
elif CLAUDE_CONFIG_DIR="$DOTFILES_DIR" CLAUDE_MULTIPLAI_HOME="$SCRIPT_DIR" \
     "$VENV_DIR/bin/python" "$SCRIPT_DIR/scripts/sync_skill_config.py"; then
  echo "  Skill frontmatter synced."
else
  echo "  Warning: Could not sync skill config (see error above). Run manually:"
  echo "    CLAUDE_CONFIG_DIR=dotfiles python scripts/sync_skill_config.py"
fi

# --- Step 9: Build Docker image (if Docker available) ---
# Container tooling lives in its own repo (spikelab/multiplai-container),
# fetched here at a pinned tag. Override CONTAINER_REPO/CONTAINER_REF in .env
# to track a fork or a different version.
if $HAS_DOCKER; then
  STEP=$((STEP + 1))
  IMAGE_NAME="${IMAGE_NAME:-claude-multiplai:local}"
  CONTAINER_REPO="${CONTAINER_REPO:-https://github.com/spikelab/multiplai-container}"
  CONTAINER_REF="${CONTAINER_REF:-v0.2}"
  echo "[$STEP/$TOTAL_STEPS] Building Docker image ($IMAGE_NAME)..."
  if [ ! -f "$SCRIPT_DIR/container/build.sh" ]; then
    echo "  Fetching container tooling ($CONTAINER_REPO @ $CONTAINER_REF)..."
    if ! git clone --quiet --depth 1 --branch "$CONTAINER_REF" "$CONTAINER_REPO" "$SCRIPT_DIR/container"; then
      echo "  WARNING: could not fetch multiplai-container. Container mode disabled."
      echo "  Fetch manually: git clone $CONTAINER_REPO container"
    fi
  elif [ -d "$SCRIPT_DIR/container/.git" ]; then
    # Already fetched — re-running setup.sh aligns it to the pinned ref (the
    # kit's update path: git pull + ./setup.sh).
    CURRENT_REF=$(git -C "$SCRIPT_DIR/container" describe --tags --exact-match 2>/dev/null || echo "")
    if [ "$CURRENT_REF" != "$CONTAINER_REF" ]; then
      echo "  Updating container tooling ($CURRENT_REF → $CONTAINER_REF)..."
      git -C "$SCRIPT_DIR/container" fetch --quiet --tags origin \
        && git -C "$SCRIPT_DIR/container" checkout --quiet "$CONTAINER_REF" \
        || echo "  WARNING: container update failed — still on $CURRENT_REF."
    fi
  else
    echo "  NOTE: container/ exists but is not a git checkout — leaving as-is."
    echo "  For managed updates: rm -rf container && re-run setup.sh"
  fi
  if [ -f "$SCRIPT_DIR/container/build.sh" ] && bash "$SCRIPT_DIR/container/build.sh"; then
    echo "  Image built successfully."
  else
    echo "  WARNING: Docker build failed. Container mode will not work."
    echo "  Fix the build and re-run: cd container && ./build.sh"
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
