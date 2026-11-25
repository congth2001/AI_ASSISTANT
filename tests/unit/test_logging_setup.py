"""Application loggers write INFO to a rotating file; third-party loggers stay quiet."""
import logging

import pytest

from config.settings import BACKEND_DIR, LoggingSettings
from src.bootstrap import logging_setup
from src.bootstrap.logging_setup import APP_LOGGERS, configure_logging


@pytest.fixture
def restore_app_loggers():
    saved = {
        name: (logging.getLogger(name).level, list(logging.getLogger(name).handlers))
        for name in APP_LOGGERS
    }
    yield
    for name, (level, handlers) in saved.items():
        logger = logging.getLogger(name)
        for handler in list(logger.handlers):
            if handler not in handlers:
                logger.removeHandler(handler)
                handler.close()
        logger.setLevel(level)


def _flush(name="src"):
    for handler in logging.getLogger(name).handlers:
        handler.flush()


def test_info_from_src_reaches_the_file_but_third_party_info_does_not(tmp_path, restore_app_loggers):
    log_file = tmp_path / "logs" / "ai_assistant.log"
    configure_logging(level="INFO", file=log_file)

    logging.getLogger("src.modules.assistant.infrastructure.llm.openai_adapter").info(
        "LLM usage [generate] cached=6912"
    )
    logging.getLogger("httpx").info("HTTP Request: POST https://api.openai.com")
    _flush()

    content = log_file.read_text(encoding="utf-8")
    assert "INFO" in content and "LLM usage [generate] cached=6912" in content
    assert "openai_adapter" in content
    assert "HTTP Request" not in content


def test_configuring_twice_does_not_duplicate_records(tmp_path, restore_app_loggers):
    log_file = tmp_path / "app.log"
    configure_logging(file=log_file)
    configure_logging(file=log_file)

    logging.getLogger("src.x").info("once")
    _flush()

    assert log_file.read_text(encoding="utf-8").count("once") == 1
    owned = [h for h in logging.getLogger("src").handlers if getattr(h, logging_setup._OWNED, False)]
    assert len(owned) == 2  # console + file


def test_level_filters_records(tmp_path, restore_app_loggers):
    log_file = tmp_path / "app.log"
    configure_logging(level="WARNING", file=log_file)

    logging.getLogger("src.x").info("hidden")
    logging.getLogger("src.x").warning("shown")
    _flush()

    content = log_file.read_text(encoding="utf-8")
    assert "shown" in content and "hidden" not in content


def test_logging_settings_resolve_paths_from_backend_dir():
    assert LoggingSettings().file_path() == BACKEND_DIR / "logs" / "ai_assistant.log"
    assert LoggingSettings(file="").file_path() is None
    assert LoggingSettings(level="INFO").level == "INFO"
    with pytest.raises(ValueError):
        LoggingSettings(level="VERBOSE")


@pytest.mark.parametrize("enabled", [True, False])
def test_create_app_configures_logging_from_settings(monkeypatch, enabled):
    import main

    settings = main.get_settings().model_copy(
        update={"logging": LoggingSettings(enabled=enabled, level="WARNING", file="")}
    )
    calls = []
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    monkeypatch.setattr(main, "configure_logging", lambda **kwargs: calls.append(kwargs))

    main.create_app()

    assert calls == ([{"level": "WARNING", "file": None, "max_bytes": 10 * 1024 * 1024,
                       "backup_count": 5}] if enabled else [])
