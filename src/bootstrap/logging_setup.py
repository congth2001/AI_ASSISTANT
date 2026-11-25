"""Console + rotating-file handlers for the application's own loggers.

Uvicorn only configures its ``uvicorn.*`` loggers, so without this the INFO
records of ``src.*`` (LLM usage, agent node metrics...) were dropped by Python's
last-resort handler. Third-party loggers are left at the default (WARNING+).
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

APP_LOGGERS = ("src", "main", "__main__")
LOG_FORMAT = "%(asctime)s %(levelname)s [%(process)d] %(name)s: %(message)s"
# Marks handlers added here, so a second create_app() replaces them instead of
# logging every record twice.
_OWNED = "_ai_assistant_handler"


def configure_logging(
    *,
    level: str = "INFO",
    file: Path | None = None,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
) -> None:
    formatter = logging.Formatter(LOG_FORMAT)
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if file is not None:
        file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(
            RotatingFileHandler(
                file, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8", delay=True
            )
        )
    for handler in handlers:
        handler.setFormatter(formatter)
        setattr(handler, _OWNED, True)

    for name in APP_LOGGERS:
        logger = logging.getLogger(name)
        for old in [h for h in logger.handlers if getattr(h, _OWNED, False)]:
            logger.removeHandler(old)
            old.close()
        logger.setLevel(level)
        for handler in handlers:
            logger.addHandler(handler)
