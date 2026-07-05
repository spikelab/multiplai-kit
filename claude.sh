#!/bin/bash
# claude.sh — Launch Claude Code
#
# Modes (in priority order):
#   --local             Bare mode: CLAUDE_CONFIG_DIR, no container, no skip-permissions
#   (inside container)  Bare mode: --dangerously-skip-permissions (container IS the sandbox)
#   (Docker available)  Container mode (default)
#   (no Docker)         Fallback bare mode with warning, no skip-permissions
#
# Additional flags:
#   --profile <name>    Load env.<name> for git identity + GH token (default: .env)
#   --shell             Container shell (bash instead of claude)
#
# Usage:
#   ./claude.sh                         # container, default profile
#   ./claude.sh --profile work          # container, work git identity
#   ./claude.sh --local                 # bare, host permissions apply
#   ./claude.sh --shell                 # container bash shell
#   ./claude.sh --profile work --shell  # work profile, bash shell

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DOTFILES_DIR="$SCRIPT_DIR/dotfiles"

# Kit project root — hooks and skills resolve runtime paths from this.
# Distinct from CLAUDE_CONFIG_DIR (dotfiles/) which is purely Claude Code's domain.
export CLAUDE_MULTIPLAI_HOME="$SCRIPT_DIR"

# --- Parse flags (extract ours, pass the rest through) ---
PROFILE=""
GCP_NAME=""
MODE=""
PASSTHROUGH_ARGS=()
CLAUDE_ONLY_ARGS=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --profile)
            PROFILE="$2"
            shift 2
            ;;
        --profile=*)
            PROFILE="${1#--profile=}"
            shift
            ;;
        --gcp)
            GCP_NAME="$2"
            shift 2
            ;;
        --gcp=*)
            GCP_NAME="${1#--gcp=}"
            shift
            ;;
        --local)
            MODE="local"
            shift
            ;;
        --shell)
            MODE="shell"
            shift
            ;;
        --plugin-dir|--add-dir)
            # claude-only flags: must not leak into `bash` in --shell mode
            CLAUDE_ONLY_ARGS+=("$1" "$2")
            shift 2
            ;;
        --plugin-dir=*|--add-dir=*)
            CLAUDE_ONLY_ARGS+=("$1")
            shift
            ;;
        *)
            PASSTHROUGH_ARGS+=("$1")
            shift
            ;;
    esac
done

# --- Load .env (base config) ---
if [ ! -f "$SCRIPT_DIR/.env" ]; then
    echo "Error: No .env file found."
    echo "  cp .env.example .env   # then fill in your values"
    exit 1
fi

# shellcheck disable=SC1091
source "$SCRIPT_DIR/.env"

# --- Load profile overlay (if specified) ---
if [ -n "$PROFILE" ]; then
    PROFILE_FILE="$SCRIPT_DIR/env.$PROFILE"
    if [ ! -f "$PROFILE_FILE" ]; then
        echo "Error: Profile '$PROFILE' not found at $PROFILE_FILE"
        echo "Available profiles:"
        ls "$SCRIPT_DIR"/env.* 2>/dev/null | sed 's/.*env\./  /' || echo "  (none)"
        exit 1
    fi
    # shellcheck disable=SC1090
    source "$PROFILE_FILE"
    echo "[claude] Profile: $PROFILE"
fi

# --- Load GCP overlay (orthogonal to --profile; sets GCP_KEY_FILE + GCP_PROJECT) ---
if [ -n "$GCP_NAME" ]; then
    GCP_FILE="$SCRIPT_DIR/env.gcp.$GCP_NAME"
    if [ ! -f "$GCP_FILE" ]; then
        echo "Error: GCP profile '$GCP_NAME' not found at $GCP_FILE"
        echo "Available GCP profiles:"
        ls "$SCRIPT_DIR"/env.gcp.* 2>/dev/null | sed 's/.*env\.gcp\./  /' || echo "  (none)"
        exit 1
    fi
    # shellcheck disable=SC1090
    source "$GCP_FILE"
    echo "[claude] GCP: $GCP_NAME"
fi

# Expand ~ and $HOME in WORKSPACE, strip trailing slash
WORKSPACE=$(eval echo "${WORKSPACE:-}")
WORKSPACE="${WORKSPACE%/}"
: "${WORKSPACE:?WORKSPACE must be set in .env}"
: "${GIT_AUTHOR_NAME:?GIT_AUTHOR_NAME must be set in .env}"

