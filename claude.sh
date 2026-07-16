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
#   --gcp <name>        Load env.gcp.<name> for GCP credentials
#   --shell             Container shell (bash instead of claude)
#
# Subcommand:
#   driver              Non-interactive driver container for the multiplai hub
#                       (ADR 0002 in multiplai-gui): runs the hub's driver
#                       runner on the kit venv python instead of interactive
#                       claude. Detached (docker run -d), no TTY, no take-back
#                       loop — the hub owns the container's lifecycle.
#                       Flags: --sid <uuid|new> --port <n> --runner <path>
#                              [--name <container>] [--project-dir <dir>]
#                              [--permission-mode prompt|acceptEdits|bypass]
#                              [--model <model>] [--foreground]
#                       --foreground runs the container attached (debug: a
#                       --rm container that dies at startup keeps its logs).
#                       Requires MULTIPLAI_DRIVER_TOKEN in the environment
#                       (forwarded to the container via -e passthrough, never argv).
#
# Usage:
#   ./claude.sh                         # container, default profile
#   ./claude.sh --profile work          # container, work git identity
#   ./claude.sh --gcp prod              # container, load env.gcp.prod
#   ./claude.sh --local                 # bare, host permissions apply
#   ./claude.sh --shell                 # container bash shell
#   ./claude.sh --profile work --shell  # work profile, bash shell
#   ./claude.sh driver --sid new --port 8765 --runner <path>  # hub driver container

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DOTFILES_DIR="$SCRIPT_DIR/dotfiles"

# Kit project root — hooks and skills resolve runtime paths from this.
# Distinct from CLAUDE_CONFIG_DIR (dotfiles/) which is purely Claude Code's domain.
export CLAUDE_MULTIPLAI_HOME="$SCRIPT_DIR"

# --- Driver subcommand: `claude.sh driver ...` (hub-launched, non-interactive) ---
DRIVER_MODE=0
if [[ "${1:-}" == "driver" ]]; then
    DRIVER_MODE=1
    shift
fi
DRV_SID=""
DRV_PORT=""
DRV_NAME=""
DRV_RUNNER=""
DRV_PROJECT_DIR=""
DRV_PERMISSION_MODE="prompt"
DRV_MODEL=""
DRV_FOREGROUND=0

