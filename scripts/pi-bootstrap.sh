#!/bin/bash
# pi-bootstrap.sh — in-container launcher for the pi coding agent.
#
# claude.sh --pi runs this instead of `claude`. It lives in the kit (which is
# bind-mounted into the container at its own absolute path) rather than in the
# image, so profile handling can change without cutting a container release.
#
# It does not install pi. The container entrypoint does that, the same way it
# keeps Claude Code current: pi's own installer into ~/.pi-cli/agent, a weekly
# `pi update`, and ~/.pi-cli/agent/bin first on PATH — with a pinned copy baked
# into the image as the fallback. This script runs whichever `pi` is on PATH.
#
# What it does, in order:
#   1. seeds ~/.pi from the profile template, then shared defaults, no overwrite
#   2. installs the shared + profile package lists when the list changes
#   3. warns about any provider key the profile names that is unset
#   4. execs pi
#
# All of it is per-profile. ~/.pi is a different host directory for every
# profile, so profiles never share credentials, models or sessions — which is
# why a capability wanted everywhere goes in _shared/packages.txt rather than
# being installed once and hoped to be visible.

set -euo pipefail

PROFILE="${MULTIPLAI_PI_PROFILE:-default}"

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

PI_HOME="$HOME/.pi"
PI_AGENT_DIR="$PI_HOME/agent"

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

# --- 1. seed the profile ----------------------------------------------------
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
# Profile first, then _shared: copy-if-absent means whoever writes a path first
# owns it, so this order lets a profile override a shared default rather than
# the other way round.
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

seed_from "$TEMPLATE_DIR" "the $PROFILE profile template"
seed_from "$KIT_HOME/dotfiles/pi-profiles/_shared" "the shared defaults"

# --- 2. packages ------------------------------------------------------------
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
        echo "[pi]          The $PROFILE profile's other providers still work. To turn them on," >&2
        echo "[pi]          add the keys to the kit's .env (or env.<profile>) — claude.sh" >&2
        echo "[pi]          forwards every non-empty variable named there into the container." >&2
        echo "[pi]          You can also authenticate interactively with /login." >&2
    fi
fi

[ "$seeded_any" -eq 1 ] && echo "[pi] Profile '$PROFILE' ready at ~/.pi (host: ~/.claude-container/pi/$PROFILE)."

exec pi "$@"
