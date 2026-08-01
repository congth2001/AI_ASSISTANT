"""
Configuration Manager
Handles loading and validation of application configuration
"""
import yaml
from pathlib import Path
from typing import Dict, Any, Optional
from pydantic import ValidationError

from config.settings import Settings


class ConfigManager:
    """Configuration manager for loading settings from various sources"""

    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize config manager

        Args:
            config_path: Path to config file (YAML or .env)
        """
        self.config_path = config_path or self._get_default_config_path()
        self._config_data: Optional[Dict[str, Any]] = None

    def _get_default_config_path(self) -> str:
        """Get default config path based on environment"""
        # Check for .env file first
        env_file = Path(".env")
        if env_file.exists():
            return str(env_file)

        # Check for YAML config files
        yaml_files = [
            "config/local.yml",
            "config/development.yml",
            "config/production.yml"
        ]

        for yaml_file in yaml_files:
            if Path(yaml_file).exists():
                return yaml_file

        # Default to local.yml
        return "config/local.yml"

    def load_config(self) -> Dict[str, Any]:
        """
        Load configuration from file

        Returns:
            Dict containing configuration data
        """
        if self._config_data is not None:
            return self._config_data

        config_path = Path(self.config_path)

        if not config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_path}")

        # Load based on file extension
        if config_path.suffix.lower() in ['.yml', '.yaml']:
            self._config_data = self._load_yaml_config(config_path)
        elif config_path.suffix.lower() == '.env':
            self._config_data = self._load_env_config(config_path)
        else:
            raise ValueError(f"Unsupported config file format: {config_path.suffix}")

        return self._config_data

    def _load_yaml_config(self, config_path: Path) -> Dict[str, Any]:
        """Load configuration from YAML file"""
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f) or {}
            return config
        except Exception as e:
            raise RuntimeError(f"Failed to load YAML config from {config_path}: {e}")

    def _load_env_config(self, config_path: Path) -> Dict[str, Any]:
        """Load configuration from .env file"""
        config = {}

        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue

                    if '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = value.strip()

                        # Remove quotes if present
                        if (value.startswith('"') and value.endswith('"')) or \
                           (value.startswith("'") and value.endswith("'")):
                            value = value[1:-1]

                        # Convert to nested dict using __ delimiter
                        self._set_nested_config(config, key, value)

            return config
        except Exception as e:
            raise RuntimeError(f"Failed to load .env config from {config_path}: {e}")

    def _set_nested_config(self, config: Dict[str, Any], key: str, value: str):
        """Set nested configuration value using __ delimiter"""
        keys = key.split('__')
        current = config

        for k in keys[:-1]:
            if k not in current:
                current[k] = {}
            current = current[k]

        # Convert value to appropriate type
        final_key = keys[-1]
        current[final_key] = self._convert_value(value)

    def _convert_value(self, value: str) -> Any:
        """Convert string value to appropriate type"""
        # Handle boolean values
        if value.lower() in ['true', 'false']:
            return value.lower() == 'true'

        # Handle None/null values
        if value.lower() in ['none', 'null', '']:
            return None

        # Handle numeric values
        try:
            # Try int first
            if '.' not in value:
                return int(value)
            # Try float
            return float(value)
        except ValueError:
            pass

        # Return as string
        return value

    def get_settings(self) -> Settings:
        """
        Get validated Pydantic settings

        Returns:
            Settings instance
        """
        config_data = self.load_config()

        try:
            return Settings(**config_data)
        except ValidationError as e:
            raise RuntimeError(f"Configuration validation failed: {e}")

    def _flatten_config(self, config: Dict[str, Any], prefix: str = "") -> Dict[str, str]:
        """Flatten nested config dict to key-value pairs"""
        result = {}

        for key, value in config.items():
            full_key = f"{prefix}__{key}" if prefix else key

            if isinstance(value, dict):
                result.update(self._flatten_config(value, full_key))
            else:
                result[full_key] = value

        return result

    def reload_config(self):
        """Reload configuration from file"""
        self._config_data = None
        self.load_config()


# Global config manager instance
config_manager = ConfigManager()


def get_settings() -> Settings:
    """Get application settings"""
    return config_manager.get_settings()


def reload_config():
    """Reload configuration"""
    config_manager.reload_config()