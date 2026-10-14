#!/bin/bash
# pi-bootstrap.sh — in-container launcher for the pi coding agent.
#
# claude.sh --pi runs this instead of `claude`. It lives in the kit (which is
# bind-mounted into the container at its own absolute path) rather than in the
# image, so seeding and packages can change without cutting a container release.
#
# It does not install pi. The container entrypoint does that, the same way it
# keeps Claude Code current: pi's own installer into ~/.pi-cli/agent, a weekly
# `pi update`, and ~/.pi-cli/agent/bin first on PATH — with a pinned copy baked
# into the image as the fallback. This script runs whichever `pi` is on PATH.
#
# What it does, in order:
#   1. seeds ~/.pi from the default template, then shared defaults, no overwrite
#   2. installs the shared + default package lists when the list changes
#   3. warns about any provider key the template names that is unset
#   4. execs pi
#
# Every other container session — plain claude, --shell, the hub driver — runs
#   pi-bootstrap.sh --packages-only -- <command> [args...]
# instead: step 2 alone, then exec <command>. `pi` called as a tool from those
# sessions needs the same packages, and claude.sh already seeded ~/.pi on the
# Mac. In that mode nothing here can stop the session: a failed install prints
# one warning and the command runs anyway.
#
# There is one pi config, ~/.claude-container/pi/default on the Mac, so the
# template is always dotfiles/pi-profiles/default.

set -euo pipefail

