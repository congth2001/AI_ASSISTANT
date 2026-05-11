"""
Logging Decorators and Context Managers for AI Assistant Service
"""
import time
import functools
from typing import Callable, Any, Optional
from contextlib import contextmanager
from .core import get_logger, log_performance, log_database_operation


def log_execution_time(operation_name: str = None, log_level: str = "info"):
    """
    Decorator to log execution time of functions
    
    Args:
        operation_name: Custom name for the operation (defaults to function name)
        log_level: Log level (debug, info, warning, error, critical)
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            start_time = time.time()
            operation = operation_name or f"{func.__module__}.{func.__name__}"
            logger = get_logger(func.__module__)
            
            try:
                logger.info(f"Starting {operation}")
                result = await func(*args, **kwargs)
                duration = time.time() - start_time
                
                log_performance(operation, duration)
                logger.info(f"Completed {operation} in {duration:.3f}s")
                
                return result
            except Exception as e:
                duration = time.time() - start_time
                logger.error(f"Failed {operation} after {duration:.3f}s: {str(e)}")
                raise
        
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            start_time = time.time()
            operation = operation_name or f"{func.__module__}.{func.__name__}"
            logger = get_logger(func.__module__)
            
            try:
                logger.info(f"Starting {operation}")
                result = func(*args, **kwargs)
                duration = time.time() - start_time
                
                log_performance(operation, duration)
                logger.info(f"Completed {operation} in {duration:.3f}s")
                
                return result
            except Exception as e:
                duration = time.time() - start_time
                logger.error(f"Failed {operation} after {duration:.3f}s: {str(e)}")
                raise
        
        # Return appropriate wrapper based on function type
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator


def log_database_operation_time(collection: str, operation: str = None):
    """
    Decorator to log database operations with timing
    
    Args:
        collection: Database collection name
        operation: Custom operation name (defaults to function name)
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            start_time = time.time()
            op_name = operation or func.__name__
            logger = get_logger(func.__module__)
            
            try:
                logger.debug(f"Starting DB {op_name} on {collection}")
                result = await func(*args, **kwargs)
                duration = time.time() - start_time
                
                log_database_operation(op_name, collection, duration)
                logger.debug(f"Completed DB {op_name} on {collection} in {duration:.3f}s")
                
                return result
            except Exception as e:
                duration = time.time() - start_time
                logger.error(f"Failed DB {op_name} on {collection} after {duration:.3f}s: {str(e)}")
                raise
        
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            start_time = time.time()
            op_name = operation or func.__name__
            logger = get_logger(func.__module__)
            
            try:
                logger.debug(f"Starting DB {op_name} on {collection}")
                result = func(*args, **kwargs)
                duration = time.time() - start_time
                
                log_database_operation(op_name, collection, duration)
                logger.debug(f"Completed DB {op_name} on {collection} in {duration:.3f}s")
                
                return result
            except Exception as e:
                duration = time.time() - start_time
                logger.error(f"Failed DB {op_name} on {collection} after {duration:.3f}s: {str(e)}")
                raise
        
        # Return appropriate wrapper based on function type
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator


def log_api_endpoint(method: str, path: str):
    """
    Decorator to log API endpoint calls
    
    Args:
        method: HTTP method (GET, POST, etc.)
        path: API path
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            start_time = time.time()
            logger = get_logger(func.__module__)
            
            # Extract user_id from kwargs if available
            user_id = kwargs.get('user_id') or (args[0].user_id if hasattr(args[0], 'user_id') else None)
            
            try:
                logger.info(f"API {method} {path} - Request started", user_id=user_id)
                result = await func(*args, **kwargs)
                duration = time.time() - start_time
                
                # Assume 200 status for successful execution
                status_code = 200
                logger.log_api_request(method, path, status_code, duration, user_id)
                logger.info(f"API {method} {path} - Request completed in {duration:.3f}s", user_id=user_id)
                
                return result
            except Exception as e:
                duration = time.time() - start_time
                status_code = 500
                logger.log_api_request(method, path, status_code, duration, user_id, error=str(e))
                logger.error(f"API {method} {path} - Request failed after {duration:.3f}s: {str(e)}", user_id=user_id)
                raise
        
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            start_time = time.time()
            logger = get_logger(func.__module__)
            
            # Extract user_id from kwargs if available
            user_id = kwargs.get('user_id') or (args[0].user_id if hasattr(args[0], 'user_id') else None)
            
            try:
                logger.info(f"API {method} {path} - Request started", user_id=user_id)
                result = func(*args, **kwargs)
                duration = time.time() - start_time
                
                # Assume 200 status for successful execution
                status_code = 200
                logger.log_api_request(method, path, status_code, duration, user_id)
                logger.info(f"API {method} {path} - Request completed in {duration:.3f}s", user_id=user_id)
                
                return result
            except Exception as e:
                duration = time.time() - start_time
                status_code = 500
                logger.log_api_request(method, path, status_code, duration, user_id, error=str(e))
                logger.error(f"API {method} {path} - Request failed after {duration:.3f}s: {str(e)}", user_id=user_id)
                raise
        
        # Return appropriate wrapper based on function type
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator


@contextmanager
def log_operation_context(operation_name: str, **context_data):
    """
    Context manager for logging operations with timing
    
    Args:
        operation_name: Name of the operation
        **context_data: Additional context data to log
    """
    logger = get_logger()
    start_time = time.time()
    
    logger.info(f"Starting {operation_name}", **context_data)
    
    try:
        yield
        duration = time.time() - start_time
        log_performance(operation_name, duration, **context_data)
        logger.info(f"Completed {operation_name} in {duration:.3f}s", **context_data)
    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"Failed {operation_name} after {duration:.3f}s: {str(e)}", **context_data)
        raise


@contextmanager
def log_database_context(collection: str, operation: str, **context_data):
    """
    Context manager for logging database operations
    
    Args:
        collection: Database collection name
        operation: Operation name
        **context_data: Additional context data to log
    """
    logger = get_logger()
    start_time = time.time()
    
    logger.debug(f"Starting DB {operation} on {collection}", **context_data)
    
    try:
        yield
        duration = time.time() - start_time
        log_database_operation(operation, collection, duration, **context_data)
        logger.debug(f"Completed DB {operation} on {collection} in {duration:.3f}s", **context_data)
    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"Failed DB {operation} on {collection} after {duration:.3f}s: {str(e)}", **context_data)
        raise


# Import asyncio for coroutine detection
import asyncio
