"""
GaussDB compatibility module for Postgres MCP Pro.

This module provides compatibility layers and adapters to support
GaussDB database alongside PostgreSQL.
"""

from .config import GaussDbCompatibilityConfig, SystemViewMapping, QueryAdaptationRule, DatabaseType
from .config_loader import ConfigLoader, ConfigValidationError
from .sql_driver_adapter import GaussDbSqlDriver, QueryAdaptationCache
from .error_handler import GaussDbErrorHandler, ErrorCategory

__all__ = [
    "GaussDbCompatibilityConfig",
    "SystemViewMapping", 
    "QueryAdaptationRule",
    "DatabaseType",
    "ConfigLoader",
    "ConfigValidationError",
    "GaussDbSqlDriver",
    "QueryAdaptationCache",
    "GaussDbErrorHandler",
    "ErrorCategory"
]