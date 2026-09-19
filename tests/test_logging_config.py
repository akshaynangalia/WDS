from __future__ import annotations

import logging
from pathlib import Path

import pytest

from orchestration import logging_config


@pytest.fixture
def fresh_wds_logger():
    """Isolate the process-wide "wds" logger so tests can configure it freely."""
    logger = logging.getLogger(logging_config.LOGGER_NAME)
    saved = (list(logger.handlers), logger.level, logger.propagate, getattr(logger, "_wds_configured", None))
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
    if hasattr(logger, "_wds_configured"):
        del logger._wds_configured
    yield logger
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
    for handler in saved[0]:
        logger.addHandler(handler)
    logger.setLevel(saved[1])
    logger.propagate = saved[2]
    if saved[3] is None:
        if hasattr(logger, "_wds_configured"):
            del logger._wds_configured
    else:
        logger._wds_configured = saved[3]


def test_configure_logging_is_idempotent(fresh_wds_logger, capsys):
    # A reloader / several workers may import the app more than once: the
    # handler must be added exactly once or every line prints twice.
    logging_config.configure_logging()
    logging_config.configure_logging()
    logging_config.configure_logging()
    assert len(fresh_wds_logger.handlers) == 1

    logging.getLogger("wds.run").info("hello")
    assert capsys.readouterr().out.count("hello") == 1


def test_every_line_carries_the_run_id(fresh_wds_logger, capsys):
    logging_config.configure_logging()
    with logging_config.run_context("20260919-101503-a1b2"):
        logging.getLogger("wds.run").info("inside a run")
    logging.getLogger("wds.run").info("outside a run")

    lines = capsys.readouterr().out.splitlines()
    assert "run=20260919-101503-a1b2" in lines[0] and "inside a run" in lines[0]
    assert "run=-" in lines[1] and "outside a run" in lines[1]


def test_output_is_always_ascii(fresh_wds_logger, capsys):
    # A cp1252 Windows console, or an odd character in a user's data, must never
    # make logging itself raise. Common punctuation becomes readable ASCII; any
    # other non-ASCII character is escaped, never dropped.
    logging_config.configure_logging()
    logging.getLogger("wds.run").info("Target DOS → 25 — café 中")

    out = capsys.readouterr().out
    assert out.isascii()
    assert "Target DOS -> 25 -- caf" in out
    assert "\\xe9" in out and "\\u4e2d" in out


def test_unwritable_log_file_is_not_fatal(fresh_wds_logger, monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("WDS_LOG_FILE", str(tmp_path / "no_such_dir" / "app.log"))
    logging_config.configure_logging()  # must not raise

    assert len(fresh_wds_logger.handlers) == 1  # stdout only
    assert "LOG_FILE_UNAVAILABLE" in capsys.readouterr().out


def test_optional_log_file_receives_lines(fresh_wds_logger, monkeypatch, tmp_path):
    log_file = tmp_path / "app.log"
    monkeypatch.setenv("WDS_LOG_FILE", str(log_file))
    logging_config.configure_logging()
    logging.getLogger("wds.run").info("to the file too")
    for handler in fresh_wds_logger.handlers:
        handler.flush()
    assert "to the file too" in log_file.read_text(encoding="utf-8")


def test_code_version_env_override_wins(monkeypatch):
    monkeypatch.setenv("WDS_VERSION", "9.9.9-test")
    logging_config.code_version.cache_clear()
    try:
        assert logging_config.code_version() == "9.9.9-test"
    finally:
        logging_config.code_version.cache_clear()


def test_code_version_reports_the_version_file(monkeypatch):
    monkeypatch.delenv("WDS_VERSION", raising=False)
    logging_config.code_version.cache_clear()
    try:
        version_file = Path(logging_config._REPO_ROOT) / "VERSION"
        assert logging_config.code_version().startswith(version_file.read_text(encoding="utf-8").strip())
    finally:
        logging_config.code_version.cache_clear()


def test_run_ids_are_unique_and_sortable():
    ids = {logging_config.new_run_id() for _ in range(50)}
    assert len(ids) == 50
