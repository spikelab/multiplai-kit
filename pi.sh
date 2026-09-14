#!/bin/bash
# pi.sh — Launch the pi coding agent in the multiplai container.
#
# A wrapper, not a second launcher. Everything that makes a session safe and
# usable — the sandbox, the workspace and kit mounts, git identity, the GH
# token, env forwarding, the SSH host bridge — is agent-agnostic and already
# lives in claude.sh. Forking it would mean maintaining two copies of that and
# watching them drift.
#
# Usage:
#   ./pi.sh                          # pi on the default (deepseek) profile
#   ./pi.sh --pi-profile kimi        # a different model profile
#   ./pi.sh --profile work           # work git identity, deepseek profile
#   ./pi.sh -p "summarise this repo" # pi flags pass straight through
#
# A pi profile is a whole ~/.pi directory: models.json, credentials, installed
# packages, session history. See docs/pi.md.

set -euo pipefail

exec "$(cd "$(dirname "$0")" && pwd)/claude.sh" --pi "$@"
