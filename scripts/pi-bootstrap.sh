#!/bin/bash
# pi-bootstrap.sh — in-container launcher for the pi coding agent.
#
# claude.sh --pi runs this instead of `claude`. It lives in the kit (which is
# bind-mounted into the container at its own absolute path) rather than in the
# image, so pi can be added, pinned and upgraded without cutting a container
# release. The image already ships Node 22 and npm, which is all pi needs.
#
# What it does, in order:
#   1. installs or re-installs pi into ~/.pi-cli at the pinned version
#   2. seeds ~/.pi/agent from the profile template, without overwriting
#   3. installs the shared + profile package lists when the list changes
#   4. execs pi
#
# Everything after step 1 is per-profile. ~/.pi is a different host directory
# for every profile, so profiles never share credentials, models or sessions —
# which is why a capability wanted everywhere goes in _shared/packages.txt
# rather than being installed once and hoped to be visible.

set -euo pipefail

PROFILE="${MULTIPLAI_PI_PROFILE:-deepseek}"

# Pin both pi and the packages. A floating `@latest` would change the agent
# under you between two launches of the same profile, and the whole point of a
# profile is that it is reproducible. Bump these deliberately.
PI_VERSION="${MULTIPLAI_PI_VERSION:-0.84.2}"

KIT_HOME="${CLAUDE_MULTIPLAI_HOME:-}"
if [ -z "$KIT_HOME" ] || [ ! -d "$KIT_HOME" ]; then
    echo "[pi] Error: CLAUDE_MULTIPLAI_HOME is not set to a readable directory." >&2
    echo "[pi]        This script is meant to be launched by claude.sh --pi." >&2
    exit 1
fi

TEMPLATE_DIR="$KIT_HOME/dotfiles/pi-profiles/$PROFILE"
if [ ! -d "$TEMPLATE_DIR" ]; then
    echo "[pi] Error: no such pi profile: $PROFILE" >&2
    echo "[pi]        Profiles available:" >&2
    for d in "$KIT_HOME/dotfiles/pi-profiles"/[A-Za-z0-9]*/; do
        [ -d "$d" ] && echo "[pi]          $(basename "$d")" >&2
    done
    exit 1
fi

PI_CLI_DIR="$HOME/.pi-cli"
PI_HOME="$HOME/.pi"
PI_AGENT_DIR="$PI_HOME/agent"
PI_BIN="$PI_CLI_DIR/bin/pi"

mkdir -p "$PI_CLI_DIR" "$PI_AGENT_DIR"

# --- 1. pi itself -----------------------------------------------------------
#
# The install goes to a user-owned npm prefix because the image's global prefix
# is /usr and this process is not root. Version is compared rather than
# timestamped: a pinned version either matches or it does not, so there is no
# "is it stale yet" question to get wrong.
#
# The lock keeps two containers sharing this mount from running npm over each
# other. A loser waits rather than racing, and gives up rather than hanging.
installed_version() {
    [ -x "$PI_BIN" ] || return 1
    "$PI_BIN" --version 2>/dev/null | head -1 | tr -d '[:space:]'
}

if [ "$(installed_version || echo none)" != "$PI_VERSION" ]; then
    LOCK="$PI_CLI_DIR/.install-lock"
    waited=0
    while ! mkdir "$LOCK" 2>/dev/null; do
        if [ "$waited" -ge 120 ]; then
            echo "[pi] Error: another container has held the pi install lock for 120s." >&2
            echo "[pi]        If nothing else is starting, remove $LOCK and retry." >&2
            exit 1
        fi
        [ "$waited" -eq 0 ] && echo "[pi] Waiting for another container to finish installing pi..."
        sleep 2
        waited=$((waited + 2))
    done
    trap 'rmdir "$LOCK" 2>/dev/null || true' EXIT

    # Re-check under the lock: the container we waited for may have just done it.
    if [ "$(installed_version || echo none)" != "$PI_VERSION" ]; then
        echo "[pi] Installing pi $PI_VERSION (one-off; cached in ~/.pi-cli for later runs)..."
        if ! npm install -g --prefix "$PI_CLI_DIR" \
                "@earendil-works/pi-coding-agent@$PI_VERSION" >/tmp/pi-install.log 2>&1; then
            echo "[pi] Error: npm install failed. Last 20 lines:" >&2
            tail -20 /tmp/pi-install.log >&2
            exit 1
        fi
    fi

    rmdir "$LOCK" 2>/dev/null || true
    trap - EXIT
