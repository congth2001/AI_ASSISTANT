"""
Logger Configuration for AI Assistant Service
"""
import os
from pathlib import Path
from typing import Dict, Any, Optional


class LoggerConfig:
    """Configuration class for logger settings"""
    
    def __init__(self):
        self.base_dir = Path("logs")
        self.base_dir.mkdir(exist_ok=True)
        
        # Log levels
        self.console_level = os.getenv("LOG_CONSOLE_LEVEL", "INFO")
        self.file_level = os.getenv("LOG_FILE_LEVEL", "DEBUG")
        self.error_level = os.getenv("LOG_ERROR_LEVEL", "ERROR")
        
        # File settings
        self.max_file_size = int(os.getenv("LOG_MAX_FILE_SIZE", "10485760"))  # 10MB
        self.backup_count = int(os.getenv("LOG_BACKUP_COUNT", "5"))
        
        # Performance logging
        self.enable_performance_logging = os.getenv("LOG_ENABLE_PERFORMANCE", "true").lower() == "true"
        self.performance_log_file = self.base_dir / "performance.log"
        
        # API logging
        self.enable_api_logging = os.getenv("LOG_ENABLE_API", "true").lower() == "true"
        self.api_log_file = self.base_dir / "api.log"
        
        # Database logging
        self.enable_database_logging = os.getenv("LOG_ENABLE_DATABASE", "true").lower() == "true"
        self.database_log_file = self.base_dir / "database.log"
        
        # JSON logging
        self.enable_json_logging = os.getenv("LOG_ENABLE_JSON", "false").lower() == "true"
        
        # Color console output
        self.enable_colors = os.getenv("LOG_ENABLE_COLORS", "true").lower() == "true"
        
        # Log format
        self.console_format = "%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s"
        self.file_format = "%(asctime)s | %(levelname)-8s | %(name)-20s | %(module)s:%(funcName)s:%(lineno)d | %(message)s"
        self.date_format = "%Y-%m-%d %H:%M:%S"
    
    def get_log_file_path(self, log_type: str) -> Path:
        """Get log file path for specific log type"""
        return self.base_dir / f"{log_type}.log"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary"""
        return {
            "base_dir": str(self.base_dir),
            "console_level": self.console_level,
            "file_level": self.file_level,
            "error_level": self.error_level,
            "max_file_size": self.max_file_size,
            "backup_count": self.backup_count,
            "enable_performance_logging": self.enable_performance_logging,
            "enable_api_logging": self.enable_api_logging,
            "enable_database_logging": self.enable_database_logging,
            "enable_json_logging": self.enable_json_logging,
            "enable_colors": self.enable_colors,
        }


# Global configuration instance
logger_config = LoggerConfig()
