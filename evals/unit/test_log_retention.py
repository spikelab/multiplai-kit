"""Tests for log retention in log_utils.py.

Retention had a working implementation and a config knob, and neither was
connected to anything: `cleanup_old_logs` had no callers, so rotated logs —
which carry prompt text and routing decisions — accumulated on the host mount
forever. These tests pin the wiring, not just the function.
"""

import logging
import os
import time

import pytest

import log_utils
from log_utils import _get_retention_days, cleanup_old_logs, setup_logging


def _age(path, days):
    """Backdate a file's mtime by *days*."""
    old = time.time() - days * 86400
    os.utime(path, (old, old))


@pytest.fixture
def logs(tmp_path):
    d = tmp_path / "logs"
    d.mkdir()
    return d


@pytest.fixture(autouse=True)
def _reset_sweep_flag():
    """The sweep is once-per-process; each test needs a fresh process view."""
    log_utils._swept = False
    yield
    log_utils._swept = False


class TestCleanupOldLogs:
    def test_deletes_rotated_logs_past_the_cutoff(self, logs):
        stale = logs / "context-router-2026-01-01.log"
        fresh = logs / "context-router-2026-07-25.log"
        stale.write_text("old prompt text\n")
        fresh.write_text("today\n")
        _age(stale, 30)

        cleanup_old_logs(logs, retention_days=7)

        assert not stale.exists()
        assert fresh.exists()

    def test_deletes_legacy_rotating_handler_names(self, logs):
        legacy = logs / "context-router.log.2026-01-01"
        legacy.write_text("old\n")
        _age(legacy, 30)

        cleanup_old_logs(logs, retention_days=7)

        assert not legacy.exists()

    def test_zero_means_keep_forever(self, logs):
        stale = logs / "context-router-2020-01-01.log"
        stale.write_text("ancient\n")
        _age(stale, 2000)

        cleanup_old_logs(logs, retention_days=0)

        assert stale.exists()

    def test_leaves_undated_logs_alone(self, logs):
        """hook-errors.log is append-only and bounded by size, not by date."""
        errors = logs / "hook-errors.log"
        errors.write_text("boom\n")
        _age(errors, 400)

        cleanup_old_logs(logs, retention_days=7)

        assert errors.exists()

    def test_missing_directory_is_not_an_error(self, tmp_path):
        cleanup_old_logs(tmp_path / "nope", retention_days=7)


class TestRetentionIsWiredIntoSetup:
    """The bug was never in cleanup_old_logs — it was that nothing called it."""

    def test_setup_logging_sweeps_stale_logs(self, logs, monkeypatch):
        monkeypatch.setenv("MULTIPLAI_LOG_RETENTION_DAYS", "7")
        stale = logs / "context-router-2026-01-01.log"
        stale.write_text("old prompt text\n")
        _age(stale, 30)

        logger = setup_logging("sweep-test-1", log_dir=logs)
        try:
            assert not stale.exists()
        finally:
            for h in list(logger.handlers):
                logger.removeHandler(h)
                h.close()
            logging.getLogger("sweep-test-1").handlers.clear()

    def test_sweep_runs_once_per_process(self, logs, monkeypatch):
        """Hooks fire many times a session; the sweep must not stat the log
        directory on every logger construction."""
        monkeypatch.setenv("MULTIPLAI_LOG_RETENTION_DAYS", "7")
        calls = []
        monkeypatch.setattr(log_utils, "cleanup_old_logs",
                            lambda *a, **k: calls.append(a))

        for name in ("sweep-test-2", "sweep-test-3"):
            logger = setup_logging(name, log_dir=logs)
            for h in list(logger.handlers):
                logger.removeHandler(h)
                h.close()

        assert len(calls) == 1


class TestRetentionResolution:
    """Resolution order is env → multiplai.conf → built-in default.

    Each test pins _MULTIPLAI_HOME at a tmp dir, otherwise resolution reaches
    the developer's own runtime conf and the result depends on whose machine
    the suite runs on.
    """

    @pytest.fixture(autouse=True)
    def _isolate_conf(self, tmp_path, monkeypatch):
        monkeypatch.setattr(log_utils, "_MULTIPLAI_HOME", tmp_path)
        monkeypatch.delenv("MULTIPLAI_LOG_RETENTION_DAYS", raising=False)
        self.home = tmp_path

    def _write_conf(self, value):
        (self.home / "multiplai.conf").write_text(
            f"MULTIPLAI_LOG_LEVEL=INFO\nMULTIPLAI_LOG_RETENTION_DAYS={value}\n")

    def test_env_overrides_conf(self, monkeypatch):
        self._write_conf(30)
        monkeypatch.setenv("MULTIPLAI_LOG_RETENTION_DAYS", "3")
        assert _get_retention_days() == 3

    def test_conf_is_read_when_env_is_unset(self):
        self._write_conf(30)
        assert _get_retention_days() == 30

    def test_unparseable_env_falls_through_to_conf(self, monkeypatch):
        self._write_conf(30)
        monkeypatch.setenv("MULTIPLAI_LOG_RETENTION_DAYS", "forever")
        assert _get_retention_days() == 30

    def test_default_applies_with_no_env_and_no_conf(self):
        assert _get_retention_days() == log_utils._DEFAULT_RETENTION_DAYS

    def test_negative_never_moves_the_cutoff_into_the_future(self, monkeypatch):
        """A negative value would put the cutoff ahead of now and delete every
        rotated log — it must fall back, not be honoured."""
        monkeypatch.setenv("MULTIPLAI_LOG_RETENTION_DAYS", "-1")
        assert _get_retention_days() == log_utils._DEFAULT_RETENTION_DAYS

    def test_zero_is_honoured_as_keep_forever(self, monkeypatch):
        monkeypatch.setenv("MULTIPLAI_LOG_RETENTION_DAYS", "0")
        assert _get_retention_days() == 0
