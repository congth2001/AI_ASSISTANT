"""
Advanced Logger Configuration for AI Assistant Service
"""
import logging
import logging.handlers
import os
import sys
from datetime import datetime
from typing import Optional, Dict, Any
from pathlib import Path
import json
import traceback
from .config import logger_config


class ColoredFormatter(logging.Formatter):
    """Custom formatter with colors for console output"""
    
    # Color codes
    COLORS = {
        'DEBUG': '\033[36m',      # Cyan
        'INFO': '\033[32m',       # Green
        'WARNING': '\033[33m',    # Yellow
        'ERROR': '\033[31m',      # Red
        'CRITICAL': '\033[35m',   # Magenta
        'RESET': '\033[0m'        # Reset
    }
    
    def format(self, record):
        # Add color to level name
        if hasattr(record, 'levelname'):
            color = self.COLORS.get(record.levelname, self.COLORS['RESET'])
            record.levelname = f"{color}{record.levelname}{self.COLORS['RESET']}"
        
        return super().format(record)


class JSONFormatter(logging.Formatter):
    """JSON formatter for structured logging"""
    
    def format(self, record):
        log_entry = {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno,
            'thread': record.thread,
            'process': record.process
        }
        
        # Add exception info if present
        if record.exc_info:
            log_entry['exception'] = {
                'type': record.exc_info[0].__name__,
                'message': str(record.exc_info[1]),
                'traceback': traceback.format_exception(*record.exc_info)
            }
        
        # Add extra fields
        if hasattr(record, 'extra_fields'):
            log_entry.update(record.extra_fields)
        
        return json.dumps(log_entry, ensure_ascii=False)


