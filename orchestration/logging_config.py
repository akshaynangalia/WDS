"""
Run logging for the tool -- one line per event, to stdout.

Why stdout: on Posit Connect the app's stdout/stderr is what shows up in the
content's Logs panel; a log file may be read-only or never looked at. A file
copy is available (set WDS_LOG_FILE) but is strictly optional and best-effort.

Design rules:
    - Uses a dedicated "wds" logger, never the root logger, so it cannot
      interfere with Dash / werkzeug / gunicorn logging.
    - configure_logging() is idempotent -- safe to call from a module that a
      reloader or several workers import more than once.
    - Output is plain ASCII. Anything else is escaped, so a Windows console
      (cp1252) or an odd character in a user's data can never make logging
      itself raise.
    - Timestamps are UTC (marked with a trailing Z), the same clock as the run
      id, so a run id and its log lines can be matched by eye on any server.
    - Every line carries run=<id>. The id lives in a context variable, so
      engine code never has to pass it around.
    - Observability must never break the product: nothing here raises.

Environment variables:
    WDS_LOG_LEVEL   INFO (default), DEBUG, WARNING, ...
    WDS_LOG_FILE    optional extra log file; ignored (with a warning) if it
                    cannot be opened
    WDS_VERSION     overrides the code version reported in the logs
"""
from __future__ import annotations

import contextlib
import contextvars
import functools
import logging
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

LOGGER_NAME = "wds"
_FORMAT = "%(asctime)s | %(levelname)-7s | run=%(run_id)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%SZ"  # UTC, same clock as the run id and the Run Report

_run_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("wds_run_id", default="-")
_REPO_ROOT = Path(__file__).resolve().parent.parent


class _RunIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.run_id = _run_id_var.get()
        return True


# Punctuation that appears in the tool's own messages, mapped to readable ASCII;
# anything else non-ASCII is escaped rather than dropped.
_ASCII_MAP = str.maketrans({
    "—": "--", "–": "-", "→": "->", "×": "x", "≥": ">=", "≤": "<=",
    "…": "...", "‘": "'", "’": "'", "“": '"', "”": '"',
})


class _AsciiFormatter(logging.Formatter):
    converter = time.gmtime  # timestamps in UTC, matching run ids (which are UTC) and the Run Report

    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record).translate(_ASCII_MAP)
        return text.encode("ascii", "backslashreplace").decode("ascii")


def _make_handler(handler: logging.Handler) -> logging.Handler:
    handler.setFormatter(_AsciiFormatter(_FORMAT, _DATE_FORMAT))
    handler.addFilter(_RunIdFilter())
    return handler


def configure_logging() -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    if getattr(logger, "_wds_configured", False):
        return logger

    level_name = os.environ.get("WDS_LOG_LEVEL", "INFO").upper()
    logger.setLevel(getattr(logging, level_name, logging.INFO))
    logger.propagate = False  # avoid double lines if a host configures the root logger
    logger.addHandler(_make_handler(logging.StreamHandler(sys.stdout)))
    logger._wds_configured = True  # type: ignore[attr-defined]

    log_file = os.environ.get("WDS_LOG_FILE")
    if log_file:
        try:
            logger.addHandler(_make_handler(logging.FileHandler(log_file, encoding="utf-8")))
        except OSError as exc:
            logger.warning("LOG_FILE_UNAVAILABLE path=%s error=%s -- continuing with stdout only", log_file, exc)
    return logger


def new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]


@contextlib.contextmanager
def run_context(run_id: str):
    token = _run_id_var.set(run_id)
    try:
        yield
    finally:
        _run_id_var.reset(token)


@functools.lru_cache(maxsize=1)
def code_version() -> str:
    """Which code produced this run. WDS_VERSION env var wins; otherwise the
    VERSION file at the repo root, with the short git commit appended when git
    is available (development machines). On Posit Connect there is no .git, so
    the VERSION file alone is reported -- bump it in the release PR."""
    override = os.environ.get("WDS_VERSION", "").strip()
    if override:
        return override

    try:
        base = (_REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip() or "unknown"
    except OSError:
        base = "unknown"

    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=_REPO_ROOT, capture_output=True,
            text=True, timeout=2, check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        commit = ""
    return f"{base}+{commit}" if commit else base