# --- Nag until the Multiplai plugins are installed ---
# setup.sh installs them when the host has the claude CLI; when it doesn't,
# this banner repeats at every launch until the one-time in-session install.
if ! grep -qs '"multiplai-context@multiplai"' "$DOTFILES_DIR/plugins/installed_plugins.json" 2>/dev/null; then
    echo "================================================================"
    echo "  Multiplai plugins are NOT installed yet."
    echo "  Run these once inside the session that's about to start:"
    echo "    /plugin marketplace add spikelab/multiplai-cc-mktplace"
    echo "    /plugin install multiplai-context@multiplai"
    echo "  Optional skill packs:"
    echo "    /plugin install multiplai-{pm,writing,research,dev,media}@multiplai"
    echo "  (This reminder disappears once multiplai-context is installed.)"
    echo "================================================================"
fi

# --strict-mcp-config: ignore account-level MCP integrations (claude.ai
# Gmail/Drive/Calendar/Miro). These are attached server-side to the
# Anthropic account and re-synced on every auth — local disabling never
# sticks. With no locally-configured MCP servers, this flag means "use
# zero MCP servers", killing the recurring OAuth-in-subprocess churn that
# also collapses nested SDK calls with exit 1. Verified 2026-05-19.
MCP_ISOLATION=(--strict-mcp-config)

# --- Explicit local mode ---
if [[ "$MODE" == "local" ]]; then
    export CLAUDE_CONFIG_DIR="$DOTFILES_DIR"
    exec claude "${MCP_ISOLATION[@]}" "${CLAUDE_ONLY_ARGS[@]+"${CLAUDE_ONLY_ARGS[@]}"}" "${PASSTHROUGH_ARGS[@]+"${PASSTHROUGH_ARGS[@]}"}"
fi

# --- Already inside a container? Run bare with full permissions ---
if [ -f /.dockerenv ] || grep -qsm1 'docker\|containerd' /proc/1/cgroup 2>/dev/null; then
    export CLAUDE_CONFIG_DIR="$DOTFILES_DIR"
    exec claude --dangerously-skip-permissions "${MCP_ISOLATION[@]}" "${CLAUDE_ONLY_ARGS[@]+"${CLAUDE_ONLY_ARGS[@]}"}" "${PASSTHROUGH_ARGS[@]+"${PASSTHROUGH_ARGS[@]}"}"
fi

# --- Docker not available? Warn and fall back to bare mode ---
if ! command -v docker &>/dev/null; then
    echo "WARNING: Docker not found — running without container sandbox."
    echo "  Host filesystem is NOT isolated. Permission prompts are active."
    echo "  Install Docker or build the image (cd container && ./build.sh) for sandboxed mode."
    echo ""
    export CLAUDE_CONFIG_DIR="$DOTFILES_DIR"
    exec claude "${MCP_ISOLATION[@]}" "${CLAUDE_ONLY_ARGS[@]+"${CLAUDE_ONLY_ARGS[@]}"}" "${PASSTHROUGH_ARGS[@]+"${PASSTHROUGH_ARGS[@]}"}"
fi

# --- Container mode (default) ---

CONTAINER_ARGS=("claude" "--dangerously-skip-permissions" "${MCP_ISOLATION[@]}" "${CLAUDE_ONLY_ARGS[@]+"${CLAUDE_ONLY_ARGS[@]}"}")
if [[ "$MODE" == "shell" ]]; then
    # bash doesn't understand --plugin-dir / --add-dir — drop CLAUDE_ONLY_ARGS.
    CONTAINER_ARGS=("bash")
fi

IMAGE_NAME="${IMAGE_NAME:-claude-multiplai:local}"

# Verify image exists
if ! docker image inspect "$IMAGE_NAME" >/dev/null 2>&1; then
    echo "Error: Docker image '$IMAGE_NAME' not found."
    echo "  Build it first: cd container && ./build.sh"
    exit 1
fi

# GH_TOKEN: env var > profile keychain key > default keychain key
GH_TOKEN_KEY="${GH_TOKEN_KEYCHAIN:-gh-token}"
if [ -z "${GH_TOKEN:-}" ]; then
    GH_TOKEN=$(security find-generic-password -a "$USER" -s "$GH_TOKEN_KEY" -w 2>/dev/null || true)