fi

export PATH="$PI_CLI_DIR/bin:$PATH"

# --- 2. seed the profile ----------------------------------------------------
#
# Copy-if-absent, never overwrite: the template is the starting point, and
# anything the user or pi itself has since written to ~/.pi/agent wins. That is
# what makes it safe to keep the template in git and still let `/settings`,
# `pi install` and `pi auth` write to the live files.
seeded_any=0
for src in "$TEMPLATE_DIR"/agent/*; do
    [ -e "$src" ] || continue
    dest="$PI_AGENT_DIR/$(basename "$src")"
    if [ ! -e "$dest" ]; then
        cp -R "$src" "$dest"
        echo "[pi] Seeded $(basename "$src") from the $PROFILE profile template."
        seeded_any=1
    fi
done

# --- 3. packages ------------------------------------------------------------
#
# `pi install` writes the package list into settings.json itself, so the
# template does not hand-write that key — it would be a guess at a schema pi
# already owns.
#
# Two lists, concatenated: `_shared/packages.txt` applies to every profile, and
# the profile's own follows it. Shared exists so a capability every profile needs
# — web search being the first — is declared once instead of copied into each
# profile and then forgotten in the next one.
#
# The marker holds a hash of the resulting list, not a bare flag. A flag made
# this first-run-only, which meant adding a line to packages.txt silently did
# nothing on profiles that had already launched — the failure would have looked
# like a broken extension. `pi install` is idempotent, so re-running a changed
# list is cheap and safe.
SHARED_PKG_FILE="$KIT_HOME/dotfiles/pi-profiles/_shared/packages.txt"
PKG_FILE="$TEMPLATE_DIR/packages.txt"
MARKER="$PI_AGENT_DIR/.multiplai-packages-installed"

pkg_list() {
    cat "$SHARED_PKG_FILE" "$PKG_FILE" 2>/dev/null \
        | sed 's/#.*//' \
        | awk 'NF { $1=$1; print }'
}

WANTED="$(pkg_list)"
if [ -n "$WANTED" ]; then
    WANT_HASH="$(printf '%s' "$WANTED" | sha256sum | cut -d' ' -f1)"
    HAVE_HASH="$(cat "$MARKER" 2>/dev/null || true)"
    if [ "$WANT_HASH" != "$HAVE_HASH" ]; then
        failed=0
        while IFS= read -r pkg; do
            [ -n "$pkg" ] || continue
            echo "[pi] Installing package: $pkg"
            if ! pi install "$pkg"; then
                echo "[pi] Warning: failed to install $pkg — continuing without it." >&2
                echo "[pi]          Re-run after fixing, or install by hand with: pi install $pkg" >&2
                failed=1
            fi
        done <<< "$WANTED"
        # Only record the hash when every package landed, so a transient npm
        # failure retries on the next launch instead of being marked done.
        [ "$failed" -eq 0 ] && printf '%s' "$WANT_HASH" > "$MARKER"
    fi
fi

# --- 4. readiness -------------------------------------------------------------
#
# A missing key is the single most likely reason a first launch fails, and pi's
# own error for it arrives several screens later. Name it here instead. Only
# the variable's presence is tested; the value is never printed.
if [ -f "$TEMPLATE_DIR/required-env.txt" ]; then
    missing=()
    while IFS= read -r var; do
        var="${var%%#*}"
        var="$(echo "$var" | xargs)"
        [ -n "$var" ] || continue
        [ -n "$(printenv "$var" 2>/dev/null)" ] || missing+=("$var")
    done < "$TEMPLATE_DIR/required-env.txt"
    if [ ${#missing[@]} -gt 0 ]; then
        echo "[pi] Warning: the $PROFILE profile expects these to be set: ${missing[*]}" >&2
        echo "[pi]          Add them to the kit's .env (or env.<profile>) — claude.sh" >&2
        echo "[pi]          forwards every non-empty variable named there into the container." >&2
        echo "[pi]          You can also authenticate interactively with /login." >&2
    fi
fi

[ "$seeded_any" -eq 1 ] && echo "[pi] Profile '$PROFILE' ready at ~/.pi (host: ~/.claude-container/pi/$PROFILE)."

exec pi "$@"
