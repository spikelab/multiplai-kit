"""Shared logging utilities for Claude Code hooks and skills.

Provides a standard log format across all components:
    [YYYY-MM-DDTHH:MM:SSZ] [component] [session:xxxxxxxx] LEVEL: message

Usage:
    from log_utils import setup_logging
    logger = setup_logging("context-router", session_id="abc123...")
    logger.info("RETRIEVE prompt=%s result=%d chars", prompt[:200], len(result))

State files (nudge sidecars, stop counters) go in logs/state/, not logs/.
"""

from __future__ import annotations

import glob as glob_mod
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

_CONFIG_DIR = Path(os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude")))
# Kit project root — runtime artifacts live here, not in dotfiles/
_MULTIPLAI_HOME = Path(os.environ.get("CLAUDE_MULTIPLAI_HOME", str(_CONFIG_DIR.parent)))

LOG_DIR = _MULTIPLAI_HOME / "runtime" / "logs"
STATE_DIR = LOG_DIR / "state"

# Ensure directories exist on import — best-effort. An unwritable
# CLAUDE_MULTIPLAI_HOME must not kill every hook that merely imports this
# module; setup_logging() re-attempts the mkdir loudly for callers that
# actually need the directory.
try:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    pass

# Default retention — overridden by MULTIPLAI_LOG_RETENTION_DAYS in multiplai.conf
_DEFAULT_RETENTION_DAYS = 7

# Oversize ceiling for append-only logs (hook-errors.log), per the logging
# standard: "truncated to ~100KB when oversized".
_ERROR_LOG_MAX_BYTES = 100 * 1024

# Retention runs once per process, on first setup_logging() call. Hooks are
# short-lived processes fired many times a session, so sweeping on every
# logger construction would stat the whole log dir for no benefit.
_swept = False


def _truncate_oversized(path: Path, max_bytes: int = _ERROR_LOG_MAX_BYTES) -> None:
    """Truncate an append-only log to its most recent tail when oversized.

    Keeps roughly half of *max_bytes* so truncation runs infrequently.
    Rewrites in place (same inode) so concurrent O_APPEND writers keep
    working; a few lines may interleave during the rewrite — acceptable
    for a best-effort error sink. Never raises.
    """
    try:
        if not path.exists() or path.stat().st_size <= max_bytes:
            return
        keep = max_bytes // 2
        with path.open("r+b") as f:
            f.seek(-keep, os.SEEK_END)
            tail = f.read()
            nl = tail.find(b"\n")
            if nl != -1:
                tail = tail[nl + 1:]
            f.seek(0)
            f.write(b"[truncated: exceeded %d bytes]\n" % max_bytes + tail)
            f.truncate()
    except OSError:
        pass


def _get_retention_days() -> int:
    """Read log retention from multiplai.conf. 0 = keep forever. Default 7.

    A negative value falls back to the default rather than being honoured: it
    would put the cutoff in the future and delete every rotated log.
    """
    # Check env first (set by conf loader or manually)
    env_val = os.environ.get("MULTIPLAI_LOG_RETENTION_DAYS")
    if env_val is not None:
        try:
            n = int(env_val)
            return n if n >= 0 else _DEFAULT_RETENTION_DAYS
        except ValueError:
            pass

    # Read from multiplai.conf directly (lightweight — no full conf parser
    # needed). This branch stays even though run-hook-python exports the env
    # var: plugin skills import this module outside run-hook-python, where the
    # env var is absent. Parsing must match run-hook-python's: drop an inline
    # `#` comment, strip whitespace, then one layer of quotes — a value like
    # `7  # one week` used to fail int() here and silently fall back to 7 only
    # by accident of the default.
    conf_path = _MULTIPLAI_HOME / "multiplai.conf"
    if conf_path.exists():
        try:
            for line in conf_path.read_text().splitlines():
                line = line.strip()
                if line.startswith("MULTIPLAI_LOG_RETENTION_DAYS"):
                    _, _, val = line.partition("=")
                    val = val.split("#", 1)[0].strip().strip('"').strip("'")
                    n = int(val)
                    return n if n >= 0 else _DEFAULT_RETENTION_DAYS
        except (OSError, ValueError):
            pass

    return _DEFAULT_RETENTION_DAYS


class _SessionFormatter(logging.Formatter):
    """Formatter that injects session_id into every log line."""

    def __init__(self, session_id: str = ""):
        self.session_id = session_id[:8] if session_id else "--------"
        super().__init__(
            fmt=f"[%(asctime)s] [%(name)s] [session:{self.session_id}] %(levelname)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%SZ",
        )
        self.converter = lambda *_: datetime.now(timezone.utc).timetuple()


class _DailyFileHandler(logging.FileHandler):
    """File handler that writes to name-YYYY-MM-DD.log, rotating at midnight UTC.

    Unlike TimedRotatingFileHandler, this uses the date-prefixed format
    (e.g. context-router-2026-04-16.log) so files are recognized as .log
    by editors and tools.
    """

    def __init__(self, log_dir: Path, name: str):
        self._log_dir = log_dir
        self._name = name
        self._current_date = self._utc_date()
        filepath = self._log_path(self._current_date)
        super().__init__(filepath, mode="a")

    @staticmethod
    def _utc_date() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _log_path(self, date_str: str) -> str:
        return str(self._log_dir / f"{self._name}-{date_str}.log")

    def emit(self, record: logging.LogRecord) -> None:
        today = self._utc_date()
        if today != self._current_date:
            # Date rolled over — switch to new file
            self._current_date = today
            self.close()
            self.baseFilename = self._log_path(today)
            self.stream = self._open()
        super().emit(record)


def cleanup_old_logs(log_dir: Path | None = None, retention_days: int | None = None) -> None:
    """Delete rotated log files older than retention_days.

    If retention_days is 0, no files are deleted (keep forever).
    Also cleans up TimedRotatingFileHandler legacy files (name.log.YYYY-MM-DD).
    """
    if log_dir is None:
        log_dir = LOG_DIR
    if retention_days is None:
        retention_days = _get_retention_days()
    if retention_days == 0:
        return  # Keep forever

    cutoff_ts = (datetime.now(timezone.utc).timestamp()
                 - retention_days * 86400)

    # Standard format: name-YYYY-MM-DD.log
    for log_path in glob_mod.glob(str(log_dir / "*-????-??-??.log")):
        try:
            if Path(log_path).stat().st_mtime < cutoff_ts:
                Path(log_path).unlink()
        except OSError:
            continue

    # Legacy TimedRotatingFileHandler format: name.log.YYYY-MM-DD
    for log_path in glob_mod.glob(str(log_dir / "*.log.????-??-??")):
        try:
            if Path(log_path).stat().st_mtime < cutoff_ts:
                Path(log_path).unlink()
        except OSError:
            continue


def setup_logging(
    name: str,
    session_id: str = "",
    log_dir: Path | None = None,
    stderr: bool = False,
    package: str | None = None,
) -> logging.Logger:
    """Configure a named logger following the multiplai standard.

    Args:
        name: Component name (e.g., "context-router", "extract", "deep-research").
              Used as both the logger name and the log file prefix.
        session_id: Claude Code session ID. First 8 chars appear in every log line.
        log_dir: Override log directory. Defaults to $CLAUDE_MULTIPLAI_HOME/runtime/logs/.
        stderr: Also log to stderr. Use for skills that run as subprocesses where
                terminal output should be visible in the Claude Code session.
        package: Optional Python package name (e.g., "research_pipeline"). When set,
                the same handlers + level are attached to that package's logger so
                submodules using `logging.getLogger(__name__)` inside the package
                propagate to these handlers. Required when `name` is hyphenated and
                the package name is underscored (Python logging hierarchies are
                strictly dot-separated — "deep-research" and "research_pipeline.sdk"
                share no parent, so handlers on one don't catch the other).

    Returns:
        Configured logger instance.
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        # Already configured — just update session_id on existing formatters
        sid = session_id[:8] if session_id else "--------"
        for handler in logger.handlers:
            if isinstance(handler.formatter, _SessionFormatter):
                handler.formatter.session_id = sid
                handler.formatter._fmt = (
                    f"[%(asctime)s] [%(name)s] [session:{sid}] %(levelname)s: %(message)s"
                )
        return logger

    if log_dir is None:
        log_dir = LOG_DIR
    log_dir.mkdir(parents=True, exist_ok=True)

    # Enforce retention. Without this call the setting is decoration: rotated
    # logs hold prompt text and routing decisions, and they sit on the host
    # mount forever. Once per process, and never fatal.
    global _swept
    if not _swept:
        _swept = True
        cleanup_old_logs(log_dir)

    # Level from config
    level = os.environ.get("MULTIPLAI_LOG_LEVEL", "INFO").upper()
    if os.environ.get("MULTIPLAI_DEBUG", "false").lower() == "true":
        level = "DEBUG"
    logger.setLevel(getattr(logging, level, logging.INFO))

    formatter = _SessionFormatter(session_id)

    # File handler — date-named files (name-YYYY-MM-DD.log)
    handler = _DailyFileHandler(log_dir, name)
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    # Error handler — also write ERROR+ to shared hook-errors.log.
    # Enforce the oversize ceiling before binding — nothing else ever
    # truncates this file.
    _truncate_oversized(log_dir / "hook-errors.log")
    err_handler = logging.FileHandler(log_dir / "hook-errors.log")
    err_handler.setLevel(logging.ERROR)
    err_handler.setFormatter(formatter)
    logger.addHandler(err_handler)

    # Stderr handler — for skills running as subprocesses
    if stderr:
        stderr_handler = logging.StreamHandler()
        stderr_handler.setFormatter(formatter)
        logger.addHandler(stderr_handler)

    # Bridge the named logger's handlers to a package logger so submodule loggers
    # (logging.getLogger(__name__)) propagate up to these handlers.
    if package and package != name:
        pkg_logger = logging.getLogger(package)
        if not pkg_logger.handlers:
            pkg_logger.setLevel(logger.level)
            for h in logger.handlers:
                pkg_logger.addHandler(h)

    return logger


def get_state_dir() -> Path:
    """Return the session state directory (logs/state/). Created on import."""
    return STATE_DIR


def get_log_dir() -> Path:
    """Return the log directory ($CLAUDE_MULTIPLAI_HOME/runtime/logs/)."""
    return LOG_DIR