fi
if [ -z "${GH_TOKEN:-}" ]; then
    echo "Warning: No '$GH_TOKEN_KEY' found in Keychain. GitHub CLI will not be authenticated."
fi

# --- Ensure kit-venv volume is agent-writable ---
# New Docker named volumes are root-owned. The venv-sync entrypoint runs as
# the agent user and can't create the venv on a fresh volume. Fix ownership
# once (no-op when venv already exists — just a stat check inside the container).
docker run --rm \
    -v "kit-venv:$SCRIPT_DIR/.venv" \
    --user root \
    "$IMAGE_NAME" bash -c \
    "[ -x '$SCRIPT_DIR/.venv/bin/python3' ] || chown $(id -u):$(id -g) '$SCRIPT_DIR/.venv'" \
    >/dev/null 2>&1 || true

# --- Volume mounts ---
# Mount the kit root at its own absolute path so the runtime works wherever it
# lives — inside the workspace (legacy) or a separate dir outside it. Without
# this, a runtime outside $WORKSPACE loses kit-root files (notably multiplai.conf,
# read in-container by run-hook-python/log_utils) because only dotfiles/ + the
# venv were mounted. The kit-venv named volume shadows $SCRIPT_DIR/.venv; the
# $WORKSPACE and $DOTFILES_DIR binds are harmless no-ops when nested under the kit.
MOUNTS=(
    -v "$SCRIPT_DIR:$SCRIPT_DIR"
    -v "$WORKSPACE:$WORKSPACE"
    -v "kit-venv:$SCRIPT_DIR/.venv"
    -v "$DOTFILES_DIR:$DOTFILES_DIR"
)

# Optional: SSH build key
if [ -n "${SSH_BUILD_KEY:-}" ] && [ -f "$SSH_BUILD_KEY" ]; then
    MOUNTS+=(-v "$SSH_BUILD_KEY:/home/agent/.ssh/build_key:ro")
fi

# Host known_hosts — needed for SSH operations (e.g. git clone via SSH, plugin marketplace)
if [ -f "$HOME/.ssh/known_hosts" ]; then
    MOUNTS+=(-v "$HOME/.ssh/known_hosts:/home/agent/.ssh/known_hosts:ro")
fi

# Persistent credentials — always mounted so auth survives across containers.
# Touch the file if it doesn't exist so the mount works on first run.
# Persistent Claude Code CLI dir — the container entrypoint keeps a
# self-updating copy here so the CLI stays current without image rebuilds.
CLI_DIR="$HOME/.claude-container/cli"
mkdir -p "$CLI_DIR"
MOUNTS+=(-v "$CLI_DIR:/home/agent/.claude-cli")

CREDS_FILE="${CLAUDE_CREDENTIALS_FILE:-$HOME/.claude-container/credentials.json}"
mkdir -p "$(dirname "$CREDS_FILE")"
touch "$CREDS_FILE"
MOUNTS+=(-v "$CREDS_FILE:$DOTFILES_DIR/.credentials.json")

# Gemini CLI credentials — mount host ~/.gemini/ so oath-personal auth persists.
# Override GEMINI_CONFIG_DIR in env.<profile> for per-account setups.
GEMINI_DIR="${GEMINI_CONFIG_DIR:-$HOME/.gemini}"
mkdir -p "$GEMINI_DIR"
MOUNTS+=(-v "$GEMINI_DIR:/home/agent/.gemini")

# GCP service account key (read-only) — only mounted when --gcp <name> is used
# and the env.gcp.<name> file set GCP_KEY_FILE to a real file on host.
GCP_KEY_FILE=$(eval echo "${GCP_KEY_FILE:-}")
if [ -n "$GCP_KEY_FILE" ] && [ -f "$GCP_KEY_FILE" ]; then
    MOUNTS+=(-v "$GCP_KEY_FILE:/home/agent/.gcp/key.json:ro")
elif [ -n "${GCP_NAME:-}" ]; then
    echo "Error: --gcp $GCP_NAME requested but key file not found at: ${GCP_KEY_FILE:-<unset>}"
    exit 1
fi

