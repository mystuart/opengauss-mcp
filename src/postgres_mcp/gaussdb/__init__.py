"""
GaussDB compatibility module for PostgreSQL MCP.

This module provides GaussDB-specific adapters and utilities to enable
PostgreSQL MCP functionality to work with GaussDB databases.
"""

from .sql_driver_adapter import GaussDbSqlDriver
from .config import GaussDbCompatibilityConfig, DatabaseType, SystemViewMapping, QueryAdaptationRule
from .config_loader import ConfigLoader
from .error_handler import GaussDbErrorHandler
from .health_adapters import (
    GaussDbIndexHealthCalc,
    GaussDbConnectionHealthCalc,
    GaussDbBufferHealthCalc,
    GaussDbVacuumHealthCalc,
    GaussDbSequenceHealthCalc,
    GaussDbReplicationCalc,
    GaussDbConstraintHealthCalc,
)
from .index_tuning_adapters import (
    GaussDbDatabaseTuningAdvisor,
    GaussDbLLMOptimizerTool,
)
from .index_tuning_base_adapter import (
    GaussDbIndexTuningMixin,
    GaussDbIndexCostModel,
)

__all__ = [
    # Core adapter
    "GaussDbSqlDriver",
    
    # Configuration
    "GaussDbCompatibilityConfig",
    "DatabaseType",
    "SystemViewMapping", 
    "QueryAdaptationRule",
    "ConfigLoader",
    
    # Error handling
    "GaussDbErrorHandler",
    
    # Health check adapters
    "GaussDbIndexHealthCalc",
    "GaussDbConnectionHealthCalc", 
    "GaussDbBufferHealthCalc",
    "GaussDbVacuumHealthCalc",
    "GaussDbSequenceHealthCalc",
    "GaussDbReplicationCalc",
    "GaussDbConstraintHealthCalc",
    
    # Index tuning adapters
    "GaussDbDatabaseTuningAdvisor",
    "GaussDbLLMOptimizerTool",
    "GaussDbIndexTuningMixin",
    "GaussDbIndexCostModel",
]