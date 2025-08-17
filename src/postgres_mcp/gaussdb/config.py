"""
GaussDB compatibility configuration data models.

This module defines the data structures for managing GaussDB compatibility
configurations, including system view mappings and query adaptation rules.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from enum import Enum


class DatabaseType(str, Enum):
    """Database type enumeration."""
    POSTGRESQL = "postgresql"
    GAUSSDB = "gaussdb"


@dataclass
class SystemViewMapping:
    """
    Mapping configuration for PostgreSQL system views to GaussDB equivalents.
    
    This class defines how PostgreSQL system views should be mapped to their
    GaussDB counterparts, handling cases where view names or schemas differ.
    """
    postgresql_view: str
    gaussdb_view: str
    schema_mapping: Optional[Dict[str, str]] = None
    column_mappings: Optional[Dict[str, str]] = None
    requires_adaptation: bool = False
    fallback_query: Optional[str] = None
    
    def __post_init__(self):
        """Initialize default values after dataclass creation."""
        if self.schema_mapping is None:
            self.schema_mapping = {}
        if self.column_mappings is None:
            self.column_mappings = {}


@dataclass 
class QueryAdaptationRule:
    """
    Query adaptation rule for converting PostgreSQL queries to GaussDB format.
    
    This class defines rules for transforming PostgreSQL-specific SQL syntax
    to GaussDB-compatible equivalents.
    """
    name: str
    description: str
    pattern: str  # Regex pattern to match
    replacement: str  # Replacement string or template
    conditions: Optional[Dict[str, Any]] = None
    priority: int = 0  # Higher priority rules are applied first
    
    def __post_init__(self):
        """Initialize default values after dataclass creation."""
        if self.conditions is None:
            self.conditions = {}


@dataclass
class GaussDbCompatibilityConfig:
    """
    Main configuration class for GaussDB compatibility settings.
    
    This class contains all the configuration needed to adapt PostgreSQL
    functionality to work with GaussDB, including version-specific settings,
    system view mappings, and query adaptation rules.
    """
    version: str
    major_version: str = ""
    minor_version: str = ""
    
    # Feature support flags
    supports_hypopg: bool = False
    supports_pg_stat_statements: bool = True
    supports_explain_analyze: bool = True
    supports_vacuum_analyze: bool = True
    supports_replication_stats: bool = True
    
    # System view mappings
    system_views: Dict[str, SystemViewMapping] = field(default_factory=dict)
    
    # Query adaptation rules
    query_adaptations: List[QueryAdaptationRule] = field(default_factory=list)
    
    # Error message mappings
    error_mappings: Dict[str, str] = field(default_factory=dict)
    
    # Performance and connection settings
    connection_settings: Dict[str, Any] = field(default_factory=dict)
    
    # Additional metadata
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Initialize computed fields after dataclass creation."""
        if not self.major_version or not self.minor_version:
            self._parse_version()
        
        # Initialize default system view mappings if none provided
        if not self.system_views:
            self._init_default_system_views()
            
        # Initialize default query adaptations if none provided  
        if not self.query_adaptations:
            self._init_default_query_adaptations()
    
    def _parse_version(self):
        """Parse version string into major and minor components."""
        try:
            parts = self.version.split('.')
            if len(parts) >= 2:
                self.major_version = parts[0]
                self.minor_version = parts[1]
            else:
                self.major_version = self.version
                self.minor_version = "0"
        except (ValueError, AttributeError):
            self.major_version = "unknown"
            self.minor_version = "0"
    
    def _init_default_system_views(self):
        """Initialize default system view mappings for GaussDB."""
        default_mappings = {
            # Index statistics views
            "pg_stat_user_indexes": SystemViewMapping(
                postgresql_view="pg_stat_user_indexes",
                gaussdb_view="pg_stat_user_indexes",
                requires_adaptation=False
            ),
            "pg_stat_all_indexes": SystemViewMapping(
                postgresql_view="pg_stat_all_indexes", 
                gaussdb_view="pg_stat_all_indexes",
                requires_adaptation=False
            ),
            
            # Table statistics views
            "pg_stat_user_tables": SystemViewMapping(
                postgresql_view="pg_stat_user_tables",
                gaussdb_view="pg_stat_user_tables", 
                requires_adaptation=False
            ),
            "pg_stat_all_tables": SystemViewMapping(
                postgresql_view="pg_stat_all_tables",
                gaussdb_view="pg_stat_all_tables",
                requires_adaptation=False
            ),
            
            # Database statistics
            "pg_stat_database": SystemViewMapping(
                postgresql_view="pg_stat_database",
                gaussdb_view="pg_stat_database",
                requires_adaptation=False
            ),
            
            # Activity and connections
            "pg_stat_activity": SystemViewMapping(
                postgresql_view="pg_stat_activity",
                gaussdb_view="pg_stat_activity",
                requires_adaptation=True,  # May have GaussDB-specific columns
                column_mappings={
                    "state": "state",
                    "query": "query", 
                    "application_name": "application_name"
                }
            ),
            
            # Buffer and cache statistics
            "pg_stat_bgwriter": SystemViewMapping(
                postgresql_view="pg_stat_bgwriter",
                gaussdb_view="pg_stat_bgwriter",
                requires_adaptation=False
            ),
            
            # Replication statistics
            "pg_stat_replication": SystemViewMapping(
                postgresql_view="pg_stat_replication",
                gaussdb_view="pg_stat_replication", 
                requires_adaptation=True
            ),
            
            # Query statistics (pg_stat_statements equivalent)
            "pg_stat_statements": SystemViewMapping(
                postgresql_view="pg_stat_statements",
                gaussdb_view="pg_stat_statements",
                requires_adaptation=True,
                fallback_query="SELECT 'pg_stat_statements not available' as message"
            )
        }
        
        self.system_views.update(default_mappings)
    
    def _init_default_query_adaptations(self):
        """Initialize default query adaptation rules."""
        default_rules = [
            QueryAdaptationRule(
                name="version_function",
                description="Adapt version() function call",
                pattern=r"SELECT\s+version\(\)",
                replacement="SELECT version()",
                priority=1
            ),
            QueryAdaptationRule(
                name="current_database",
                description="Adapt current_database() function",
                pattern=r"SELECT\s+current_database\(\)",
                replacement="SELECT current_database()",
                priority=1
            ),
            QueryAdaptationRule(
                name="pg_size_pretty",
                description="Adapt pg_size_pretty function",
                pattern=r"pg_size_pretty\(",
                replacement="pg_size_pretty(",
                priority=2
            ),
            QueryAdaptationRule(
                name="information_schema",
                description="Handle information_schema queries",
                pattern=r"information_schema\.",
                replacement="information_schema.",
                priority=3
            )
        ]
        
        self.query_adaptations.extend(default_rules)
        # Sort by priority (higher first)
        self.query_adaptations.sort(key=lambda x: x.priority, reverse=True)
    
    def get_system_view_mapping(self, postgresql_view: str) -> Optional[SystemViewMapping]:
        """
        Get the system view mapping for a PostgreSQL view.
        
        Args:
            postgresql_view: The PostgreSQL system view name
            
        Returns:
            SystemViewMapping if found, None otherwise
        """
        return self.system_views.get(postgresql_view)
    
    def get_adapted_view_name(self, postgresql_view: str) -> str:
        """
        Get the adapted view name for GaussDB.
        
        Args:
            postgresql_view: The PostgreSQL system view name
            
        Returns:
            The GaussDB equivalent view name, or original if no mapping exists
        """
        mapping = self.get_system_view_mapping(postgresql_view)
        return mapping.gaussdb_view if mapping else postgresql_view
    
    def requires_view_adaptation(self, postgresql_view: str) -> bool:
        """
        Check if a view requires adaptation beyond simple name mapping.
        
        Args:
            postgresql_view: The PostgreSQL system view name
            
        Returns:
            True if the view requires query adaptation, False otherwise
        """
        mapping = self.get_system_view_mapping(postgresql_view)
        return mapping.requires_adaptation if mapping else False
    
    def get_query_adaptations_by_priority(self) -> List[QueryAdaptationRule]:
        """
        Get query adaptation rules sorted by priority.
        
        Returns:
            List of QueryAdaptationRule sorted by priority (highest first)
        """
        return sorted(self.query_adaptations, key=lambda x: x.priority, reverse=True)
    
    def is_feature_supported(self, feature: str) -> bool:
        """
        Check if a specific feature is supported in this GaussDB version.
        
        Args:
            feature: Feature name to check
            
        Returns:
            True if feature is supported, False otherwise
        """
        feature_map = {
            "hypopg": self.supports_hypopg,
            "pg_stat_statements": self.supports_pg_stat_statements,
            "explain_analyze": self.supports_explain_analyze,
            "vacuum_analyze": self.supports_vacuum_analyze,
            "replication_stats": self.supports_replication_stats
        }
        return feature_map.get(feature, False)
    
    def get_error_message(self, error_key: str, default: str = "") -> str:
        """
        Get a user-friendly error message for a specific error.
        
        Args:
            error_key: The error key to look up
            default: Default message if key not found
            
        Returns:
            User-friendly error message
        """
        return self.error_mappings.get(error_key, default)
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert configuration to dictionary format.
        
        Returns:
            Dictionary representation of the configuration
        """
        return {
            "version": self.version,
            "major_version": self.major_version,
            "minor_version": self.minor_version,
            "supports_hypopg": self.supports_hypopg,
            "supports_pg_stat_statements": self.supports_pg_stat_statements,
            "supports_explain_analyze": self.supports_explain_analyze,
            "supports_vacuum_analyze": self.supports_vacuum_analyze,
            "supports_replication_stats": self.supports_replication_stats,
            "system_views": {k: {
                "postgresql_view": v.postgresql_view,
                "gaussdb_view": v.gaussdb_view,
                "schema_mapping": v.schema_mapping,
                "column_mappings": v.column_mappings,
                "requires_adaptation": v.requires_adaptation,
                "fallback_query": v.fallback_query
            } for k, v in self.system_views.items()},
            "query_adaptations": [{
                "name": rule.name,
                "description": rule.description,
                "pattern": rule.pattern,
                "replacement": rule.replacement,
                "conditions": rule.conditions,
                "priority": rule.priority
            } for rule in self.query_adaptations],
            "error_mappings": self.error_mappings,
            "connection_settings": self.connection_settings,
            "metadata": self.metadata
        }