import logging
import traceback
from typing import Any
from typing import Union
from functools import wraps

logger = logging.getLogger(__name__)


class DatabaseError(Exception):
    """Base class for database-related errors."""
    pass


class ConnectionError(DatabaseError):
    """Error raised when database connection fails."""
    pass


class QueryError(DatabaseError):
    """Error raised when a database query fails."""
    pass


class FeatureNotSupportedError(DatabaseError):
    """Error raised when a feature is not supported."""
    pass


def handle_database_errors(func):
    """Decorator to handle database errors consistently."""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except ConnectionError as e:
            logger.error(f"Connection error in {func.__name__}: {str(e)}")
            return f"Error: Database connection failed. Details: {str(e)}"
        except QueryError as e:
            logger.error(f"Query error in {func.__name__}: {str(e)}")
            return f"Error: Database query failed. Details: {str(e)}"
        except FeatureNotSupportedError as e:
            logger.error(f"Feature not supported in {func.__name__}: {str(e)}")
            return f"Error: Feature not supported. Details: {str(e)}"
        except Exception as e:
            logger.error(f"Unexpected error in {func.__name__}: {str(e)}")
            logger.debug(f"Traceback: {traceback.format_exc()}")
            return f"Error: An unexpected error occurred. Details: {str(e)}"
    return wrapper


def log_function_call(func):
    """Decorator to log function calls with parameters."""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        # Log function name and parameters (excluding sensitive data)
        logger.debug(f"Calling {func.__name__} with args: {args[:2]}..., kwargs: {list(kwargs.keys())}")
        try:
            result = await func(*args, **kwargs)
            logger.debug(f"Function {func.__name__} completed successfully")
            return result
        except Exception as e:
            logger.error(f"Function {func.__name__} failed with error: {str(e)}")
            raise
    return wrapper


def safe_execute_query(sql_driver, query: str, params: list[Any] | None = None) -> Union[Any, str]:
    """Safely execute a database query with error handling.

    Args:
        sql_driver: SQL driver to use for the query
        query: SQL query to execute
        params: Optional parameters for the query

    Returns:
        Query result or error message
    """
    try:
        if params:
            return sql_driver.execute_param_query(query, params)
        else:
            return sql_driver.execute_query(query)
    except Exception as e:
        logger.error(f"Error executing query: {str(e)}")
        logger.debug(f"Query: {query}")
        if params:
            logger.debug(f"Parameters: {params}")
        return f"Error executing query: {str(e)}"


def setup_logging(level: str = "INFO", format_string: str | None = None) -> None:
    """Set up logging configuration.

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        format_string: Custom format string for log messages
    """
    if not format_string:
        format_string = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format=format_string,
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    # Set specific logger levels
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("urllib3.connectionpool").setLevel(logging.WARNING)


class ErrorContext:
    """Context manager for handling errors in a specific context."""
    
    def __init__(self, context_name: str, reraise: bool = False):
        self.context_name = context_name
        self.reraise = reraise
        self.error = None
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.error = exc_val
            logger.error(f"Error in context '{self.context_name}': {str(exc_val)}")
            logger.debug(f"Traceback: {traceback.format_exception(exc_type, exc_val, exc_tb)}")
            
            if self.reraise:
                raise
        return True  # Suppress exception if not re-raising


def format_error_message(error: Exception, context: str | None = None) -> str:
    """Format an error message with context information.

    Args:
        error: Exception that occurred
        context: Optional context information

    Returns:
        Formatted error message
    """
    message = f"Error: {str(error)}"
    if context:
        message = f"Error in {context}: {str(error)}"
    return message