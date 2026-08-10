"""
Logger Usage Examples for AI Assistant Service
"""
import asyncio
import time
from .core import (
    get_logger, debug, info, warning, error, critical,
    log_performance, log_api_request,
    log_database_operation, log_exception
)
from .decorators import (
    log_execution_time, log_database_operation_time,
    log_api_endpoint, log_operation_context, log_database_context
)


# Example 1: Basic logging
def basic_logging_example():
    """Example of basic logging usage"""
    logger = get_logger("example")
    
    logger.debug("This is a debug message")
    logger.info("This is an info message")
    logger.warning("This is a warning message")
    logger.error("This is an error message")
    logger.critical("This is a critical message")
    
    # Using convenience functions
    debug("Debug message with convenience function")
    info("Info message with convenience function")
    warning("Warning message with convenience function")
    error("Error message with convenience function")
    critical("Critical message with convenience function")


# Example 2: Logging with extra fields
def logging_with_extra_fields():
    """Example of logging with extra fields"""
    logger = get_logger("example")
    
    # Log with extra context
    logger.info("User login successful", user_id="12345", ip_address="192.168.1.1")
    logger.warning("High memory usage detected", memory_usage="85%", threshold="80%")
    logger.error("Database connection failed", database="mongodb", retry_count=3)


# Example 3: Performance logging
def performance_logging_example():
    """Example of performance logging"""
    start_time = time.time()
    
    # Simulate some work
    time.sleep(0.1)
    
    duration = time.time() - start_time
    log_performance("example_operation", duration, 
                   records_processed=100, memory_used="50MB")


# Example 4: API request logging
def api_logging_example():
    """Example of API request logging"""
    log_api_request(
        method="POST",
        path="/api/v1/faces/register",
        status_code=201,
        duration=0.5,
        user_id="12345",
        face_id="face_67890"
    )



# Example 6: Database operation logging
def database_logging_example():
    """Example of database operation logging"""
    log_database_operation(
        operation="insert",
        collection="faces",
        duration=0.02,
        records_count=1
    )


# Example 7: Exception logging
def exception_logging_example():
    """Example of exception logging"""
    try:
        # Simulate an error
        raise ValueError("Something went wrong!")
    except Exception as e:
        log_exception("Failed to process face image", e, 
                     image_path="/path/to/image.jpg", user_id="12345")


# Example 8: Using decorators
@log_execution_time("face_encoding_operation")
def face_encoding_example():
    """Example of using execution time decorator"""
    time.sleep(0.1)  # Simulate work
    return "encoded_face_vector"


@log_database_operation_time("faces", "insert_face")
def insert_face_example():
    """Example of using database operation decorator"""
    time.sleep(0.05)  # Simulate database operation
    return {"face_id": "face_12345"}


@log_api_endpoint("POST", "/api/v1/faces/register")
def register_face_endpoint_example():
    """Example of using API endpoint decorator"""
    time.sleep(0.2)  # Simulate API processing
    return {"status": "success", "face_id": "face_12345"}


# Example 9: Using context managers
def context_manager_example():
    """Example of using logging context managers"""
    with log_operation_context("face_detection", image_path="/path/to/image.jpg"):
        time.sleep(0.1)  # Simulate face detection
        print("Face detection completed")
    
    with log_database_context("faces", "find_by_person_id", person_id="person_123"):
        time.sleep(0.05)  # Simulate database query
        print("Database query completed")


# Example 10: Async logging
async def async_logging_example():
    """Example of async logging"""
    logger = get_logger("async_example")
    
    logger.info("Starting async operation")
    
    # Simulate async work
    await asyncio.sleep(0.1)
    
    logger.info("Async operation completed")


# Example 11: Module-specific logger
def module_specific_logger_example():
    """Example of using module-specific logger"""
    # Get logger for specific module
    face_detection_logger = get_logger("face_detection")
    face_encoding_logger = get_logger("face_encoding")
    
    face_detection_logger.info("Starting face detection")
    face_encoding_logger.info("Starting face encoding")


# Example 12: Error handling with logging
def error_handling_example():
    """Example of error handling with logging"""
    logger = get_logger("error_handling")
    
    try:
        # Simulate some operation that might fail
        result = 1 / 0
    except ZeroDivisionError as e:
        logger.error("Division by zero error occurred", 
                    operation="calculate_ratio", 
                    numerator=1, 
                    denominator=0)
        log_exception("Mathematical operation failed", e)
    except Exception as e:
        logger.critical("Unexpected error occurred", 
                       operation="calculate_ratio",
                       error_type=type(e).__name__)
        log_exception("Unexpected error in calculation", e)


if __name__ == "__main__":
    """Run all examples"""
    print("Running logger examples...")
    
    # Basic examples
    basic_logging_example()
    logging_with_extra_fields()
    performance_logging_example()
    api_logging_example()
    database_logging_example()
    exception_logging_example()
    
    # Decorator examples
    face_encoding_example()
    insert_face_example()
    register_face_endpoint_example()
    
    # Context manager examples
    context_manager_example()
    
    # Module-specific examples
    module_specific_logger_example()
    
    # Error handling examples
    error_handling_example()
    
    # Async example
    asyncio.run(async_logging_example())
    
    print("All examples completed!")
