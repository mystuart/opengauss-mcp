"""
GaussDB compatibility module for PostgreSQL MCP.

This module provides GaussDB-specific adapters and utilities to enable
PostgreSQL MCP functionality to work with GaussDB databases.
"""

from .config import DatabaseType
from .config import GaussDbCompatibilityConfig
from .config import QueryAdaptationRule
from .config import SystemViewMapping
from .config_loader import ConfigLoader
from .error_handler import GaussDbErrorHandler
from .health_adapters import GaussDbBufferHealthCalc
from .health_adapters import GaussDbConnectionHealthCalc
from .health_adapters import GaussDbConstraintHealthCalc
from .health_adapters import GaussDbIndexHealthCalc
from .health_adapters import GaussDbReplicationCalc
from .health_adapters import GaussDbSequenceHealthCalc
from .health_adapters import GaussDbVacuumHealthCalc
from .index_tuning_adapters import GaussDbDatabaseTuningAdvisor
from .index_tuning_adapters import GaussDbLLMOptimizerTool
from .index_tuning_base_adapter import GaussDbIndexCostModel
from .index_tuning_base_adapter import GaussDbIndexTuningMixin
from .sql_driver_adapter import GaussDbSqlDriver

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
