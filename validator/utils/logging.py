"""Structured logging with file rotation.

Provides dual-output logging: human-readable to stdout for real-time monitoring,
and timestamped file output with daily rotation for post-incident analysis.
Log files are stored in ~/.zhen/logs/.
"""

from __future__ import annotations

import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"
LOG_DIR = Path.home() / ".zhen" / "logs"
BACKUP_COUNT = 14


def setup_logging(component: str = "validator", log_level: str = "INFO") -> None:
    """Configure logging with stdout and rotating file output.

    Sets up dual handlers on the root logger: a StreamHandler for stdout
    and a TimedRotatingFileHandler for persistent logs. Suppresses noisy
    third-party loggers.

    Args:
        component: Name used in log filename (e.g., "validator", "miner").
        log_level: Logging level string (DEBUG, INFO, WARNING, ERROR).
    """
    level = getattr(logging, log_level.upper(), logging.INFO)

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(fmt=LOG_FORMAT, datefmt=LOG_DATEFMT)

    # Stdout handler
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    stream_handler.setLevel(level)

    # Rotating file handler (daily, 14-day retention)
    log_file = LOG_DIR / f"{component}.log"
    file_handler = TimedRotatingFileHandler(
        filename=str(log_file),
        when="midnight",
        interval=1,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(level)

    # Configure root logger
    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(stream_handler)
    root.addHandler(file_handler)

    # Suppress noisy third-party loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("bittensor").setLevel(logging.WARNING)
