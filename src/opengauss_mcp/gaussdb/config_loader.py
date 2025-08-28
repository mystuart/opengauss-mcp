"""
Configuration file loader for GaussDB compatibility settings.

This module provides functionality to load and validate GaussDB compatibility
configurations from YAML files, with support for version-specific settings.
"""

import logging
from pathlib import Path
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

import yaml

from .config import GaussDbCompatibilityConfig
from .config import QueryAdaptationRule
from .config import SystemViewMapping

logger = logging.getLogger(__name__)


class ConfigValidationError(Exception):
    """Raised when configuration validation fails."""
    pass


class ConfigLoader:
    """
    Configuration loader for GaussDB compatibility settings.
    
    This class handles loading, parsing, and validating YAML configuration
    files that define GaussDB compatibility settings for different versions.
    """

    DEFAULT_CONFIG_FILENAME = "gaussdb_compatibility.yaml"

    def __init__(self, config_dir: Optional[str] = None):
        """
        Initialize the configuration loader.
        
        Args:
            config_dir: Directory containing configuration files.
                       If None, uses default locations.
        """
        self.config_dir = self._determine_config_dir(config_dir)
        self._config_cache: Dict[str, GaussDbCompatibilityConfig] = {}

    def _determine_config_dir(self, config_dir: Optional[str]) -> Path:
        """
        Determine the configuration directory to use.
        
        Args:
            config_dir: User-specified config directory
            
        Returns:
            Path to configuration directory
        """
        if config_dir:
            return Path(config_dir)

        # Try multiple default locations
        possible_dirs = [
            Path.cwd() / "config",
            Path.cwd() / "src" / "opengauss_mcp" / "gaussdb" / "config",
            Path(__file__).parent / "config",
            Path.home() / ".opengauss_mcp" / "config"
        ]

        for dir_path in possible_dirs:
            if dir_path.exists() and dir_path.is_dir():
                return dir_path

        # Default to first option if none exist
        return possible_dirs[0]

    def load_config_for_version(self, version: str) -> GaussDbCompatibilityConfig:
        """
        Load configuration for a specific GaussDB version.
        
        Args:
            version: GaussDB version string (e.g., "8.1.0")
            
        Returns:
            GaussDbCompatibilityConfig for the specified version
            
        Raises:
            ConfigValidationError: If configuration is invalid
            FileNotFoundError: If configuration file is not found
        """
        # Check cache first
        if version in self._config_cache:
            logger.debug(f"Returning cached config for version {version}")
            return self._config_cache[version]

        config_file = self.config_dir / self.DEFAULT_CONFIG_FILENAME

        if not config_file.exists():
            logger.warning(f"Config file not found: {config_file}")
            # Create default configuration
            config = self._create_default_config(version)
            self._config_cache[version] = config
            return config

        try:
            with open(config_file, encoding='utf-8') as f:
                yaml_data = yaml.safe_load(f)

            config = self._parse_config_for_version(yaml_data, version)
            self._validate_config(config)

            # Cache the configuration
            self._config_cache[version] = config

            logger.info(f"Loaded GaussDB config for version {version}")
            return config

        except yaml.YAMLError as e:
            raise ConfigValidationError(f"Invalid YAML in config file: {e}")
        except Exception as e:
            raise ConfigValidationError(f"Error loading config: {e}")

    def _parse_config_for_version(self, yaml_data: Dict[str, Any], version: str) -> GaussDbCompatibilityConfig:
        """
        Parse YAML data and extract configuration for specific version.
        
        Args:
            yaml_data: Parsed YAML data
            version: Target version string
            
        Returns:
            GaussDbCompatibilityConfig for the version
        """
        versions_data = yaml_data.get("versions", {})

        # Try exact version match first
        version_config = versions_data.get(version)

        # If not found, try to find compatible version
        if not version_config:
            version_config = self._find_compatible_version_config(versions_data, version)

        # If still not found, use default
        if not version_config:
            logger.warning(f"No specific config found for version {version}, using default")
            version_config = versions_data.get("default", {})

        # Parse the configuration
        config = GaussDbCompatibilityConfig(version=version)

        # Update basic settings
        config.supports_hypopg = version_config.get("supports_hypopg", False)
        config.supports_pg_stat_statements = version_config.get("supports_pg_stat_statements", True)
        config.supports_explain_analyze = version_config.get("supports_explain_analyze", True)
        config.supports_vacuum_analyze = version_config.get("supports_vacuum_analyze", True)
        config.supports_replication_stats = version_config.get("supports_replication_stats", True)

        # Parse system views
        system_views_data = version_config.get("system_views", {})
        config.system_views = self._parse_system_views(system_views_data)

        # Parse query adaptations
        adaptations_data = version_config.get("query_adaptations", [])
        config.query_adaptations = self._parse_query_adaptations(adaptations_data)

        # Parse error mappings
        config.error_mappings = version_config.get("error_mappings", {})

        # Parse connection settings
        config.connection_settings = version_config.get("connection_settings", {})

        # Parse metadata
        config.metadata = version_config.get("metadata", {})

        return config

    def _find_compatible_version_config(self, versions_data: Dict[str, Any], target_version: str) -> Optional[Dict[str, Any]]:
        """
        Find a compatible version configuration for the target version.
        
        Args:
            versions_data: All version configurations
            target_version: Target version to find config for
            
        Returns:
            Compatible version config or None
        """
        try:
            target_parts = [int(x) for x in target_version.split('.')]
        except ValueError:
            return None

        compatible_versions = []

        for version_key in versions_data.keys():
            if version_key == "default":
                continue

            try:
                version_parts = [int(x) for x in version_key.split('.')]

                # Check if this version is compatible (same major version, equal or lower minor)
                if (len(version_parts) >= 2 and len(target_parts) >= 2 and
                    version_parts[0] == target_parts[0] and
                    version_parts[1] <= target_parts[1]):
                    compatible_versions.append((version_key, version_parts))

            except ValueError:
                continue

        if not compatible_versions:
            return None

        # Sort by version (highest compatible version first)
        compatible_versions.sort(key=lambda x: x[1], reverse=True)
        best_version = compatible_versions[0][0]

        logger.info(f"Using compatible config version {best_version} for {target_version}")
        return versions_data[best_version]

    def _parse_system_views(self, system_views_data: Dict[str, Any]) -> Dict[str, SystemViewMapping]:
        """
        Parse system view mappings from configuration data.
        
        Args:
            system_views_data: System views configuration data
            
        Returns:
            Dictionary of SystemViewMapping objects
        """
        system_views = {}

        for pg_view, mapping_data in system_views_data.items():
            if isinstance(mapping_data, str):
                # Simple string mapping
                mapping = SystemViewMapping(
                    postgresql_view=pg_view,
                    gaussdb_view=mapping_data
                )
            else:
                # Complex mapping with additional settings
                mapping = SystemViewMapping(
                    postgresql_view=pg_view,
                    gaussdb_view=mapping_data.get("gaussdb_view", pg_view),
                    schema_mapping=mapping_data.get("schema_mapping", {}),
                    column_mappings=mapping_data.get("column_mappings", {}),
                    requires_adaptation=mapping_data.get("requires_adaptation", False),
                    fallback_query=mapping_data.get("fallback_query")
                )

            system_views[pg_view] = mapping

        return system_views

    def _parse_query_adaptations(self, adaptations_data: List[Dict[str, Any]]) -> List[QueryAdaptationRule]:
        """
        Parse query adaptation rules from configuration data.
        
        Args:
            adaptations_data: Query adaptations configuration data
            
        Returns:
            List of QueryAdaptationRule objects
        """
        adaptations = []

        for rule_data in adaptations_data:
            rule = QueryAdaptationRule(
                name=rule_data.get("name", ""),
                description=rule_data.get("description", ""),
                pattern=rule_data.get("pattern", ""),
                replacement=rule_data.get("replacement", ""),
                conditions=rule_data.get("conditions", {}),
                priority=rule_data.get("priority", 0)
            )
            adaptations.append(rule)

        # Sort by priority
        adaptations.sort(key=lambda x: x.priority, reverse=True)
        return adaptations

    def _create_default_config(self, version: str) -> GaussDbCompatibilityConfig:
        """
        Create a default configuration for a version.
        
        Args:
            version: GaussDB version
            
        Returns:
            Default GaussDbCompatibilityConfig
        """
        logger.info(f"Creating default config for GaussDB version {version}")
        return GaussDbCompatibilityConfig(version=version)

    def _validate_config(self, config: GaussDbCompatibilityConfig) -> None:
        """
        Validate a configuration object.
        
        Args:
            config: Configuration to validate
            
        Raises:
            ConfigValidationError: If validation fails
        """
        if not config.version:
            raise ConfigValidationError("Version is required")

        # Validate system view mappings
        for view_name, mapping in config.system_views.items():
            if not mapping.postgresql_view or not mapping.gaussdb_view:
                raise ConfigValidationError(f"Invalid system view mapping for {view_name}")

        # Validate query adaptation rules
        for rule in config.query_adaptations:
            if not rule.name or not rule.pattern:
                raise ConfigValidationError(f"Invalid query adaptation rule: {rule.name}")

        logger.debug(f"Configuration validation passed for version {config.version}")

    def create_default_config_file(self, force: bool = False) -> Path:
        """
        Create a default configuration file.
        
        Args:
            force: Whether to overwrite existing file
            
        Returns:
            Path to created configuration file
            
        Raises:
            FileExistsError: If file exists and force=False
        """
        config_file = self.config_dir / self.DEFAULT_CONFIG_FILENAME

        if config_file.exists() and not force:
            raise FileExistsError(f"Configuration file already exists: {config_file}")

        # Ensure directory exists
        config_file.parent.mkdir(parents=True, exist_ok=True)

        default_config = self._get_default_yaml_config()

        with open(config_file, 'w', encoding='utf-8') as f:
            yaml.dump(default_config, f, default_flow_style=False, allow_unicode=True)

        logger.info(f"Created default configuration file: {config_file}")
        return config_file

    def _get_default_yaml_config(self) -> Dict[str, Any]:
        """
        Get the default YAML configuration structure.
        
        Returns:
            Default configuration as dictionary
        """
        return {
            "# GaussDB Compatibility Configuration": None,
            "# This file defines compatibility settings for different GaussDB versions": None,
            "versions": {
                "8.1.0": {
                    "supports_hypopg": False,
                    "supports_pg_stat_statements": True,
                    "supports_explain_analyze": True,
                    "supports_vacuum_analyze": True,
                    "supports_replication_stats": True,
                    "system_views": {
                        "pg_stat_user_indexes": "pg_stat_user_indexes",
                        "pg_stat_user_tables": "pg_stat_user_tables",
                        "pg_stat_database": "pg_stat_database",
                        "pg_stat_activity": {
                            "gaussdb_view": "pg_stat_activity",
                            "requires_adaptation": True,
                            "column_mappings": {
                                "state": "state",
                                "query": "query",
                                "application_name": "application_name"
                            }
                        },
                        "pg_stat_statements": {
                            "gaussdb_view": "pg_stat_statements",
                            "requires_adaptation": True,
                            "fallback_query": "SELECT 'pg_stat_statements not available' as message"
                        }
                    },
                    "query_adaptations": [
                        {
                            "name": "version_function",
                            "description": "Adapt version() function call",
                            "pattern": "SELECT\\s+version\\(\\)",
                            "replacement": "SELECT version()",
                            "priority": 1
                        }
                    ],
                    "error_mappings": {
                        "hypopg_not_supported": "Hypothetical indexes are not supported in this GaussDB version. Consider using EXPLAIN to analyze query performance.",
                        "connection_failed": "Failed to connect to GaussDB. Please check connection parameters and database availability."
                    },
                    "connection_settings": {
                        "default_timeout": 30,
                        "max_connections": 100
                    },
                    "metadata": {
                        "description": "GaussDB 8.1.0 compatibility configuration",
                        "last_updated": "2024-01-01"
                    }
                },
                "8.2.0": {
                    "supports_hypopg": False,
                    "supports_pg_stat_statements": True,
                    "supports_explain_analyze": True,
                    "supports_vacuum_analyze": True,
                    "supports_replication_stats": True,
                    "system_views": {
                        "pg_stat_user_indexes": "pg_stat_user_indexes",
                        "pg_stat_user_tables": "pg_stat_user_tables",
                        "pg_stat_database": "pg_stat_database",
                        "pg_stat_activity": {
                            "gaussdb_view": "pg_stat_activity",
                            "requires_adaptation": True
                        }
                    },
                    "query_adaptations": [
                        {
                            "name": "version_function",
                            "description": "Adapt version() function call",
                            "pattern": "SELECT\\s+version\\(\\)",
                            "replacement": "SELECT version()",
                            "priority": 1
                        }
                    ],
                    "error_mappings": {
                        "hypopg_not_supported": "Hypothetical indexes are not supported in this GaussDB version."
                    },
                    "metadata": {
                        "description": "GaussDB 8.2.0 compatibility configuration"
                    }
                },
                "default": {
                    "supports_hypopg": False,
                    "supports_pg_stat_statements": True,
                    "supports_explain_analyze": True,
                    "supports_vacuum_analyze": True,
                    "supports_replication_stats": True,
                    "system_views": {
                        "pg_stat_user_indexes": "pg_stat_user_indexes",
                        "pg_stat_user_tables": "pg_stat_user_tables",
                        "pg_stat_database": "pg_stat_database"
                    },
                    "query_adaptations": [],
                    "error_mappings": {},
                    "metadata": {
                        "description": "Default GaussDB compatibility configuration"
                    }
                }
            }
        }

    def reload_config(self, version: str) -> GaussDbCompatibilityConfig:
        """
        Reload configuration for a version, bypassing cache.
        
        Args:
            version: GaussDB version to reload
            
        Returns:
            Reloaded configuration
        """
        # Clear from cache
        if version in self._config_cache:
            del self._config_cache[version]

        return self.load_config_for_version(version)

    def list_available_versions(self) -> List[str]:
        """
        List all available version configurations.
        
        Returns:
            List of available version strings
        """
        config_file = self.config_dir / self.DEFAULT_CONFIG_FILENAME

        if not config_file.exists():
            return []

        try:
            with open(config_file, encoding='utf-8') as f:
                yaml_data = yaml.safe_load(f)

            versions = list(yaml_data.get("versions", {}).keys())
            # Remove 'default' from the list
            return [v for v in versions if v != "default"]

        except Exception as e:
            logger.error(f"Error reading config file: {e}")
            return []
