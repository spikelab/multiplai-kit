# Logging Standard

All hooks, skills, and pipeline code MUST follow this standard for consistent, parseable logs.

## Log Line Format

Every log line follows this pattern:

```
[YYYY-MM-DDTHH:MM:SSZ] [component] [session:xxxxxxxx] LEVEL: message
```

| Field | Description |
|-------|-------------|
| Timestamp | UTC, ISO 8601, always ends with `Z` |
| Component | Logger name (e.g., `context`, `extract`, `deep-research`, `build-pipeline`) |
| Session | First 8 chars of the Claude Code session ID. Use `--------` if unknown |
| Level | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| Message | Freeform text. Use `key=value` pairs for structured data |

**Example lines:**
```
[2026-04-10T00:51:16Z] [context] [session:c6a0d827] INFO: RETRIEVE prompt="I was showing..." routing={"memory":["claude-code-tools.md"]} result=13301 chars
[2026-04-10T00:39:13Z] [context] [session:4f869fed] INFO: SKIP reason=short-continuation prompt="yes"
[2026-04-09T04:35:29Z] [deep-research] [session:abc12345] INFO: SDK call [plan] prompt=3479 bytes tools=none timeout=600s
[2026-04-09T22:52:00Z] [extract] [session:e15d583c] INFO: DONE status=ok units=2 learnings=1
```

> The session-lifecycle/context-router hooks named in older versions of this
> doc now live in the `multiplai-context` plugin; the format is unchanged.

## Infrastructure

- **Log directory:** `$CLAUDE_CONFIG_DIR/logs/`
- **State directory:** `$CLAUDE_CONFIG_DIR/logs/state/` — session state files (nudge sidecars, stop counters). NOT logs.
- **Configuration:** `$CLAUDE_CONFIG_DIR/multiplai.conf` controls log level:
  ```bash
  MULTIPLAI_LOG_LEVEL=INFO  # DEBUG | INFO | WARNING | ERROR
  ```
- **Debug toggle:** `MULTIPLAI_DEBUG=true` enables DEBUG level (aliased to LOG_LEVEL=DEBUG)

## Directory Layout

Current-day logs are undated; the previous day rotates to `<name>-YYYY-MM-DD.log`
on the first write of a new UTC day (retention via `MULTIPLAI_LOG_RETENTION_DAYS`).

```
logs/
├── deep-research.log          # Current day's deep research log
├── deep-research-2026-04-09.log  # Rotated (dated)
├── extract.log                # Extraction output (rotated daily)
├── activity.log               # Curated human-readable event log
├── activity.jsonl             # Structured mirror of activity.log
├── hook-errors.log            # ERROR+ from all components (append-only)
├── state/
│   ├── nudge-{session_id}.json    # Per-session nudge/dedup state
│   └── stop-count-{session_id}    # Per-session turn counter
```

**What does NOT go in logs/:**
- Session state files belong in `logs/state/`, not the logs root
- Per-session log files (use date-based rotation instead)

## Python Standard

Use the shared `log_utils.py` module (in `hooks/`):

```python
from log_utils import setup_logging

logger = setup_logging("my-component", session_id="abc123...")
logger.info("Processing %d items", count)
logger.debug("Item details: %s", item)
logger.warning("Retrying after timeout")
logger.error("Failed to connect: %s", err)
```

`setup_logging()` (from `multiplai_core.log_utils`) configures:
- A date-rotated file handler: `<name>.log` current, `<name>-YYYY-MM-DD.log`
  rotated on UTC day change (retention via `MULTIPLAI_LOG_RETENTION_DAYS`)
- Error handler writing ERROR+ to shared `hook-errors.log`
- Standard format with session ID baked in

For scripts that run as subprocesses with shell-level output capture (like `extract_learnings.py`), use a simple stderr logging helper instead:

```python
from datetime import datetime, timezone

def _log(level: str, session_id: str, msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    sid = session_id[:8] if session_id else "--------"
    print(f"[{ts}] [my-component] [session:{sid}] {level}: {msg}", file=sys.stderr)
```

## Shell Standard

```bash
LOGS_DIR="$CLAUDE_CONFIG_DIR/logs"
STATE_DIR="$LOGS_DIR/state"
SCRIPT_NAME="my-component"

_log() {
  local sid="${SESSION_ID:0:8}"
  sid="${sid:---------}"
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] [$SCRIPT_NAME] [session:$sid] $*" \
    >> "$LOGS_DIR/$SCRIPT_NAME.log" 2>/dev/null || true
}
_debug() { $MULTIPLAI_DEBUG && _log "DEBUG: $*"; }
_error() {
  _log "ERROR: $*"
  local sid="${SESSION_ID:0:8}"
  sid="${sid:---------}"
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] [$SCRIPT_NAME] [session:$sid] ERROR: $*" \
    >> "$LOGS_DIR/hook-errors.log" 2>/dev/null || true
}
```

## What to Log

| Level | When |
|-------|------|
| **ERROR** | Failures that prevent the operation from completing |
| **WARNING** | Recoverable issues, fallbacks triggered, retries |
| **INFO** | Operation start/complete, key decisions, state transitions |
| **DEBUG** | Data shapes, API payloads, intermediate values, timing |

## Structured Message Conventions

Use consistent verb prefixes for parseable messages:

| Prefix | Usage |
|--------|-------|
| `START` | Operation beginning (include key params) |
| `DONE` | Operation completed (include result summary) |
| `SKIP` | Operation skipped (include reason) |
| `FAIL` | Operation failed (include error) |
| `RETRIEVE` | Memory/resource retrieval result |

Use `key=value` pairs for structured data:
```
INFO: RETRIEVE prompt="help me write..." routing={"memory":["core-voice.md"]} result=5000 chars
INFO: SKIP reason=short-continuation prompt="yes"
INFO: DONE status=ok units=3 learnings=5
ERROR: FAIL reason=SDK timeout after 30s
```

## What NOT to Log

- Secrets, API keys, tokens (even at DEBUG)
- Full file contents (log line counts or checksums instead)
- User PII beyond what's already in the session context
- Redundant lines (don't log the same event from both caller and callee)

## Rotation & Retention

- The date-rotated file handler archives the prior day to `<name>-YYYY-MM-DD.log`
  on the first write of a new UTC day
- A directory-wide sweep prunes dated logs older than
  `MULTIPLAI_LOG_RETENTION_DAYS` (default 7)
- **Append-only logs** (`hook-errors.log`) are truncated to their most
  recent ~50KB tail once they exceed 100KB. Enforced by `setup_logging()`
  in `log_utils` (both the kit's `dotfiles/hooks/log_utils.py` and
  `multiplai_core.log_utils`) before the error handler binds
- **Session state files** are cleaned up by the `multiplai-context` plugin's
  lifecycle hooks