# --- Parse flags (extract ours, pass the rest through) ---
PROFILE=""
GCP_NAME=""
MODE=""
PASSTHROUGH_ARGS=()
CLAUDE_ONLY_ARGS=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --sid|--port|--name|--runner|--project-dir|--permission-mode|--model)
            # Driver-mode flags ONLY when the subcommand is active. Outside it,
            # fall through to passthrough — --model/--permission-mode are real
            # claude CLI flags and hijacking them breaks interactive launches.
            if [ "$DRIVER_MODE" -eq 0 ]; then
                PASSTHROUGH_ARGS+=("$1")
                shift
                continue
            fi
            [ $# -ge 2 ] || { echo "Error: $1 requires a value" >&2; exit 1; }
            case "$1" in
                --sid) DRV_SID="$2" ;;
                --port) DRV_PORT="$2" ;;
                --name) DRV_NAME="$2" ;;
                --runner) DRV_RUNNER="$2" ;;
                --project-dir) DRV_PROJECT_DIR="$2" ;;
                --permission-mode) DRV_PERMISSION_MODE="$2" ;;
                --model) DRV_MODEL="$2" ;;
            esac
            shift 2
            ;;
        --foreground)
            # debug: run the driver container attached (logs on this terminal)
            # instead of detached — a --rm container that dies at startup
            # otherwise destroys its own logs before they can be read.
            [ "$DRIVER_MODE" -eq 1 ] || { echo "Error: $1 is only valid after the 'driver' subcommand" >&2; exit 1; }
            DRV_FOREGROUND=1
            shift
            ;;
        --profile)
            [ $# -ge 2 ] || { echo "Error: $1 requires a value" >&2; exit 1; }
            PROFILE="$2"
            shift 2
            ;;
        --profile=*)
            PROFILE="${1#--profile=}"
            shift
            ;;
        --gcp)
            [ $# -ge 2 ] || { echo "Error: $1 requires a value" >&2; exit 1; }
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
            [ $# -ge 2 ] || { echo "Error: $1 requires a value" >&2; exit 1; }
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

if [ "$DRIVER_MODE" -eq 1 ] && [ -n "$MODE" ]; then
    echo "Error: driver mode cannot combine with --local/--shell." >&2
    exit 1
fi
if [ "$DRIVER_MODE" -eq 1 ] && [ ${#PASSTHROUGH_ARGS[@]} -gt 0 ]; then
    echo "Error: unknown driver-mode arguments: ${PASSTHROUGH_ARGS[*]}" >&2
    exit 1
fi

# --- Load .env (base config) ---
if [ ! -f "$SCRIPT_DIR/.env" ]; then
    echo "Error: No .env file found."
    echo "  cp .env.example .env   # then fill in your values"
    exit 1
fi

# Export everything sourced from the user env files (`set -a`) so it reaches
# the exec'd `claude` and its child skill scripts in bare/--local modes, which
# run on the host with NO container `-e` forwarding. Previously only vars named
# explicitly below were forwarded (container only); a plain `source` leaves the
# rest as un-exported shell vars, invisible to skills in --local. .env / profile
# / gcp overlays are user config by definition — all meant to become environment.
# shellcheck disable=SC1091
set -a
source "$SCRIPT_DIR/.env"
set +a

# --- Load profile overlay (if specified) ---
if [ -n "$PROFILE" ]; then
    PROFILE_FILE="$SCRIPT_DIR/env.$PROFILE"
    if [ ! -f "$PROFILE_FILE" ]; then
        echo "Error: Profile '$PROFILE' not found at $PROFILE_FILE"
        echo "Available profiles:"
        # Real profiles only — exclude the env.example template and env.gcp.* files.
        ls "$SCRIPT_DIR"/env.* 2>/dev/null \
            | grep -vE '/env\.(example|gcp\.)' \
            | sed 's/.*env\./  /' || echo "  (none)"
        exit 1
    fi
    # shellcheck disable=SC1090
    set -a
    source "$PROFILE_FILE"
    set +a
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
    set -a
    source "$GCP_FILE"
    set +a
    echo "[claude] GCP: $GCP_NAME"
fi

# Expand ~ and $HOME in WORKSPACE, strip trailing slash
WORKSPACE=$(eval echo "${WORKSPACE:-}")
WORKSPACE="${WORKSPACE%/}"
: "${WORKSPACE:?WORKSPACE must be set in .env}"
: "${GIT_AUTHOR_NAME:?GIT_AUTHOR_NAME must be set in .env}"

# --- Driver mode validations (container-only; the hub owns this container) ---
if [ "$DRIVER_MODE" -eq 1 ]; then
    if [ -f /.dockerenv ] || grep -qsm1 'docker\|containerd' /proc/1/cgroup 2>/dev/null; then
        echo "Error: driver mode launches a container — run it on the host." >&2
        exit 1
    fi
    if ! command -v docker &>/dev/null; then
        echo "Error: driver mode requires Docker (no bare fallback)." >&2
        exit 1
    fi
    if [ "$DRV_SID" != "new" ] && ! [[ "$DRV_SID" =~ ^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$ ]]; then
        echo "Error: driver mode requires --sid <uuid|new> (got: '${DRV_SID:-<unset>}')" >&2
        exit 1
    fi
    if ! [[ "$DRV_PORT" =~ ^[0-9]+$ ]] || [ "$DRV_PORT" -lt 1 ] || [ "$DRV_PORT" -gt 65535 ]; then
        echo "Error: driver mode requires --port <1-65535> (got: '${DRV_PORT:-<unset>}')" >&2
        exit 1
    fi
    if [ -z "$DRV_RUNNER" ] || [ ! -f "$DRV_RUNNER" ]; then
        echo "Error: driver mode requires --runner <path to driver_runner.py> (got: '${DRV_RUNNER:-<unset>}')" >&2
        exit 1
    fi
    case "$DRV_RUNNER" in
        "$WORKSPACE"/*|"$SCRIPT_DIR"/*) ;;
        *)
            echo "Error: --runner must live under \$WORKSPACE or the kit root (it reaches the container via the bind mounts): $DRV_RUNNER" >&2
            exit 1
            ;;
    esac
    DRV_PROJECT_DIR="${DRV_PROJECT_DIR:-$WORKSPACE}"
    if [ ! -d "$DRV_PROJECT_DIR" ]; then
        echo "Error: --project-dir is not a directory: $DRV_PROJECT_DIR" >&2
        exit 1
    fi
    case "$DRV_PROJECT_DIR/" in
        "$WORKSPACE/"*) ;;
        *)
            echo "Error: --project-dir must be inside \$WORKSPACE: $DRV_PROJECT_DIR" >&2
            exit 1
            ;;
    esac
    case "$DRV_PERMISSION_MODE" in
        prompt|acceptEdits|bypass) ;;
        *)
            echo "Error: --permission-mode must be prompt|acceptEdits|bypass (got: '$DRV_PERMISSION_MODE')" >&2
            exit 1
            ;;
    esac
    if [ -z "${MULTIPLAI_DRIVER_TOKEN:-}" ]; then
        echo "Error: driver mode requires MULTIPLAI_DRIVER_TOKEN in the environment." >&2
        exit 1
    fi
    if [ -z "$DRV_NAME" ]; then
        if [ "$DRV_SID" = "new" ]; then
            # $RANDOM suffix: two manual same-second launches must not collide
            # (the hub always passes --name, so this is the CLI-only fallback)
            DRV_NAME="claude-drv-new-$(date +%d%H%M%S)-$RANDOM"
        else
            DRV_NAME="claude-drv-${DRV_SID:0:8}"
        fi
    fi
    if ! [[ "$DRV_NAME" =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]*$ ]]; then
        echo "Error: invalid container name: '$DRV_NAME'" >&2
        exit 1
    fi
fi

# --- Nag until the Multiplai plugins are installed ---
# setup.sh installs them when the host has the claude CLI; when it doesn't,
# this banner repeats at every launch until the one-time in-session install.
# Skipped in driver mode: non-interactive, nothing to run /plugin in.
if [ "$DRIVER_MODE" -eq 0 ] && ! grep -qs '"multiplai-context@multiplai"' "$DOTFILES_DIR/plugins/installed_plugins.json" 2>/dev/null; then
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
    echo "  Install Docker and re-run ./setup.sh to build the sandbox image."
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

# Per-runtime venv volume. Derived from this kit checkout's path so parallel
# runtimes (e.g. ~/.multiplai-runtimes/{default,test-x}) never share one —
# a shared volume is broken by construction: the venv bakes in absolute
# paths, and the volume mounts at a different $SCRIPT_DIR per runtime.
# basename for readability + path checksum for uniqueness; override with
# KIT_VENV_VOLUME in .env. NOTE for pre-existing installs: the name changes
# from the old literal 'kit-venv', so the first launch re-syncs the venv
# into a fresh volume (a few minutes, self-healing); set
# KIT_VENV_VOLUME=kit-venv to keep the old volume instead.
_VOL_SUFFIX=$(basename "$SCRIPT_DIR" | tr -c 'a-zA-Z0-9_.-' '-' | sed 's/-*$//')
_VOL_HASH=$(printf '%s' "$SCRIPT_DIR" | cksum | cut -d' ' -f1)
KIT_VENV_VOLUME="${KIT_VENV_VOLUME:-kit-venv-${_VOL_SUFFIX}-${_VOL_HASH}}"

# Verify image exists
if ! docker image inspect "$IMAGE_NAME" >/dev/null 2>&1; then
    echo "Error: Docker image '$IMAGE_NAME' not found."
    echo "  Build it first: cd container && ./build.sh"
    exit 1
fi

# GH_TOKEN: env var > macOS Keychain key. The Keychain lookup is macOS-only
# (`security`); on Linux we skip it and point at the env var instead of telling
# the user to fix a Keychain that can't exist there.
GH_TOKEN_KEY="${GH_TOKEN_KEYCHAIN:-gh-token}"
if [ -z "${GH_TOKEN:-}" ] && [ "$(uname)" = "Darwin" ] && command -v security >/dev/null 2>&1; then
    GH_TOKEN=$(security find-generic-password -a "$USER" -s "$GH_TOKEN_KEY" -w 2>/dev/null || true)
fi
if [ -z "${GH_TOKEN:-}" ]; then
    if [ "$(uname)" = "Darwin" ]; then
        echo "Warning: No '$GH_TOKEN_KEY' in Keychain and \$GH_TOKEN unset. GitHub CLI will not be authenticated."
    else
        echo "Warning: \$GH_TOKEN not set. GitHub CLI will not be authenticated (set GH_TOKEN in .env or your profile)."
    fi
fi

# --- Ensure kit-venv volume is agent-writable ---
# New Docker named volumes are root-owned. The venv-sync entrypoint runs as
# the agent user and can't create the venv on a fresh volume. Fix ownership
# once (no-op when venv already exists — just a stat check inside the container).
#
# --entrypoint is REQUIRED: without it, `bash -c` becomes arguments to the
# image's venv-sync entrypoint, which exits at once (CLAUDE_MULTIPLAI_HOME
# unset in this bare run) and the chown never executes — leaving every FRESH
# volume root-owned and the first launch failing with EACCES in venv-sync.
# chown by container user name (`agent`, no group — the image has no `agent`
# group; primary group is the build-time GID) rather than host `id -u`.
docker run --rm \
    --entrypoint bash \
    -v "$KIT_VENV_VOLUME:$SCRIPT_DIR/.venv" \
    --user root \
    "$IMAGE_NAME" \
    -c "[ -x '$SCRIPT_DIR/.venv/bin/python3' ] || chown agent '$SCRIPT_DIR/.venv'" \
    >/dev/null \
    || echo "Warning: venv volume ($KIT_VENV_VOLUME) ownership prep failed — a fresh volume may hit 'Permission denied' in venv-sync." >&2

# --- Volume mounts ---
# Mount the kit root at its own absolute path so the runtime works wherever it
# lives — inside the workspace (legacy) or a separate dir outside it. Without
# this, a runtime outside $WORKSPACE loses kit-root files (notably multiplai.conf,
# read in-container by run-hook-python/log_utils) because only dotfiles/ + the
# venv were mounted. The per-runtime venv volume shadows $SCRIPT_DIR/.venv; the
# $WORKSPACE and $DOTFILES_DIR binds are harmless no-ops when nested under the kit.
MOUNTS=(
    -v "$SCRIPT_DIR:$SCRIPT_DIR"
    -v "$WORKSPACE:$WORKSPACE"
    -v "$KIT_VENV_VOLUME:$SCRIPT_DIR/.venv"
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

# Gmail (multiplai-messaging skill): credential is three env vars from .env,
# forwarded below like SLACK_TOKEN — GMAIL_CLIENT_ID / GMAIL_CLIENT_SECRET /
# GMAIL_REFRESH_TOKEN (minted once on the host by the skill's get_token.py).
# No mount, no token file. (A JSON file via GMAIL_TOKEN_FILE is an optional fallback.)

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
    # The entrypoint's ~/.claude-cli refresh owns CLI updates; the in-app
    # auto-updater targets the root-owned global npm prefix and fails with a
    # per-session nag. Set here as well as in the image so containers built
    # from pre-fix images are covered without a rebuild.
    -e DISABLE_AUTOUPDATER=1
)

# Messaging plugin (multiplai-messaging) credentials — one allowlist to extend
# for the next plugin, instead of hand-enumerating an -e line per var. Only
# forward vars that are actually set: `-e NAME=` (empty) makes the var *present
# but empty* in the container, which defeats a script's `os.environ.get(NAME,
# default)` fallback (the empty string wins over the default). Skipping unset
# vars keeps optional ones (e.g. GMAIL_TOKEN_URI) truly absent.
for v in SLACK_TOKEN GMAIL_CLIENT_ID GMAIL_CLIENT_SECRET GMAIL_REFRESH_TOKEN GMAIL_TOKEN_URI GMAIL_TOKEN_FILE; do
    [ -n "${!v:-}" ] && ENV_ARGS+=(-e "$v=${!v}")
done

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

# Propagate the launcher's cwd into the container so `./claude.sh <subproject>`
# lands in the subproject. The whole workspace is bind-mounted at the same path,
# so $PWD is valid inside the container as long as it's under $WORKSPACE.
# Fall back to $WORKSPACE (the Dockerfile WORKDIR) if cwd is outside it.
WORKDIR_ARG="$WORKSPACE"
case "$PWD/" in "$WORKSPACE/"*) WORKDIR_ARG="$PWD" ;; esac

# --- Driver mode: detached runner container for the multiplai hub ---
# Reuses the exact MOUNTS/ENV_ARGS/hardening of interactive container mode,
# but runs the hub's driver runner on the kit venv python instead of
# interactive claude: no TTY, detached, and NO take-back loop — the hub owns
# this container (release = shutdown frame -> exit --rm).
# The venv python MUST be addressed explicitly (same rule as run-hook-python):
# the image's PATH only fronts the legacy $WORKSPACE/multiplai-runtime venv
# path, so a bare `python3` is the system interpreter when the kit lives
# elsewhere (e.g. ~/.multiplai-runtimes/<name>) — no websockets, no SDK.
# venv-sync (the entrypoint) creates/updates this venv before CMD runs.
if [ "$DRIVER_MODE" -eq 1 ]; then
    RUNNER_CMD=("$SCRIPT_DIR/.venv/bin/python3" "$DRV_RUNNER"
        --port "$DRV_PORT"
        --project-dir "$DRV_PROJECT_DIR"
        --permission-mode "$DRV_PERMISSION_MODE")
    if [ "$DRV_SID" = "new" ]; then
        RUNNER_CMD+=(--new)
    else
        RUNNER_CMD+=(--sid "$DRV_SID")
    fi
    [ -n "$DRV_MODEL" ] && RUNNER_CMD+=(--model "$DRV_MODEL")
    DRV_DETACH_ARGS=(-d)
    [ "$DRV_FOREGROUND" -eq 1 ] && DRV_DETACH_ARGS=()
    # -e MULTIPLAI_DRIVER_TOKEN (no value) forwards the token from this
    # process's environment without exposing it on argv (ps-safe).
    exec docker run "${DRV_DETACH_ARGS[@]+"${DRV_DETACH_ARGS[@]}"}" --rm \
        --name "$DRV_NAME" \
        --hostname "$DRV_NAME" \
        --workdir "$DRV_PROJECT_DIR" \
        "${MOUNTS[@]}" \
        "${ENV_ARGS[@]}" \
        -e MULTIPLAI_DRIVER_TOKEN \
        --cap-drop=ALL \
        --security-opt=no-new-privileges \
        "$IMAGE_NAME" "${RUNNER_CMD[@]}"
fi

# Allocate a TTY only when stdin is one — `docker run -it` fails with
# "the input device is not a TTY" under pipes/CI/non-interactive shells.
if [ -t 0 ]; then TTY_ARGS=(-it); else TTY_ARGS=(-i); fi

# Take-back relaunch arg filter: a resume must never replay the one-shot
# prompt. Drops -p/--print and EVERY positional — the claude CLI accepts the
# prompt as a positional anywhere on the line, not just after -p, and a
# resume never needs the original prompt. Flags survive, and a value-taking
# flag keeps its value(s) so they are never mistaken for positionals. The
# three flag lists mirror `claude --help` (CLI 2.1.207): mandatory-value,
# variadic (<...> consumes values until the next flag, matching commander),
# and optional-value ([value] consumes one following non-dash token). An
# unknown future value-flag degrades safely: the flag survives, its value is
# dropped as a positional — a visible CLI error on relaunch, never a
# replayed prompt. Result lands in FILTERED_ARGS.
# (Same function in scripts/claude-wrapped — keep the two in sync.)
filter_resume_args() {
    FILTERED_ARGS=()
    while [ $# -gt 0 ]; do
        case "$1" in
            -p|--print)
                # one-shot print mode: drop
                shift; continue ;;
            --)
                # everything after -- is positional: drop it all
                break ;;
            --agent|--append-system-prompt|--debug-file|--effort|--fallback-model|\
--input-format|--json-schema|--max-budget-usd|--model|-n|--name|\
--output-format|--permission-mode|--plugin-dir|--plugin-url|\
--remote-control-session-name-prefix|--session-id|--setting-sources|\
--settings|--system-prompt)
                # mandatory-value flag: keep flag + its value
                FILTERED_ARGS+=("$1"); shift
                if [ $# -gt 0 ]; then FILTERED_ARGS+=("$1"); shift; fi
                continue ;;
            --add-dir|--allowedTools|--allowed-tools|--disallowedTools|\
--disallowed-tools|--betas|--file|--mcp-config|--tools)
                # variadic flag: keep flag + every following non-dash value
                FILTERED_ARGS+=("$1"); shift
                while [ $# -gt 0 ]; do
                    case "$1" in -*) break ;; *) FILTERED_ARGS+=("$1"); shift ;; esac
                done
                continue ;;
            -d|--debug|--from-pr|--prompt-suggestions|--remote-control|-r|--resume|-w|--worktree)
                # optional-value flag: keep flag + one following non-dash value
                FILTERED_ARGS+=("$1"); shift
                if [ $# -gt 0 ]; then
                    case "$1" in -*) ;; *) FILTERED_ARGS+=("$1"); shift ;; esac
                fi
                continue ;;
            -*)
                # boolean flag or --flag=value form: keep as-is
                FILTERED_ARGS+=("$1"); shift; continue ;;
            *)
                # positional (the prompt can be one, anywhere): drop
                shift; continue ;;
        esac
    done
}

# --- Run, with the hub adoption take-back loop ---
# The multiplai hub (multiplai-gui) can adopt a terminal-born session: it
# writes <sid>.adopt beside the session registry entry the multiplai-context
# hooks maintain under $WORKSPACE/.multiplai/data/sessions/ (the entry's
# hostname equals this container's name — that is the sid discovery key).
# When claude exits and a marker addressed at this container exists, offer to
# take the session back: ask the hub to release the driver seat, delete the
# marker, and relaunch with `claude --resume <sid>`. With no marker (no hub,
# plugin absent, plain exit) this is a single pass that ends with the docker
# run's own exit status — the flow is unchanged.
SESSIONS_DIR="$WORKSPACE/.multiplai/data/sessions"
RESUME_ARGS=()
DOCKER_STATUS=0
while :; do
    # Container name — used by OrbStack for DNS (<name>.orb.local).
    # All container ports are reachable from macOS at that hostname, no -p
    # mapping needed. Each instance gets a unique suffix so multiple
    # containers don't clash; recomputed per pass so a take-back relaunch
    # never races the previous container's --rm cleanup over the name.
    SUFFIX=$(date +%d%H%M%S)
    CONTAINER_NAME="claude"
    if [ -n "$PROFILE" ]; then
        CONTAINER_NAME="${CONTAINER_NAME}-${PROFILE}"
    fi
    if [ -n "$GCP_NAME" ]; then
        CONTAINER_NAME="${CONTAINER_NAME}-gcp${GCP_NAME}"
    fi
    CONTAINER_NAME="${CONTAINER_NAME}-${SUFFIX}"

    DOCKER_STATUS=0
    docker run --rm "${TTY_ARGS[@]}" \
        --name "$CONTAINER_NAME" \
        --hostname "$CONTAINER_NAME" \
        --workdir "$WORKDIR_ARG" \
        "${MOUNTS[@]}" \
        "${SSH_MOUNT[@]+"${SSH_MOUNT[@]}"}" \
        "${ENV_ARGS[@]}" \
        --cap-drop=ALL \
        --security-opt=no-new-privileges \
        "$IMAGE_NAME" "${CONTAINER_ARGS[@]}" \
        "${PASSTHROUGH_ARGS[@]+"${PASSTHROUGH_ARGS[@]}"}" \
        "${RESUME_ARGS[@]+"${RESUME_ARGS[@]}"}" \
        || DOCKER_STATUS=$?

    # Shell mode runs bash — there is no claude session to adopt.
    [[ "$MODE" == "shell" ]] && break

    # Map this container back to its session via the registry, then look for
    # an adoption marker. Every step is best-effort: no registry (plugin not
    # installed), no entry, or no marker all mean "normal exit".
    # Newest entry by mtime wins (the registry refreshes hostname on every
    # event, so the just-ended session is the most recently updated match);
    # the hostname match is whitespace-tolerant, not coupled to the plugin's
    # JSON formatting. Registry filenames are UUIDs — no spaces to trip ls -t.
    ENTRY=""
    while IFS= read -r CAND_ENTRY; do
        if command -v jq >/dev/null 2>&1; then
            jq -e --arg h "$CONTAINER_NAME" '.hostname == $h' "$CAND_ENTRY" >/dev/null 2>&1 || continue
        else
            grep -qsE "\"hostname\"[[:space:]]*:[[:space:]]*\"$CONTAINER_NAME\"" "$CAND_ENTRY" || continue
        fi
        ENTRY="$CAND_ENTRY"
        break
    done < <(ls -t "$SESSIONS_DIR"/*.json 2>/dev/null || true)
    [ -n "$ENTRY" ] || break
    SID=$(basename "$ENTRY" .json)
    # SID is a filename from a container-writable dir and is interpolated
    # into the hub URL and `--resume` — accept only canonical UUIDs.
    [[ "$SID" =~ ^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$ ]] || break
    MARKER="$SESSIONS_DIR/$SID.adopt"
    [ -f "$MARKER" ] || break

    # Non-interactive stdin (pipes, CI): a read here would swallow a line of
    # piped input as "Enter" (unwanted release+resume) or block forever.
    # Skip the take-back and leave the marker — the hub keeps the seat.
    [ -t 0 ] || break

    echo "Session $SID adopted by multiplai hub. Press Enter to take it back, Ctrl-C to leave it."
    # Ctrl-C here means "leave it with the hub" — trap INT so we fall through
    # to `exit $DOCKER_STATUS` instead of dying with 130 and breaking the
    # documented exit-status preservation. read returns >128 on the signal.
    trap : INT
    if ! read -r; then
        trap - INT
        echo ""
        break
    fi
    trap - INT

    # Ask the hub to release the driver seat — fail CLOSED. Resuming while
    # the hub's SDK client still drives the session puts two drivers on one
    # session. Proceed only when the release is confirmed (2xx), moot
    # (404/409 — unknown / not driven), or the hub is provably dead
    # (connection refused / unresolvable). Timeout, 5xx, auth failure, or a
    # missing curl leave the marker in place and skip the resume.
    # Env (.env is exported above) wins over multiplai.conf; the conf is
    # parsed KEY=value (grep, not source) because it contains INI sections.
    HUB_URL="${MULTIPLAI_HUB_URL:-$(sed -n 's/^MULTIPLAI_HUB_URL=//p' "$SCRIPT_DIR/multiplai.conf" 2>/dev/null | tail -n 1 | tr -d '"')}"
    HUB_TOKEN="${MULTIPLAI_HUB_TOKEN:-$(sed -n 's/^MULTIPLAI_HUB_TOKEN=//p' "$SCRIPT_DIR/multiplai.conf" 2>/dev/null | tail -n 1 | tr -d '"')}"
    RELEASED=""
    if [ -z "$HUB_URL" ]; then
        echo "No MULTIPLAI_HUB_URL configured — cannot ask the hub to release; leaving the session with the hub." >&2
    elif ! command -v curl >/dev/null 2>&1; then
        echo "curl not found — cannot ask the hub to release; leaving the session with the hub." >&2
    else
        # Token stays off argv (visible in ps) — the header arrives on stdin
        # via `-H @-`. An empty herestring (no token) is a no-op for curl.
        HUB_AUTH_HEADER=""
        [ -n "$HUB_TOKEN" ] && HUB_AUTH_HEADER="Authorization: Bearer $HUB_TOKEN"
        CURL_EXIT=0
        HTTP_CODE=$(curl -sS -m 5 -o /dev/null -w '%{http_code}' -X POST \
            -H @- \
            "${HUB_URL%/}/v1/sessions/$SID/release" \
            2>/dev/null <<<"$HUB_AUTH_HEADER") || CURL_EXIT=$?
        case "$CURL_EXIT:$HTTP_CODE" in
            0:2??|0:404|0:409) RELEASED=1 ;;  # released, or not hub-driven
            6:*|7:*)           RELEASED=1 ;;  # hub dead: unresolvable / refused
            *)
                echo "Hub did not confirm release (curl exit $CURL_EXIT, HTTP ${HTTP_CODE:-n/a}) — not resuming; the hub keeps the session. Marker kept: $MARKER" >&2
                ;;
        esac
    fi
    [ -n "$RELEASED" ] || break
    rm -f "$MARKER"

    # One-shot prompts must not replay on the resumed session —
    # `./claude.sh "deploy prod" -p` (or the prompt as a bare positional
    # anywhere) would re-run the side-effectful prompt. filter_resume_args
    # (above) drops -p/--print and all positionals from the relaunch args.
    filter_resume_args "${PASSTHROUGH_ARGS[@]+"${PASSTHROUGH_ARGS[@]}"}"
    PASSTHROUGH_ARGS=("${FILTERED_ARGS[@]+"${FILTERED_ARGS[@]}"}")

    RESUME_ARGS=(--resume "$SID")
done
exit "$DOCKER_STATUS"
