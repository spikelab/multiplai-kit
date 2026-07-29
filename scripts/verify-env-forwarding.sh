#!/bin/bash
# Does my variable actually reach the container?
#
# `evals/unit/test_claude_sh_env.py` pins the launcher's forwarding *decisions*
# against a stub docker, which is why it can run in CI. It cannot tell you what
# a real container sees. This script does: it launches real containers and reads
# the environment from inside them.
#
# Run it on a host with Docker and a built image, from the kit root:
#
#     ./scripts/verify-env-forwarding.sh
#
# It restores `.env` on every exit path, including Ctrl-C.
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1

if [ ! -f .env ]; then
    echo "No .env in $(pwd) — run ./setup.sh first." >&2
    exit 1
fi
if ! command -v docker >/dev/null 2>&1; then
    echo "No docker on PATH. This script needs a real daemon; that is its whole" >&2
    echo "purpose. For the launcher's decision logic without a daemon, run:" >&2
    echo "    pytest evals/unit/test_claude_sh_env.py" >&2
    exit 1
fi

ENV_BACKUP="$(mktemp)"
KEY_FILE="$(mktemp)"   # plain mktemp: `-t <name>` is not portable across BSD/GNU
cp .env "$ENV_BACKUP"
cleanup() {
    cp "$ENV_BACKUP" .env
    rm -f "$ENV_BACKUP" "$KEY_FILE"
}
trap cleanup EXIT INT TERM

PASS=0
FAIL=0
pass() { PASS=$((PASS + 1)); printf '  \033[32mPASS\033[0m  %s\n' "$1"; }
fail() { FAIL=$((FAIL + 1)); printf '  \033[31mFAIL\033[0m  %s\n' "$1"; }

echo
echo "Launching real containers — each check takes a few seconds."
echo

# --- 4. the empty-variable rule ---------------------------------------------
#
# The bug: `-e NAME=` makes a variable present-but-empty inside the container,
# which beats every ${NAME:-fallback} downstream. An unset GH_TOKEN used to be
# forwarded as empty and shadow the token the container mints for itself.
#
# So the failure condition is specifically an EMPTY GH_TOKEN. A non-empty one is
# the container's own and is the fix working, not a leak.
echo "4. empty variables are not forwarded"
out=$(GH_TOKEN= ./claude.sh --shell -c 'env' 2>&1)
if printf '%s\n' "$out" | grep -qE '^GH_TOKEN=$'; then
    fail "GH_TOKEN arrived present-but-empty — the shadowing bug is back"
else
    pass "no empty GH_TOKEN in the container"
fi
if printf '%s\n' "$out" | grep -qE '^(SLACK_TOKEN|GMAIL_[A-Z_]*)=$'; then
    fail "a messaging secret arrived present-but-empty"
else
    pass "no empty SLACK_TOKEN / GMAIL_* in the container"
fi

# --- 5. shell-env-wins precedence -------------------------------------------
echo "5. the launching shell overrides the env files"
out=$(GIT_AUTHOR_NAME=OverrideTest ./claude.sh --shell -c 'echo "GAN=$GIT_AUTHOR_NAME"' 2>&1)
if printf '%s\n' "$out" | grep -qx 'GAN=OverrideTest'; then
    pass "exported GIT_AUTHOR_NAME beat the value in .env"
else
    fail "shell value did not win (got: $(printf '%s\n' "$out" | grep '^GAN=' || echo '<no output>'))"
fi

# --- 6. dynamic forwarding --------------------------------------------------
#
# The point of the refactor: declaring a variable in .env is the entire install
# step. No matching edit to claude.sh, which is what used to be required and
# which silently forwarded nothing when forgotten.
echo "6. a newly declared variable arrives with no launcher edit"
printf '\nVERIFY_SMOKE_VAR="reached-the-container"\n' >> .env
out=$(./claude.sh --shell -c 'echo "V=$VERIFY_SMOKE_VAR"' 2>&1)
if printf '%s\n' "$out" | grep -qx 'V=reached-the-container'; then
    pass "VERIFY_SMOKE_VAR arrived from .env alone"
else
    fail "declared variable did not arrive (got: $(printf '%s\n' "$out" | grep '^V=' || echo '<no output>'))"
fi
cp "$ENV_BACKUP" .env

# --- 7. GCP activation ------------------------------------------------------
echo "7. GCP_KEY_FILE activates the mount, and a missing key fails loudly"
out=$(GCP_KEY_FILE=/nonexistent/key.json ./claude.sh --shell -c true 2>&1)
status=$?
if [ "$status" -ne 0 ] && printf '%s\n' "$out" | grep -q '/nonexistent/key.json'; then
    pass "missing key exits non-zero and names the path"
else
    fail "missing key should abort naming the path (exit $status)"
fi

printf '{"type":"service_account"}' > "$KEY_FILE"
out=$(GCP_KEY_FILE="$KEY_FILE" ./claude.sh --shell -c \
    'echo "C=$GOOGLE_APPLICATION_CREDENTIALS"
     echo "K=${GCP_KEY_FILE:-<unset>}"
     cat /home/agent/.gcp/key.json' 2>&1)
if printf '%s\n' "$out" | grep -qx 'C=/home/agent/.gcp/key.json'; then
    pass "credentials point at the in-container path"
else
    fail "GOOGLE_APPLICATION_CREDENTIALS wrong or unset"
fi
if printf '%s\n' "$out" | grep -q 'service_account'; then
    pass "the key is actually readable at that path"
else
    fail "key not readable inside the container — the mount did not happen"
fi
# Asserted against the container's own environment rather than by grepping the
# whole transcript for the path: launcher chatter would make that a false alarm.
if printf '%s\n' "$out" | grep -qx 'K=<unset>'; then
    pass "host-side GCP_KEY_FILE path not forwarded"
else
    fail "the host-side key path is set inside the container ($(printf '%s\n' "$out" | grep '^K=' || true))"
fi

echo
if [ "$FAIL" -eq 0 ]; then
    printf 'All %d checks passed.\n' "$PASS"
else
    printf '%d passed, \033[31m%d failed\033[0m.\n' "$PASS" "$FAIL"
fi
exit "$FAIL"
