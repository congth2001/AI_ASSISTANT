"""Select config files; delegate parsing, merging and validation to Pydantic Settings."""
import os
from pathlib import Path

import yaml
from pydantic import ValidationError
from pydantic_settings import SettingsError, YamlConfigSettingsSource

from config.settings import BACKEND_DIR, DatabaseConfiguration, DatabaseSettings, Settings
from src.common.errors import ConfigurationError


class ConfigManager:
    def __init__(self, config_path: str | Path | None = None, *, env_file: str | Path | None = BACKEND_DIR / ".env"):
        self._requested_path = config_path
        self.env_file = self._resolve(env_file) if env_file is not None else None
        self._settings: Settings | None = None
        self._database: DatabaseSettings | None = None

    @staticmethod
    def _resolve(path: str | Path) -> Path:
        path = Path(path).expanduser()
        return path.resolve() if path.is_absolute() else (BACKEND_DIR / path).resolve()

    @property
    def config_path(self) -> Path | None:
        selected = self._requested_path or os.getenv("AI_ASSISTANT_CONFIG_FILE")
        if selected:
            path = self._resolve(selected)
            if not path.is_file():
                raise FileNotFoundError(f"Configuration file not found: {path}")
            if path.suffix.lower() not in {".yaml", ".yml"}:
                raise ConfigurationError("AI_ASSISTANT_CONFIG_FILE/config_path must select a YAML file")
            return path
        # One documented development default, never a local/development/production search.
        default = BACKEND_DIR / "config/local.yml"
        return default if default.is_file() else None

    def _load(self, model):
        path = self.config_path
        try:
            values = YamlConfigSettingsSource(model, yaml_file=path, yaml_file_encoding="utf-8")()
            if not isinstance(values, dict):
                raise ConfigurationError("YAML configuration must be a mapping")
            if model is DatabaseConfiguration:
                values = {key: value for key, value in values.items() if key == "database"}
            return model(_env_file=self.env_file, **values)
        except ValidationError as exc:
            details = "; ".join(
                f"{'.'.join(map(str, error['loc']))}: {error['msg']}"
                for error in exc.errors(include_input=False, include_url=False)
            )
            raise ConfigurationError(f"Configuration validation failed: {details}") from None
        except (yaml.YAMLError, SettingsError, ValueError, TypeError):
            raise ConfigurationError("Cannot parse configuration; check YAML, JSON environment values and PostgreSQL URL") from None

    def get_settings(self) -> Settings:
        if self._settings is None:
            self._settings = self._load(Settings)
            self._database = self._settings.database
        return self._settings

    def get_database_settings(self) -> DatabaseSettings:
        if self._database is None:
            self._database = self._load(DatabaseConfiguration).database
        return self._database

    def load_config(self) -> dict:
        """Compatibility entry point: validated data with SecretStr values still protected."""
        return self.get_settings().model_dump()

    def reload_config(self) -> Settings:
        """Invalidate both caches; existing DI singletons require an application restart."""
        self._settings = None
        self._database = None
        return self.get_settings()


config_manager = ConfigManager()


def get_settings() -> Settings:
    return config_manager.get_settings()


def get_database_settings() -> DatabaseSettings:
    return config_manager.get_database_settings()


def reload_config() -> Settings:
    return config_manager.reload_config()