PACKAGES_ONLY=0
if [ "${1:-}" = "--packages-only" ]; then
    PACKAGES_ONLY=1
    shift
    [ "${1:-}" = "--" ] && shift
    if [ $# -eq 0 ]; then
        echo "[pi] Error: --packages-only needs the command to run after it." >&2
        exit 2
    fi
fi

KIT_HOME="${CLAUDE_MULTIPLAI_HOME:-}"
TEMPLATE_DIR="$KIT_HOME/dotfiles/pi-profiles/default"

PI_HOME="$HOME/.pi"
PI_AGENT_DIR="$PI_HOME/agent"

# --- packages ---------------------------------------------------------------
#
# `pi install` writes the package list into settings.json itself, so the
# template does not hand-write that key — it would be a guess at a schema pi
# already owns.
#
# Two lists, concatenated: `_shared/packages.txt`, then the default template's.
#
# The marker holds a hash of the resulting list, not a bare flag. A flag made
# this first-run-only, which meant adding a line to packages.txt silently did
# nothing on a config that had already launched — the failure would have looked
# like a broken extension. `pi install` is idempotent, so re-running a changed
# list is cheap and safe.
SHARED_PKG_FILE="$KIT_HOME/dotfiles/pi-profiles/_shared/packages.txt"
PKG_FILE="$TEMPLATE_DIR/packages.txt"
MARKER="$PI_AGENT_DIR/.multiplai-packages-installed"
# pi install's own output in --packages-only mode, where the terminal belongs to
# the session about to start.
PKG_LOG="$PI_AGENT_DIR/.multiplai-packages.log"

pkg_list() {
    cat "$SHARED_PKG_FILE" "$PKG_FILE" 2>/dev/null \
        | sed 's/#.*//' \
        | awk 'NF { $1=$1; print }'
}

# install_packages [quiet] — install the list when its hash differs from the
# marker. Sets PKG_FAILED to the packages that did not install. Returns 1 when
# any failed. Without `quiet` it prints each install and each failure, as the
# --pi launch always has; with it, it prints nothing and pi install's output
# goes to $PKG_LOG.
PKG_FAILED=""
install_packages() {
    local quiet="${1:-}" wanted want_hash have_hash pkg failed=0 log="$PKG_LOG"
    wanted="$(pkg_list)"
    [ -n "$wanted" ] || return 0
    want_hash="$(printf '%s' "$wanted" | sha256sum | cut -d' ' -f1)"
    have_hash="$(cat "$MARKER" 2>/dev/null || true)"
    [ "$want_hash" != "$have_hash" ] || return 0
    if [ -n "$quiet" ]; then
        echo "[pi] Installing pi packages (the list changed): ${wanted//$'\n'/ }" >&2
        : 2>/dev/null > "$log" || log=/dev/null
    fi
    while IFS= read -r pkg; do
        [ -n "$pkg" ] || continue
        if [ -n "$quiet" ]; then
            if ! pi install "$pkg" >> "$log" 2>&1 </dev/null; then
                PKG_FAILED="${PKG_FAILED:+$PKG_FAILED }$pkg"
                failed=1
            fi
            continue
        fi
        echo "[pi] Installing package: $pkg"
        if ! pi install "$pkg"; then
            echo "[pi] Warning: failed to install $pkg — continuing without it." >&2
            echo "[pi]          Re-run after fixing, or install by hand with: pi install $pkg" >&2
            PKG_FAILED="${PKG_FAILED:+$PKG_FAILED }$pkg"
            failed=1
        fi
    done <<< "$wanted"
    # Only record the hash when every package landed, so a transient npm
    # failure retries on the next launch instead of being marked done.
    if [ "$failed" -eq 0 ]; then
        printf '%s' "$want_hash" 2>/dev/null > "$MARKER" || return 1
        return 0
    fi
    return 1
}

if [ "$PACKAGES_ONLY" -eq 1 ]; then
    # From here on a failure is a warning, never an exit: the session matters
    # more than the packages.
    set +e
    reason=""
    if [ -z "$KIT_HOME" ] || [ ! -d "$KIT_HOME" ]; then
        reason="CLAUDE_MULTIPLAI_HOME is not set to a readable directory"
    elif ! command -v pi >/dev/null 2>&1; then
        reason="pi is not installed in this container (git pull && ./setup.sh brings an image that has it)"
    elif ! mkdir -p "$PI_AGENT_DIR" 2>/dev/null; then
        reason="$PI_AGENT_DIR could not be created"
    elif ! install_packages quiet; then
        if [ -n "$PKG_FAILED" ]; then
            reason="these failed: $PKG_FAILED (details in ~/.pi/agent/.multiplai-packages.log)"
        else
            reason="the marker $MARKER could not be written"
        fi
    fi
    if [ -n "$reason" ]; then
        echo "[pi] Warning: pi's packages (packages.txt) are not installed, so pi runs without them: $reason. The next launch tries again." >&2
    fi

    # The container entrypoint runs its git-hooks drift check only when its own
    # command is `claude` (venv-sync-entrypoint.sh, `[ "${1:-}" = claude ]`).
    # In front of claude, that command is this script, so run the check here.
    if [ "$1" = claude ] && [ -x /usr/local/share/git-hooks/check-hookspath ]; then
        /usr/local/share/git-hooks/check-hookspath "${WORKSPACE:-}" || true
    fi
    exec "$@"
fi

if [ -z "$KIT_HOME" ] || [ ! -d "$KIT_HOME" ]; then
    echo "[pi] Error: CLAUDE_MULTIPLAI_HOME is not set to a readable directory." >&2
    echo "[pi]        This script is meant to be launched by claude.sh --pi." >&2
    exit 1
fi

# An image from before pi was baked in, with no ~/.pi-cli install either, has
# no pi at all. Say so here rather than leave it to `exec`'s "not found".
if ! command -v pi >/dev/null 2>&1; then
    echo "[pi] Error: pi is not installed in this container." >&2
    echo "[pi]        The container entrypoint installs it into ~/.pi-cli, and newer" >&2
    echo "[pi]        images bake a fallback copy. Update the kit and container:" >&2
    echo "[pi]        git pull && ./setup.sh" >&2
    exit 1
fi

mkdir -p "$PI_AGENT_DIR"

# --- 1. seed the config -----------------------------------------------------
#
# Copy-if-absent, never overwrite: the template is the starting point, and
# anything the user or pi itself has since written wins. That is what makes it
# safe to keep the template in git and still let `/settings`, `pi install` and
# `pi auth` write to the live files.
#
# A template directory mirrors ~/.pi, so `agent/models.json` lands at
# ~/.pi/agent/models.json and a bare `web-search.json` lands at
# ~/.pi/web-search.json. Extensions do not all keep their config under agent/ —
# pi-web-access reads ~/.pi/web-search.json — so seeding only agent/ would have
# left those files unreachable.
#
# default first, then _shared: copy-if-absent means whoever writes a path first
# owns it, so this order lets the default template override a shared default
# rather than the other way round.
#
# claude.sh runs the same copy on the Mac before every container launch, so a
# plain Claude session gets a seeded ~/.pi too. Keep the two in step.
seeded_any=0

seed_from() {
    local root="$1" label="$2" src base dest f d
    [ -d "$root" ] || return 0
    for src in "$root"/*; do
        [ -e "$src" ] || continue
        base="$(basename "$src")"
        # Control files read by this script, and repo docs — not pi config.
        case "$base" in packages.txt | required-env.txt | README.md) continue ;; esac
        dest="$PI_HOME/$base"
        if [ -d "$src" ]; then
            mkdir -p "$dest"
            for f in "$src"/*; do
                [ -e "$f" ] || continue
                d="$dest/$(basename "$f")"
                [ -e "$d" ] && continue
                cp -R "$f" "$d"
                echo "[pi] Seeded $base/$(basename "$f") from $label."
                seeded_any=1
            done
        else
            [ -e "$dest" ] && continue
            cp -R "$src" "$dest"
            echo "[pi] Seeded $base from $label."
            seeded_any=1
        fi
    done
}

seed_from "$TEMPLATE_DIR" "the default template"
seed_from "$KIT_HOME/dotfiles/pi-profiles/_shared" "the shared defaults"

# --- 2. packages ------------------------------------------------------------
#
# install_packages, above. A failure has already warned, and pi starts without
# that package, as it always has.
install_packages || true

# --- 3. readiness -------------------------------------------------------------
#
# A missing key is the single most likely reason a provider fails, and pi's own
# error for it arrives several screens later. Name it here instead. It warns and
# continues: one config can hold several providers, and a missing key disables
# only the provider that reads it. Only the variable's presence is tested; the
# value is never printed.
if [ -f "$TEMPLATE_DIR/required-env.txt" ]; then
    missing=()
    while IFS= read -r var; do
        var="${var%%#*}"
        var="$(echo "$var" | xargs)"
        [ -n "$var" ] || continue
        [ -n "$(printenv "$var" 2>/dev/null)" ] || missing+=("$var")
    done < "$TEMPLATE_DIR/required-env.txt"
    if [ ${#missing[@]} -gt 0 ]; then
        echo "[pi] Warning: these are unset, so the providers that read them are off: ${missing[*]}" >&2
        echo "[pi]          The other providers still work. To turn these on," >&2
        echo "[pi]          add the keys to the kit's .env (or env.<profile>) — claude.sh" >&2
        echo "[pi]          forwards every non-empty variable named there into the container." >&2
        echo "[pi]          You can also authenticate interactively with /login." >&2
    fi
fi

[ "$seeded_any" -eq 1 ] && echo "[pi] Config ready at ~/.pi (host: ~/.claude-container/pi/default)."

exec pi "$@"