class ServiceLogger:
    """Main logger class for the AI Assistant Service"""
    
    _instance = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not self._initialized:
            self._setup_logger()
            ServiceLogger._initialized = True
    
    def _setup_logger(self):
        """Setup the main logger configuration"""
        # Use config for logs directory
        self.logs_dir = logger_config.base_dir
        
        # Main logger
        self.logger = logging.getLogger("ai_assistant_service")
        self.logger.setLevel(getattr(logging, logger_config.file_level.upper()))
        
        # Clear existing handlers
        self.logger.handlers.clear()
        
        # Console handler with colors
        self._setup_console_handler()
        
        # File handlers
        self._setup_file_handlers()
        
        # Error handler
        self._setup_error_handler()
        
        # Performance handler
        if logger_config.enable_performance_logging:
            self._setup_performance_handler()
    
    def _setup_console_handler(self):
        """Setup console handler with colored output"""
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(getattr(logging, logger_config.console_level.upper()))
        
        # Choose formatter based on config
        if logger_config.enable_colors:
            console_formatter = ColoredFormatter(
                logger_config.console_format,
                datefmt=logger_config.date_format
            )
        else:
            console_formatter = logging.Formatter(
                logger_config.console_format,
                datefmt=logger_config.date_format
            )
        
        console_handler.setFormatter(console_formatter)
        self.logger.addHandler(console_handler)
    
    def _setup_file_handlers(self):
        """Setup file handlers for different log levels"""
        # General log file
        general_handler = logging.handlers.RotatingFileHandler(
            self.logs_dir / "ai_assistant.log",
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5
        )
        general_handler.setLevel(logging.DEBUG)
        
        general_formatter = logging.Formatter(
            '%(asctime)s | %(levelname)-8s | %(name)-20s | %(module)s:%(funcName)s:%(lineno)d | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        general_handler.setFormatter(general_formatter)
        
        self.logger.addHandler(general_handler)
        
        # Error log file
        error_handler = logging.handlers.RotatingFileHandler(
            self.logs_dir / "errors.log",
            maxBytes=5*1024*1024,  # 5MB
            backupCount=3
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(general_formatter)
        
        self.logger.addHandler(error_handler)
    
    def _setup_error_handler(self):
        """Setup dedicated error handler"""
        error_handler = logging.handlers.RotatingFileHandler(
            self.logs_dir / "critical_errors.log",
            maxBytes=2*1024*1024,  # 2MB
            backupCount=2
        )
        error_handler.setLevel(logging.CRITICAL)
        
        error_formatter = logging.Formatter(
            '%(asctime)s | CRITICAL | %(name)-20s | %(module)s:%(funcName)s:%(lineno)d | %(message)s\n%(pathname)s:%(lineno)d\n%(exc_info)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        error_handler.setFormatter(error_formatter)
        
        self.logger.addHandler(error_handler)
    
    def _setup_performance_handler(self):
        """Setup performance monitoring handler"""
        perf_handler = logging.handlers.RotatingFileHandler(
            self.logs_dir / "performance.log",
            maxBytes=5*1024*1024,  # 5MB
            backupCount=3
        )
        perf_handler.setLevel(logging.INFO)
        
        # JSON formatter for performance logs
        json_formatter = JSONFormatter()
        perf_handler.setFormatter(json_formatter)
        
        # Create performance logger
        self.perf_logger = logging.getLogger("ai_assistant_performance")
        self.perf_logger.setLevel(logging.INFO)
        self.perf_logger.addHandler(perf_handler)
        self.perf_logger.propagate = False
    
    def get_logger(self, name: str = None) -> logging.Logger:
        """Get a logger instance"""
        if name:
            return logging.getLogger(f"ai_assistant_service.{name}")
        return self.logger
    
    def debug(self, message: str, **kwargs):
        """Log debug message"""
        self._log_with_extra(logging.DEBUG, message, **kwargs)
    
    def info(self, message: str, **kwargs):
        """Log info message"""
        self._log_with_extra(logging.INFO, message, **kwargs)
    
    def warning(self, message: str, **kwargs):
        """Log warning message"""
        self._log_with_extra(logging.WARNING, message, **kwargs)
    
    def error(self, message: str, **kwargs):
        """Log error message"""
        self._log_with_extra(logging.ERROR, message, **kwargs)
    
    def critical(self, message: str, **kwargs):
        """Log critical message"""
        self._log_with_extra(logging.CRITICAL, message, **kwargs)
    
    def _log_with_extra(self, level: int, message: str, **kwargs):
        """Log message with extra fields"""
        extra_fields = {k: v for k, v in kwargs.items() if k not in ['exc_info', 'stack_info']}
        
        if extra_fields:
            # Create a new record with extra fields
            record = self.logger.makeRecord(
                self.logger.name, level, "", 0, message, (), None
            )
            record.extra_fields = extra_fields
            self.logger.handle(record)
        else:
            self.logger.log(level, message)
    
    def log_performance(self, operation: str, duration: float, **kwargs):
        """Log performance metrics"""
        extra_fields = {
            'operation': operation,
            'duration_ms': duration * 1000,
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            **kwargs
        }
        
        record = self.perf_logger.makeRecord(
            self.perf_logger.name, logging.INFO, "", 0, 
            f"Performance: {operation} took {duration:.3f}s", (), None
        )
        record.extra_fields = extra_fields
        self.perf_logger.handle(record)
    
    def log_api_request(self, method: str, path: str, status_code: int, 
                       duration: float, user_id: str = None, **kwargs):
        """Log API request details"""
        extra_fields = {
            'type': 'api_request',
            'method': method,
            'path': path,
            'status_code': status_code,
            'duration_ms': duration * 1000,
            'user_id': user_id,
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            **kwargs
        }
        
        record = self.logger.makeRecord(
            self.logger.name, logging.INFO, "", 0,
            f"API {method} {path} -> {status_code} ({duration:.3f}s)", (), None
        )
    
    def log_database_operation(self, operation: str, collection: str, 
                              duration: float = None, **kwargs):
        """Log database operations"""
        extra_fields = {
            'type': 'database_operation',
            'operation': operation,
            'collection': collection,
            'duration_ms': duration * 1000 if duration else None,
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            **kwargs
        }
        
        message = f"DB {operation} on {collection}"
        if duration:
            message += f" ({duration:.3f}s)"
        
        record = self.logger.makeRecord(
            self.logger.name, logging.DEBUG, "", 0, message, (), None
        )
        record.extra_fields = extra_fields
        self.logger.handle(record)
    
    def log_exception(self, message: str, exception: Exception, **kwargs):
        """Log exception with full traceback"""
        extra_fields = {
            'type': 'exception',
            'exception_type': type(exception).__name__,
            'exception_message': str(exception),
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            **kwargs
        }
        
        record = self.logger.makeRecord(
            self.logger.name, logging.ERROR, "", 0, message, (), 
            (type(exception), exception, exception.__traceback__)
        )
        record.extra_fields = extra_fields
        self.logger.handle(record)


# Global logger instance
logger = ServiceLogger()

# Convenience functions
def get_logger(name: str = None) -> logging.Logger:
    """Get a logger instance"""
    return logger.get_logger(name)

def debug(message: str, **kwargs):
    """Log debug message"""
    logger.debug(message, **kwargs)

def info(message: str, **kwargs):
    """Log info message"""
    logger.info(message, **kwargs)

def warning(message: str, **kwargs):
    """Log warning message"""
    logger.warning(message, **kwargs)

def error(message: str, **kwargs):
    """Log error message"""
    logger.error(message, **kwargs)

def critical(message: str, **kwargs):
    """Log critical message"""
    logger.critical(message, **kwargs)

def log_performance(operation: str, duration: float, **kwargs):
    """Log performance metrics"""
    logger.log_performance(operation, duration, **kwargs)

def log_api_request(method: str, path: str, status_code: int, 
                   duration: float, user_id: str = None, **kwargs):
    """Log API request details"""
    logger.log_api_request(method, path, status_code, duration, user_id, **kwargs)

def log_database_operation(operation: str, collection: str, 
                          duration: float = None, **kwargs):
    """Log database operations"""
    logger.log_database_operation(operation, collection, duration, **kwargs)

def log_exception(message: str, exception: Exception, **kwargs):
    """Log exception with full traceback"""
    logger.log_exception(message, exception, **kwargs)
