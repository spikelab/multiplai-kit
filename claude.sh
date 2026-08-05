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
# Environment:
#   Every variable assigned in .env / env.<profile> is forwarded into the
#   container when its value is non-empty (minus a launcher-only denylist) —
#   adding a var to .env is all it takes. Variables exported in the launching
#   shell WIN over the files. See "Environment forwarding" below.
#   MULTIPLAI_NET selects the egress profile (unrestricted, the default and only
#   implemented value). GCP_KEY_FILE, if set, mounts that service-account key.
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
#                       Notes:
#                       - `driver` must be the FIRST argument ($1); anywhere
#                         else it is treated as a claude prompt/passthrough.
#                       - Driver flags accept only the space-separated form
#                         (--sid <x>, not --sid=x).
#                       - Driver containers intentionally omit the SSH agent
#                         mount that interactive containers get — a hub-owned
#                         driver should never perform SSH-authenticated
#                         operations with the user's agent (parity gap vs
#                         interactive mode is deliberate).
#
# Usage:
#   ./claude.sh                         # container, default profile
#   ./claude.sh --profile work          # container, work git identity
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
if [ "$DRIVER_MODE" -eq 1 ] && [ ${#CLAUDE_ONLY_ARGS[@]} -gt 0 ]; then
    # These are claude-CLI flags for the interactive modes; the driver runs
    # the hub's runner, not claude — silently ignoring them would mislead.
    echo "Error: unsupported driver-mode arguments: ${CLAUDE_ONLY_ARGS[*]}" >&2
    exit 1
fi

# --- Load .env (base config) ---
if [ ! -f "$SCRIPT_DIR/.env" ]; then
    echo "Error: No .env file found."
    echo "  cp .env.example .env   # then fill in your values"
    exit 1
fi

# --- Sourcing env files: the file is the DEFAULT, the shell environment WINS ---
#
# `source_env_file` does two things at once.
#
# 1. **Precedence.** A var already exported in the launching shell survives the
#    source. The kit documents this rule ("Shell env wins over .env") and the
#    in-container python loaders honour it (`override=False`) — the launcher used
#    to be the one place that violated it, so a setup that mints a fresh
#    GH_TOKEN per shell had it silently replaced by the stale value in .env.
#    Applies to every name the file assigns, WORKSPACE included.
#
# 2. **Discovery.** It records every name the file assigns in `_ENV_FILE_VARS`.
#    That list is the universe considered for container forwarding (see
#    "Environment forwarding" below), which is what makes adding a var to .env
#    sufficient to get it into the container — no launcher edit.
#
# `set -a` exports the sourced values so they also reach the exec'd `claude` and
# its child skill scripts in bare/--local modes, which run on the host with no
# container `-e` forwarding at all.
_ENV_FILE_VARS=""
_ENV_SNAP_NAMES=()
_ENV_SNAP_VALUES=()
# Which file first declared each name. Only the GitHub auth-mode check reads
# this, and only to name the offending file in its error — "GH_TOKEN and
# GH_TOKEN_APP are both set" is useless advice if you own three env files.
_ENV_DECL_NAMES=()
_ENV_DECL_FILES=()
_ENV_DECL_N=0
# Explicit count rather than ${#_ENV_SNAP_NAMES[@]}: macOS ships bash 3.2, where
# expanding an empty array under `set -u` is a minefield (hence the
# ${arr[@]+"${arr[@]}"} guards throughout this file). A counter has no such edge.
_ENV_SNAP_N=0
source_env_file() {
    local path="$1"
    local name val i

    # Names assigned by the file. A leading `#` can't match `[A-Za-z_]`, so
    # commented-out entries are ignored — uncommenting a var is what forwards it.
    #
    # The environment value is snapshotted the FIRST time a name is seen, which
    # is before the file declaring it has been sourced. Snapshotting once, rather
    # than per file, is what keeps `--profile` working: .env is sourced first, so
    # a per-file snapshot would capture .env's value and then restore it over the
    # profile that exists precisely to override it.
    #
    # printenv, not ${!name}: it reads the real environment, and it is the only
    # thing that tells "exported but empty" apart from "unset". That difference
    # carries intent — `GH_TOKEN= ./claude.sh` means deliberately blank, not
    # "fall back to whatever the file says".
    while IFS= read -r name; do
        [ -n "$name" ] || continue
        case " $_ENV_FILE_VARS " in
            *" $name "*) continue ;;
        esac
        _ENV_FILE_VARS="$_ENV_FILE_VARS $name"
        _ENV_DECL_NAMES[$_ENV_DECL_N]="$name"
        _ENV_DECL_FILES[$_ENV_DECL_N]="$path"
        _ENV_DECL_N=$((_ENV_DECL_N + 1))
        if val=$(printenv "$name"); then
            _ENV_SNAP_NAMES[$_ENV_SNAP_N]="$name"
            _ENV_SNAP_VALUES[$_ENV_SNAP_N]="$val"
            _ENV_SNAP_N=$((_ENV_SNAP_N + 1))
        fi
    done < <(sed -nE 's/^[[:space:]]*(export[[:space:]]+)?([A-Za-z_][A-Za-z0-9_]*)=.*$/\2/p' "$path")

    # shellcheck disable=SC1090
    set -a
    source "$path"
    set +a

    # Files are defaults; the launching shell wins. Names that were unset in the
    # launcher's environment were never snapshotted, so the file's value stands.
    i=0
    while [ "$i" -lt "$_ENV_SNAP_N" ]; do
        export "${_ENV_SNAP_NAMES[$i]}=${_ENV_SNAP_VALUES[$i]}"
        i=$((i + 1))
    done
}

source_env_file "$SCRIPT_DIR/.env"

# --- Load profile overlay (if specified) ---
if [ -n "$PROFILE" ]; then
    PROFILE_FILE="$SCRIPT_DIR/env.$PROFILE"
    if [ ! -f "$PROFILE_FILE" ]; then
        echo "Error: Profile '$PROFILE' not found at $PROFILE_FILE"
        echo "Available profiles:"
        # Real profiles only — exclude the committed env.example template.
        ls "$SCRIPT_DIR"/env.* 2>/dev/null \
            | grep -v '/env\.example$' \
            | sed 's/.*env\./  /' || echo "  (none)"
        exit 1
    fi
    source_env_file "$PROFILE_FILE"
    echo "[claude] Profile: $PROFILE"
fi

# Expand a leading ~ in WORKSPACE, strip trailing slash. No `eval` — this is
# user config, and eval would execute whatever a stray backtick in it says.
# `$HOME` inside the file's double quotes is already expanded at source time.
WORKSPACE="${WORKSPACE:-}"
WORKSPACE="${WORKSPACE/#\~/$HOME}"
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
    # Containment checks run on CANONICALIZED paths (symlinks and `..`
    # resolved via cd + pwd -P) so a crafted `$WORKSPACE/../outside` can't
    # slip past the prefix match. The original user-supplied paths are what
    # still reaches docker — the bind mounts use the un-canonicalized
    # $WORKSPACE/$SCRIPT_DIR, which is what's valid inside the container.
    _canon_dir() { (cd "$1" 2>/dev/null && pwd -P); }
    WORKSPACE_REAL=$(_canon_dir "$WORKSPACE") || WORKSPACE_REAL="$WORKSPACE"
    KIT_REAL=$(_canon_dir "$SCRIPT_DIR") || KIT_REAL="$SCRIPT_DIR"
    DRV_RUNNER_REAL=""
    if _RUNNER_DIR_REAL=$(_canon_dir "$(dirname "$DRV_RUNNER")"); then
        DRV_RUNNER_REAL="$_RUNNER_DIR_REAL/$(basename "$DRV_RUNNER")"
    fi
    case "$DRV_RUNNER_REAL" in
        "$WORKSPACE_REAL"/*|"$KIT_REAL"/*) ;;
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
    DRV_PROJECT_DIR_REAL=$(_canon_dir "$DRV_PROJECT_DIR") || DRV_PROJECT_DIR_REAL=""
    case "$DRV_PROJECT_DIR_REAL/" in
        "$WORKSPACE_REAL/"*) ;;
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

# --- Bare mode: no container, claude runs directly on this host ---
# The three callers below differ in exactly one thing: whether skip-permissions
# is safe. It is safe only when something else is already the sandbox (we are
# inside a container). On the host — explicit --local, or Docker missing — the
# permission prompts are the only boundary left, so they stay on.
# Env forwarding is moot here: `set -a` in source_env_file already exported the
# user's config into this process, which `claude` inherits.
exec_bare() {
    local -a skip=()
    if [ "${1:-}" = "skip-permissions" ]; then
        skip=(--dangerously-skip-permissions)
    fi
    export CLAUDE_CONFIG_DIR="$DOTFILES_DIR"
    exec claude "${skip[@]+"${skip[@]}"}" "${MCP_ISOLATION[@]}" \
        "${CLAUDE_ONLY_ARGS[@]+"${CLAUDE_ONLY_ARGS[@]}"}" \
        "${PASSTHROUGH_ARGS[@]+"${PASSTHROUGH_ARGS[@]}"}"
}

# The GH auth decision runs BEFORE any bare-mode exec below, not after it.
# `exec` replaces this process, so a block placed after the `exec_bare` call
# sites simply never runs on `--local`, inside-a-container, or the Docker-missing
# fallback — three launch paths that then got no precedence resolution, no
# preflight checks, and no Keychain lookup. A `.env` declaring both GH_TOKEN and
# GH_TOKEN_APP would hand the session both, and gh silently prefers the
# environment PAT over the App credential the hooks store: the session works, as
# the wrong identity, with nothing said. (kit #23.)
# --- GitHub auth: pick a MODE, never mint -------------------------------------
#
# Two modes, both supported, never both at once:
#
#   PAT mode  GH_TOKEN, or the macOS Keychain item named by GH_TOKEN_KEYCHAIN.
#             Unchanged, and still the default for anyone without a GitHub App.
#   App mode  GH_TOKEN_APP names a host-side App profile. The launcher forwards
#             only the NAME; the SessionStart hook mints inside the container so
#             the token is fresh relative to the SESSION rather than to
#             `docker run`, and the PreToolUse hook renews it when it runs out.
#             The App's private key never leaves the Mac.
#
# Declaring both IN CONFIGURATION is a hard error, not a precedence rule: a
# silent winner here means launching with the wrong GitHub identity, which is
# worse than not launching. A GH_TOKEN exported in the launching SHELL is a
# different thing — the kit's documented "shell env wins" override — and is
# allowed. source_env_file already records which names came from a file
# (_ENV_DECL_*) and which existed in the environment first (_ENV_SNAP_NAMES),
# so telling them apart needs no new machinery.
_gh_decl_file() {    # the env file that first declared NAME, if any
    local i=0
    while [ "$i" -lt "$_ENV_DECL_N" ]; do
        if [ "${_ENV_DECL_NAMES[$i]}" = "$1" ]; then
            printf '%s' "${_ENV_DECL_FILES[$i]}"
            return 0
        fi
        i=$((i + 1))
    done
    return 1
}
_gh_from_shell() {   # is NAME's current value the launching shell's?
    # Two ways that is true, and the second is easy to miss: the snapshot only
    # records names that an env file ALSO declares (that is all it needs to do —
    # restore the shell's value over the file's). A name nobody declared but that
    # is set right now can only have come from the shell, and treating it as
    # file-declared would turn the documented `GH_TOKEN=$(mint) ./claude.sh`
    # override into a launch error.
    local i=0
    while [ "$i" -lt "$_ENV_SNAP_N" ]; do
        if [ "${_ENV_SNAP_NAMES[$i]}" = "$1" ]; then return 0; fi
        i=$((i + 1))
    done
    _gh_decl_file "$1" >/dev/null || return 0
    return 1
}

GH_TOKEN_KEY="${GH_TOKEN_KEYCHAIN:-gh-token}"
GH_AUTH_MODE=pat

if [ -n "${GH_TOKEN_APP:-}" ]; then
    if [ -n "${GH_TOKEN:-}" ] && _gh_from_shell GH_TOKEN; then
        # Rule: a shell-exported token is an override, not a conflict. It wins
        # for this launch; GH_TOKEN_APP is dropped so the container hooks stay
        # inert rather than fighting the token that was handed in.
        echo "[claude] GH_TOKEN from the shell overrides GH_TOKEN_APP='$GH_TOKEN_APP' for this launch."
        unset GH_TOKEN_APP
    elif ! _gh_from_shell GH_TOKEN_APP; then
        _pat_var=""; _pat_file=""
        if [ -n "${GH_TOKEN:-}" ] && ! _gh_from_shell GH_TOKEN; then
            _pat_var=GH_TOKEN; _pat_file=$(_gh_decl_file GH_TOKEN || true)
        elif [ -n "${GH_TOKEN_KEYCHAIN:-}" ] && ! _gh_from_shell GH_TOKEN_KEYCHAIN; then
            _pat_var=GH_TOKEN_KEYCHAIN; _pat_file=$(_gh_decl_file GH_TOKEN_KEYCHAIN || true)
        fi
        if [ -n "$_pat_var" ]; then
            _app_file=$(_gh_decl_file GH_TOKEN_APP || true)
            echo "Error: two GitHub identities are declared in configuration." >&2
            echo "         GH_TOKEN_APP='$GH_TOKEN_APP'   declared in ${_app_file:-the environment}" >&2
            echo "         $_pat_var   declared in ${_pat_file:-the environment}" >&2
            echo "       These select different GitHub identities. Refusing to guess which one" >&2
            echo "       you meant — a silent winner here runs the session as the wrong user." >&2
            echo "       Fix: give each identity its own profile (the PAT in one env.<profile>," >&2
            echo "       GH_TOKEN_APP in another, neither in .env). See docs/PROFILES.md." >&2
            exit 1
        fi
        GH_AUTH_MODE=app
    else
        # GH_TOKEN_APP itself came from the launching shell: the same "your
        # shell wins" override as above, in the other direction — but never
        # silently. A file-declared PAT is being dropped for this launch; name
        # it and the file it lives in, exactly like the mirror case, or the
        # session runs as an unexpected GitHub user with no visible cause.
        _pat_var=""
        if [ -n "${GH_TOKEN:-}" ] && ! _gh_from_shell GH_TOKEN; then
            _pat_var=GH_TOKEN
        elif [ -n "${GH_TOKEN_KEYCHAIN:-}" ] && ! _gh_from_shell GH_TOKEN_KEYCHAIN; then
            _pat_var=GH_TOKEN_KEYCHAIN
        fi
        if [ -n "$_pat_var" ]; then
            _pat_file=$(_gh_decl_file "$_pat_var" || true)
            echo "[claude] GH_TOKEN_APP='$GH_TOKEN_APP' from the shell overrides $_pat_var (declared in ${_pat_file:-a file}) for this launch."
        fi
        GH_AUTH_MODE=app
    fi
fi

if [ "$GH_AUTH_MODE" = app ]; then
    # App mode is macOS-only: the App's private key lives in the Mac Keychain,
    # and minting reaches it either over the host bridge (container mode) or
    # directly (bare). Either way this must be a Mac. Launching a session that
    # cannot possibly authenticate is worse than refusing here.
    if [ "$(uname)" != "Darwin" ]; then
        echo "Error: GH_TOKEN_APP='$GH_TOKEN_APP' needs macOS — the App's private key lives in the Mac Keychain." >&2
        echo "       This host is $(uname). Use a PAT (GH_TOKEN) here, or unset GH_TOKEN_APP." >&2
        exit 1
    fi
    if [ ! -x "$HOME/.local/bin/multiplai-gh-token" ]; then
        echo "Error: GH_TOKEN_APP='$GH_TOKEN_APP' but ~/.local/bin/multiplai-gh-token is not installed." >&2
        echo "       Every gh call in the session would fail. Install it: ./setup.sh" >&2
        echo "       (setup installs it from the pinned container checkout, with the gateway.)" >&2
        exit 1
    fi
    # No PAT fallback, ever: falling back would swap the session's GitHub
    # identity without saying so. An environment token also beats hosts.yml and
    # makes `gh auth login --with-token` refuse outright, so forward none.
    unset GH_TOKEN
    export GH_TOKEN_APP
else
    # PAT mode — exactly the previous behaviour. The Keychain lookup is macOS-only
    # (`security`); on Linux we skip it and point at the env var instead of telling
    # the user to fix a Keychain that can't exist there.
    if [ -z "${GH_TOKEN:-}" ] && [ "$(uname)" = "Darwin" ] && command -v security >/dev/null 2>&1; then
        # Exported, not just assigned: forwarding is value-less `-e GH_TOKEN`, which
        # docker resolves from this process's ENVIRONMENT, so a plain shell variable
        # would arrive as nothing at all.
        # `${USER:-…}`, not `$USER`: this runs under `set -u`, and USER is not
        # guaranteed — a launch from cron, an SSH forced command, or any other
        # non-login context has an empty environment. Dying with "USER: unbound
        # variable" on the way to an optional Keychain lookup is a bad trade.
        GH_TOKEN=$(security find-generic-password -a "${USER:-$(id -un)}" -s "$GH_TOKEN_KEY" -w 2>/dev/null || true)
        export GH_TOKEN
    fi
    if [ -z "${GH_TOKEN:-}" ]; then
        if [ "$(uname)" = "Darwin" ]; then
            echo "Warning: No '$GH_TOKEN_KEY' in Keychain and \$GH_TOKEN unset. GitHub CLI will not be authenticated."
            echo "         (Or set GH_TOKEN_APP=<app> to use a GitHub App — see docs/PROFILES.md.)"
        else
            echo "Warning: \$GH_TOKEN not set. GitHub CLI will not be authenticated (set GH_TOKEN in .env or your profile)."
        fi
    fi
fi


# --- Explicit local mode ---
if [[ "$MODE" == "local" ]]; then
    exec_bare
fi

# --- Already inside a container? Run bare with full permissions ---
if [ -f /.dockerenv ] || grep -qsm1 'docker\|containerd' /proc/1/cgroup 2>/dev/null; then
    exec_bare skip-permissions
fi

# --- Docker not available? Warn and fall back to bare mode ---
if ! command -v docker &>/dev/null; then
    echo "WARNING: Docker not found — running without container sandbox."
    echo "  Host filesystem is NOT isolated. Permission prompts are active."
    echo "  Install Docker and re-run ./setup.sh to build the sandbox image."
    echo ""
    exec_bare
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

# --- Network egress profile ---
#
# MULTIPLAI_NET selects how much of the internet the container can reach.
# "unrestricted" (the default, and the only implemented value) is today's
# behaviour: normal Docker networking, the agent can reach any host.
#
# "restricted" is the planned opt-in profile — an internal Docker network with
# no route out, plus a proxy sidecar holding a hostname allowlist (the Anthropic
# API, GitHub, PyPI, the npm registry, and entries you add). It is not built
# yet. The name and this validation exist so the interface is settled and a
# request for it fails loudly and immediately, rather than silently running
# unrestricted and leaving you believing egress was filtered — which is the
# worse of the two failure modes by a wide margin.
MULTIPLAI_NET="${MULTIPLAI_NET:-unrestricted}"
case "$MULTIPLAI_NET" in
    unrestricted)
        ;;
    restricted)
        echo "Error: MULTIPLAI_NET=restricted is not implemented yet." >&2
        echo "       Egress filtering (proxy sidecar + hostname allowlist) is planned;" >&2
        echo "       until it lands, this refuses rather than pretending to filter." >&2
        echo "       Use MULTIPLAI_NET=unrestricted (the default) to launch." >&2
        exit 1
        ;;
    *)
        echo "Error: unknown MULTIPLAI_NET '$MULTIPLAI_NET' (known: unrestricted, restricted)" >&2
        exit 1
        ;;
esac

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

# Gemini CLI credentials — opt-in, OFF by default.
#
# This used to mount the host's entire ~/.gemini/ read-write on every launch.
# That directory holds OAuth refresh tokens (oauth_creds.json) and history/ —
# a record of past prompts — and the image ships no gemini binary, so the
# default configuration exposed all of it to buy exactly nothing. Set
# MULTIPLAI_MOUNT_GEMINI=1 in .env or env.<profile> if you've installed the
# Gemini CLI yourself and want its auth to survive across containers.
#
# It stays read-write when enabled: the CLI rewrites oauth_creds.json on every
# token refresh (verified — the file's mtime advances from inside the
# container), so a :ro mount would break auth rather than harden it.
if [ "${MULTIPLAI_MOUNT_GEMINI:-0}" = "1" ]; then
    GEMINI_DIR="${GEMINI_CONFIG_DIR:-$HOME/.gemini}"
    mkdir -p "$GEMINI_DIR"
    MOUNTS+=(-v "$GEMINI_DIR:/home/agent/.gemini")
fi

# GCP service account key (read-only) — activated by GCP_KEY_FILE alone, from
# whichever source set it: .env, env.<profile>, or an export in the launching
# shell. There is no separate selector flag or overlay file; with dynamic
# forwarding and shell-env-wins there is nothing left for one to do.
#
# Set-but-missing is a hard error rather than a silent skip: launching without
# the credential surfaces as an opaque auth failure deep inside some later
# gcloud call, which is a much worse place to learn the path was wrong.
GCP_KEY_FILE="${GCP_KEY_FILE:-}"
GCP_KEY_FILE="${GCP_KEY_FILE/#\~/$HOME}"
GCP_ACTIVE=0
if [ -n "$GCP_KEY_FILE" ]; then
    if [ ! -f "$GCP_KEY_FILE" ]; then
        echo "Error: GCP_KEY_FILE is set but there is no file at: $GCP_KEY_FILE" >&2
        exit 1
    fi
    MOUNTS+=(-v "$GCP_KEY_FILE:/home/agent/.gcp/key.json:ro")
    GCP_ACTIVE=1
fi

# Optional: SSH agent forwarding
SSH_MOUNT=()
if [ -n "${SSH_AUTH_SOCK:-}" ]; then
    SSH_MOUNT=(-v "$SSH_AUTH_SOCK:/ssh-agent.sock" -e SSH_AUTH_SOCK=/ssh-agent.sock)
fi

# --- Environment forwarding ---
#
# The universe of forwarded variables is
#
#     (every name assigned in .env / env.<profile>  ∪  keep-list)  −  denylist
#
# so adding a variable to .env is all it takes to see it in the container. The
# old hand-enumerated list is what this replaces: it meant every new secret
# needed a matching launcher edit, and without one the var silently never
# arrived — a failure that looks like a broken skill, not a missing -e line.
#
# Two rules make the sweep safe to point at user config:
#
#  1. **Value-less `-e NAME`.** Docker resolves the value from this process's
#     environment, so secrets never appear on argv (and therefore never in
#     `ps`). This is why source_env_file exports, and why GH_TOKEN from the
#     Keychain and the GIT_COMMITTER_* defaults are exported explicitly below.
#  2. **Non-empty only.** `-e NAME=` makes the variable *present but empty*
#     inside the container, which beats every `${NAME:-fallback}` and
#     `os.environ.get(NAME, default)` downstream — an empty forwarded GH_TOKEN
#     shadows a token the container would otherwise mint for itself. Empty or
#     unset here means not forwarded at all, so the default wins as intended.
#
# Note there is no sweep of the whole host environment. A variable that is
# exported in the shell and named in no file reaches the container only if it is
# on the keep-list — the file is still the declaration of intent.

# Vars that legitimately exist in no env file: set by the terminal, computed
# below, read from the macOS Keychain, or exported per launch
# (ANTHROPIC_BASE_URL — pointing one launch at a proxy shouldn't require an
# .env line; it used to work from the shell alone and silently dropping it
# would misroute traffic with no visible cause).
#
# GH_TOKEN_APP is here rather than on the denylist on purpose: the two hooks
# inside the container read it to know which App profile to mint against, and it
# is a profile NAME, not a secret.
_ENV_KEEP="TERM GIT_AUTHOR_NAME GIT_AUTHOR_EMAIL GIT_COMMITTER_NAME GIT_COMMITTER_EMAIL GH_TOKEN GH_TOKEN_APP SSH_BUILD_USER CLOUDSDK_CORE_PROJECT ANTHROPIC_BASE_URL"

# Never forwarded dynamically, for one of three reasons: it configures the
# launcher itself (which image, which volume, which network); it holds a HOST
# path that the mounts remap, so the host value is actively wrong inside the
# container; or it is set explicitly further down with a computed container-side
# value. MULTIPLAI_DRIVER_TOKEN is denied here and forwarded by driver mode
# alone — an interactive session has no business holding the hub's token.
#
# The last line is the guard rail: these are never *meant* to be in an env file,
# but the sweep now reads user config, and a stray `PATH=` or `HOME=` in .env
# would otherwise be forwarded as the macOS value and break the Linux container
# in ways that look nothing like their cause. SSH_AUTH_SOCK is denied because the
# SSH_MOUNT block above already forwards it, remapped to the socket's in-container
# path; the host path would win on argv order and silently kill agent forwarding.
_ENV_DENY="WORKSPACE SSH_BUILD_KEY GCP_KEY_FILE CLAUDE_CREDENTIALS_FILE
GEMINI_CONFIG_DIR IMAGE_NAME CONTAINER_REPO CONTAINER_REF KIT_VENV_VOLUME
MULTIPLAI_NET GH_TOKEN_KEYCHAIN MULTIPLAI_MOUNT_GEMINI MULTIPLAI_HUB_URL
MULTIPLAI_HUB_TOKEN MULTIPLAI_DRIVER_TOKEN HOST_HOME CLAUDE_CONFIG_DIR
CLAUDE_MULTIPLAI_HOME DISABLE_AUTOUPDATER GOOGLE_APPLICATION_CREDENTIALS
CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE
SSH_AUTH_SOCK PATH HOME USER LOGNAME SHELL PWD OLDPWD HOSTNAME"

# The list above wraps for readability; the membership tests below are
# space-delimited, so flatten the newlines out of it first.
_flat=""
for _name in $_ENV_DENY; do _flat="$_flat $_name"; done
_ENV_DENY="$_flat"

# The committer fields fall back to the author fields, and both must be in the
# ENVIRONMENT (not merely shell variables) for value-less forwarding to find them.
export GIT_AUTHOR_NAME
export GIT_AUTHOR_EMAIL="${GIT_AUTHOR_EMAIL:-}"
export GIT_COMMITTER_NAME="${GIT_COMMITTER_NAME:-$GIT_AUTHOR_NAME}"
export GIT_COMMITTER_EMAIL="${GIT_COMMITTER_EMAIL:-${GIT_AUTHOR_EMAIL:-}}"

ENV_ARGS=()
_ENV_SEEN=""
for _name in $_ENV_FILE_VARS $_ENV_KEEP; do
    case " $_ENV_DENY " in *" $_name "*) continue ;; esac
    case " $_ENV_SEEN " in *" $_name "*) continue ;; esac
    # printenv, not ${!_name}: it reads the same environment docker will read,
    # so what we test is exactly what would be forwarded.
    [ -n "$(printenv "$_name" 2>/dev/null)" ] || continue
    _ENV_SEEN="$_ENV_SEEN $_name"
    ENV_ARGS+=(-e "$_name")
done

# Computed / container-side values — these are the names on the denylist above,
# passed in value form because the host's value is not the container's.
ENV_ARGS+=(
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

# GCP credential env — the key is mounted at a fixed container path, so these
# two point there, never at the host path in GCP_KEY_FILE.
if [ "$GCP_ACTIVE" -eq 1 ]; then
    ENV_ARGS+=(
        -e CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE=/home/agent/.gcp/key.json
        -e GOOGLE_APPLICATION_CREDENTIALS=/home/agent/.gcp/key.json
    )
fi

# Forward any CLAUDE_PLUGIN_OPTION_* vars set by the caller into the container.
# Sideloaded (--plugin-dir) plugins don't get pluginConfigs applied, so their
# options arrive via this documented env contract instead. `docker run -e NAME`
# (no value) passes the value through from the current environment.
while IFS='=' read -r _name _; do
    [ -n "$_name" ] && ENV_ARGS+=(-e "$_name")
done < <(env | grep '^CLAUDE_PLUGIN_OPTION_' | cut -d= -f1)

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

# --- Post-exit extraction drain ---
# The multiplai-context plugin defers learnings/diary extraction: SessionEnd is
# killed within seconds, so it only drops a marker in
# $WORKSPACE/.multiplai/data/pending_extractions/. Something else has to run
# the (multi-minute) extraction. Until now that something was the *next*
# SessionStart in any project — so closing your last tab on a Friday evening
# produced Friday's diary entry on Monday morning.
#
# The session container itself can't do it — `docker run --rm` tears the
# container down when PID 1 exits, taking any detached child with it. And the
# host must not: an earlier design ran the plugin's drain_extractions.py
# directly on the Mac, which meant executing code resolved from
# installed_plugins.json / the plugin cache — state that lives in the
# rw-mounted dotfiles dir and is therefore writable by in-container code. A
# compromised session could plant a script the host would then run with the
# launcher's environment. That design was rejected (2026-08-02): no claude —
# and no plugin-resolved code — runs on the host.
#
# So the launcher's only job here is deciding WHETHER to launch (markers
# present?) and assembling a `docker run`: a disposable, detached container
# from the SAME image the session just ran in, with the drain as its process.
# Resolving which script to run happens inside that container — the trust
# domain designed to execute plugin state.
#
# Scope: this fires for container-mode sessions only. `--local` and in-container
# bare sessions, and hub `driver` containers, all `exec` and never return here —
# those still drain at the next SessionStart, as before.
#
# Strictly best-effort and strictly silent. Every unmet precondition is a
# `return 0`, and the whole call is `|| true`: `exit $DOCKER_STATUS` below is
# documented behaviour with tests on it, and a diary entry is never worth
# changing what the launcher reports about the session.

# The drain container's command. Runs under the image's bash; every $var here
# is a CONTAINER-side expansion (quoted heredoc — the host expands nothing).
#
# Resolution mirrors what the in-container SessionStart drain gets from Claude
# Code: the manifest's installPath for the installed multiplai-context, exactly
# — no newest-in-cache fallback, so a rolled-back install can never run a
# newer cached version against its queue. Plugin missing, too old to ship the
# script, or no jq/uv in the image: silent exit 0, the queue drains at the
# next SessionStart as before.
#
# --wait is load-bearing: drain_extractions.py normally fires detached
# extraction children and exits, but this container is `--rm` — PID 1 exiting
# would tear it down, children and all. --wait keeps the drain in the
# foreground until every child has finished.
#
# --project is load-bearing too, and points at the plugin's scripts/ directory,
# never a level above it. That directory's pyproject.toml is what provides
# multiplai_core; an installed plugin is a copy of the plugin subtree with no
# workspace root above it, so the member dir is the only form that resolves in
# both layouts. This ran with project resolution disabled until 2026-08-05,
# which meant drain_extractions.py died on `import multiplai_core` every time —
# invisibly, since the container's output is discarded and its status ignored.
DRAIN_CONTAINER_CMD=$(cat <<'DRAIN_EOF'
command -v jq >/dev/null 2>&1 || exit 0
command -v uv >/dev/null 2>&1 || exit 0
manifest="$CLAUDE_CONFIG_DIR/plugins/installed_plugins.json"
[ -f "$manifest" ] || exit 0
install_path=$(jq -r '
    .plugins // {}
    | to_entries[]
    | select(.key | startswith("multiplai-context@"))
    | .value[0].installPath // empty
' "$manifest" 2>/dev/null | head -n 1)
[ -n "$install_path" ] || exit 0
script="$install_path/scripts/drain_extractions.py"
[ -f "$script" ] || exit 0
exec uv run --project "$install_path/scripts" "$script" \
    --wait --data-dir "$WORKSPACE/.multiplai/data"
DRAIN_EOF
)

# --- Live-container roster ---
# A session cannot answer "am I still alive" and neither can anything inside
# the container: there is no docker binary, no socket, no root, and the build
# gateway's allowlist has never carried docker. So the fleet view has had to
# guess death from silence — an entry quiet past a threshold is *filed* as
# idle, deliberately without claiming it died, because a killed container and
# a session you walked away from are indistinguishable from in there. On a real
# registry that left 49 entries in permanent limbo.
#
# The Mac can just look. This writes the names of every running container to a
# file in the shared workspace; the plugin reads it and treats "this entry's
# container is absent from a roster observed AFTER the entry's last event" as
# proof the session is over. Names only — no ports, no images, nothing that
# could make this a second source of truth about sessions.
#
# **This is a poll, not a marker, and that is the whole point.** kit 0.15.1
# tried the marker: the launcher dropped an `.exited` file beside the registry
# entry when `docker run` returned. It was removed before release because the
# launcher dies *with* the terminal on a reboot or a closed window, so the
# marker only ever covered `docker kill` and OOM — worth zero entries in
# practice. A poll does not care whether any launcher survived; it asks what
# exists right now, which is exactly the case the marker could not reach.
#
# Called at two points, both of which the launcher already reaches: just before
# `docker run`, and again after the session exits. The first is what makes this
# work with no daemon and no timer — every hook-path render of AGENTS.md
# happens at SessionStart, inside a container this launcher started seconds
# earlier, so the roster it reads is seconds old. A stale roster is not a
# wrong answer, only a missing one: the plugin falls back to the quiet
# heuristic, which is what a vanilla Claude Code install does permanently.
#
# Best-effort throughout. No docker, no workspace, an unwritable data dir, or a
# daemon that has gone away are all silent no-ops — losing the roster costs
# accuracy in the fleet view and must never cost you a session.
write_container_roster() {
    local data_dir="$WORKSPACE/.multiplai/data"
    [ -d "$data_dir" ] || return 0
    command -v docker >/dev/null 2>&1 || return 0

    local names
    names=$(docker ps --format '{{.Names}}' 2>/dev/null) || return 0

    # Hand-built JSON array: jq is optional on a host and container names are
    # a closed alphabet (docker rejects anything outside [a-zA-Z0-9][a-zA-Z0-9_.-]),
    # so there is nothing here that needs escaping. Guard anyway — a name that
    # somehow carried a quote or a backslash must drop out, not corrupt the file.
    local ids="" name
    while IFS= read -r name; do
        [ -n "$name" ] || continue
        case "$name" in *[\"\\]*) continue ;; esac
        ids="${ids:+$ids, }\"$name\""
    done <<< "$names"

    # `observer` and `kind` are not decoration. A container name is globally
    # meaningful because there is one daemon; a pid would only mean something
    # in the namespace that observed it, and this system already has that scar
    # (the plugin's fleet_sources/jobs.py: "judge liveness by mtime, never by
    # pid — the roster's pids belong to another process namespace"). Any future
    # roster of pids must be refused by a reader expecting containers, and
    # these two fields are how it can tell.
    local tmp="$data_dir/.live_containers.json.$$"
    {
        printf '{\n'
        printf '  "version": 1,\n'
        printf '  "observed_at": "%s",\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
        printf '  "observer": "host",\n'
        printf '  "kind": "container",\n'
        printf '  "ids": [%s]\n' "$ids"
        printf '}\n'
    } > "$tmp" 2>/dev/null || { rm -f "$tmp" 2>/dev/null; return 0; }

    # Atomic: a reader in another container must never see a half-written file.
    mv -f "$tmp" "$data_dir/live_containers.json" 2>/dev/null || rm -f "$tmp" 2>/dev/null
    return 0
}

post_exit_drain() {
    local data_dir="$WORKSPACE/.multiplai/data"

    # Only spend a container when there is actually something to do. Marker
    # filenames are the whole read — the host treats the queue strictly as
    # data and never opens, parses, or resolves anything from it.
    #
    # Both queues count. A marker sitting in processing_extractions/ is not
    # necessarily live work: a container torn down mid-extraction (which is the
    # normal way a session ends) kills the detached child and strands its
    # marker there, and the drain's recover_stale_processing is the only thing
    # that ever requeues it. Checking pending_extractions/ alone made this
    # launcher skip precisely the case it is best placed to repair.
    #
    # (No nullglob here, so an unmatched glob stays literal — hence -e per
    # entry rather than trusting ${queued[0]}, which would be the literal
    # pattern whenever the first directory happens to be empty.)
    local -a queued=(
        "$data_dir"/pending_extractions/*.json
        "$data_dir"/processing_extractions/*.json
    )
    local q work=""
    for q in "${queued[@]}"; do
        [ -e "$q" ] && { work=1; break; }
    done
    [ -n "$work" ] || return 0

    # Defensive: this point is only reached in container mode, so docker and
    # the image were both present at launch — but "were" is not "are", and
    # either going missing mid-session must stay silent, not error at exit.
    command -v docker >/dev/null 2>&1 || return 0
    docker image inspect "$IMAGE_NAME" >/dev/null 2>&1 || return 0

    # Two launchers exiting at once may both reach this point and both launch
    # a drain container. Fine: the dequeue in the plugin's lib/extraction_drain
    # is an atomic os.rename, so each marker is processed by exactly one of
    # them and the rename loser just moves on — no host-side lock needed.
    # $$ keeps a same-second exit from failing the second `docker run` on a
    # duplicate --name; even that loss would be benign (the winner drains the
    # shared queue).
    local drain_name
    drain_name="multiplai-drain-$(date +%Y%m%d%H%M%S)-$$"

    # Deliberately NOT the session container's plumbing:
    #   * mounts are only what the drain reads and writes — the workspace
    #     (queue in, diary/learnings out), the config dir (plugin manifest +
    #     cache, session transcripts under projects/), and the same renaming
    #     credentials bind a session gets, pointing the Agent SDK at the LIVE
    #     OAuth file (never a copy — the CLI refreshes the token in place).
    #     No kit mount, no kit venv, no SSH agent, no CLI dir.
    #   * env is exactly two variables, both non-secret paths. None of the
    #     .env sweep (ENV_ARGS) and none of the CLAUDE_PLUGIN_OPTION_* pass-
    #     through reach it — in particular CLAUDE_PLUGIN_OPTION_anthropic_api_key
    #     cannot arrive even if .env sets one, so the drain always runs on the
    #     OAuth-backed Agent SDK and never bills a separate API key. WORKSPACE
    #     is what routes the diary into the workspace instead of ~/.multiplai/.
    #
    # -d detaches the CLIENT immediately (the launcher's exit is never delayed
    # by the multi-minute extraction); --rm reaps the container when the drain
    # finishes. Stdio is fully detached; failure to launch is silent by design.
    docker run -d --rm \
        --name "$drain_name" \
        -v "$WORKSPACE:$WORKSPACE" \
        -v "$DOTFILES_DIR:$DOTFILES_DIR" \
        -v "$CREDS_FILE:$DOTFILES_DIR/.credentials.json" \
        -e WORKSPACE="$WORKSPACE" \
        -e CLAUDE_CONFIG_DIR="$DOTFILES_DIR" \
        --cap-drop=ALL \
        --security-opt=no-new-privileges \
        "$IMAGE_NAME" \
        bash -c "$DRAIN_CONTAINER_CMD" \
        >/dev/null 2>&1 </dev/null || return 0
    return 0
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
    CONTAINER_NAME="${CONTAINER_NAME}-${SUFFIX}"

    # Before the run, not after: the session about to start is the one that
    # renders AGENTS.md at SessionStart, so this is what makes the roster it
    # reads seconds old. This container is deliberately NOT in that roster —
    # its own entry does not exist yet, and an entry is only ever judged
    # against a roster observed after its last event.
    write_container_roster || true

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

# After the loop, so it runs on every way out of it — shell mode's early
# break, no registry, no marker, a declined take-back, or a hub that would not
# release. A take-back relaunch loops back into `docker run` instead, and its
# own SessionStart drains as it always did.
post_exit_drain || true

# And once more on the way out — the container that just exited is gone from
# docker ps by now (`--rm`), so this is the observation that retires it. The
# pre-run write alone would leave the last session of a run looking alive
# until the next launch.
write_container_roster || true

exit "$DOCKER_STATUS"