# Optional: SSH agent forwarding
SSH_MOUNT=()
if [ -n "${SSH_AUTH_SOCK:-}" ]; then
    SSH_MOUNT=(-v "$SSH_AUTH_SOCK:/ssh-agent.sock" -e SSH_AUTH_SOCK=/ssh-agent.sock)
fi

# --- Environment ---
ENV_ARGS=(
    -e GIT_AUTHOR_NAME="$GIT_AUTHOR_NAME"
    -e GIT_AUTHOR_EMAIL="${GIT_AUTHOR_EMAIL:-}"
    -e GIT_COMMITTER_NAME="${GIT_COMMITTER_NAME:-$GIT_AUTHOR_NAME}"
    -e GIT_COMMITTER_EMAIL="${GIT_COMMITTER_EMAIL:-${GIT_AUTHOR_EMAIL:-}}"
    -e TERM
    -e GH_TOKEN="${GH_TOKEN:-}"
    -e SSH_BUILD_USER="${SSH_BUILD_USER:-}"
    -e WORKSPACE="$WORKSPACE"
    -e HOST_HOME="$HOME"
    -e CLAUDE_CONFIG_DIR="$DOTFILES_DIR"
    -e CLAUDE_MULTIPLAI_HOME="$SCRIPT_DIR"
)

# Forward any CLAUDE_PLUGIN_OPTION_* vars set by the caller into the container.
# Sideloaded (--plugin-dir) plugins don't get pluginConfigs applied, so their
# options arrive via this documented env contract instead. `docker run -e NAME`
# (no value) passes the value through from the current environment.
while IFS='=' read -r _name _; do
    [ -n "$_name" ] && ENV_ARGS+=(-e "$_name")
done < <(env | grep '^CLAUDE_PLUGIN_OPTION_' | cut -d= -f1)

if [ -n "${ANTHROPIC_BASE_URL:-}" ]; then
    ENV_ARGS+=(-e ANTHROPIC_BASE_URL="$ANTHROPIC_BASE_URL")
fi

# GCP credential env — only set when --gcp <name> is active and key was mounted.
if [ -n "${GCP_KEY_FILE:-}" ] && [ -f "$GCP_KEY_FILE" ]; then
    ENV_ARGS+=(
        -e CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE=/home/agent/.gcp/key.json
        -e GOOGLE_APPLICATION_CREDENTIALS=/home/agent/.gcp/key.json
    )
    [ -n "${GCP_PROJECT:-}" ] && ENV_ARGS+=(-e CLOUDSDK_CORE_PROJECT="$GCP_PROJECT")
fi

# Container name — used by OrbStack for DNS (<name>.orb.local).
# All container ports are reachable from macOS at that hostname, no -p mapping needed.
# Each instance gets a unique suffix so multiple containers don't clash.
SUFFIX=$(date +%d%H%M%S)
CONTAINER_NAME="claude"
if [ -n "$PROFILE" ]; then
    CONTAINER_NAME="${CONTAINER_NAME}-${PROFILE}"
fi
if [ -n "$GCP_NAME" ]; then
    CONTAINER_NAME="${CONTAINER_NAME}-gcp${GCP_NAME}"
fi
CONTAINER_NAME="${CONTAINER_NAME}-${SUFFIX}"

# Propagate the launcher's cwd into the container so `./claude.sh <subproject>`
# lands in the subproject. The whole workspace is bind-mounted at the same path,
# so $PWD is valid inside the container as long as it's under $WORKSPACE.
# Fall back to $WORKSPACE (the Dockerfile WORKDIR) if cwd is outside it.
WORKDIR_ARG="$WORKSPACE"
case "$PWD/" in "$WORKSPACE/"*) WORKDIR_ARG="$PWD" ;; esac

docker run --rm -it \
    --name "$CONTAINER_NAME" \
    --hostname "$CONTAINER_NAME" \
    --workdir "$WORKDIR_ARG" \
    "${MOUNTS[@]}" \
    "${SSH_MOUNT[@]+"${SSH_MOUNT[@]}"}" \
    "${ENV_ARGS[@]}" \
    --cap-drop=ALL \
    --security-opt=no-new-privileges \
    "$IMAGE_NAME" "${CONTAINER_ARGS[@]}" "${PASSTHROUGH_ARGS[@]+"${PASSTHROUGH_ARGS[@]}"}"
