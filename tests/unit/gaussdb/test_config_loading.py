"""
Unit tests for GaussDB configuration loading and validation.

This module tests the configuration loading system, YAML parsing,
version-specific configuration selection, and configuration validation.
"""

from pathlib import Path
from unittest.mock import mock_open
from unittest.mock import patch

import pytest
import yaml

from opengauss_mcp.gaussdb.config import GaussDbCompatibilityConfig
from opengauss_mcp.gaussdb.config import QueryAdaptationRule
from opengauss_mcp.gaussdb.config import SystemViewMapping
from opengauss_mcp.gaussdb.config_loader import ConfigLoader
from opengauss_mcp.gaussdb.config_loader import ConfigValidationError
# Config validation is handled by ConfigLoader._validate_config method


class TestConfigLoader:
    """Test cases for ConfigLoader."""

    @pytest.fixture
    def sample_config_yaml(self):
        """Sample YAML configuration for testing."""
        return """
versions:
  "8.1.0":
    supports_hypopg: false
    supports_pg_stat_statements: true
    supports_explain_analyze: true
    supports_vacuum_analyze: true
    
    system_view_mappings:
      - postgresql_view: "pg_stat_user_indexes"
        gaussdb_view: "pg_stat_user_indexes"
        description: "User index statistics"
      - postgresql_view: "pg_stat_user_tables"
        gaussdb_view: "pg_stat_user_tables"
        description: "User table statistics"
    
    query_adaptations:
      - name: "version_query"
        description: "Adapt version queries"
        pattern: "SELECT\\s+version\\(\\)"
        replacement: "SELECT version()"
        priority: 1
      - name: "pg_stat_activity"
        description: "Adapt pg_stat_activity queries"
        pattern: "FROM\\s+pg_stat_activity"
        replacement: "FROM pg_stat_activity"
        priority: 2
    
    error_mappings:
      connection_refused: "Unable to connect to GaussDB server"
      function_not_found: "Function not available in GaussDB"
    
    feature_alternatives:
      hypopg: "Use GaussDB's built-in virtual index functionality"
      
  "8.2.0":
    supports_hypopg: false
    supports_pg_stat_statements: true
    supports_explain_analyze: true
    supports_vacuum_analyze: true
    
    system_view_mappings:
      - postgresql_view: "pg_stat_user_indexes"
        gaussdb_view: "pg_stat_user_indexes"
        description: "User index statistics"
    
    query_adaptations:
      - name: "version_query"
        description: "Adapt version queries"
        pattern: "SELECT\\s+version\\(\\)"
        replacement: "SELECT version()"
        priority: 1
        
default_version: "8.1.0"
"""

    @pytest.fixture
    def config_loader(self):
        """Create a ConfigLoader instance."""
        return ConfigLoader()

    def test_load_config_from_yaml_string(self, config_loader, sample_config_yaml):
        """Test loading configuration from YAML string."""
        config = config_loader._load_config_from_yaml_string(sample_config_yaml)

        assert "versions" in config
        assert "8.1.0" in config["versions"]
        assert "8.2.0" in config["versions"]
        assert config["default_version"] == "8.1.0"

    def test_load_config_for_version_existing(self, config_loader, sample_config_yaml):
        """Test loading configuration for existing version."""
        with patch.object(config_loader, '_load_yaml_config', return_value=yaml.safe_load(sample_config_yaml)):
            config = config_loader.load_config_for_version("8.1.0")

            assert config.version == "8.1.0"
            assert config.supports_hypopg is False
            assert config.supports_pg_stat_statements is True
            assert len(config.system_views) == 2
            assert len(config.query_adaptations) == 2

    def test_load_config_for_version_fallback_to_default(self, config_loader, sample_config_yaml):
        """Test fallback to default version for unknown version."""
        with patch.object(config_loader, '_load_yaml_config', return_value=yaml.safe_load(sample_config_yaml)):
            config = config_loader.load_config_for_version("9.0.0")  # Non-existent version

            # Should fallback to default version
            assert config.version == "8.1.0"

    def test_load_config_file_not_found(self, config_loader):
        """Test handling of missing configuration file."""
        with patch('pathlib.Path.exists', return_value=False):
            with pytest.raises(ConfigValidationError, match="Configuration file not found"):
                config_loader.load_config_for_version("8.1.0")

    def test_load_config_invalid_yaml(self, config_loader):
        """Test handling of invalid YAML syntax."""
        invalid_yaml = """
        versions:
          "8.1.0":
            invalid: yaml: syntax
        """

        with patch('builtins.open', mock_open(read_data=invalid_yaml)):
            with patch('pathlib.Path.exists', return_value=True):
                with pytest.raises(ConfigValidationError, match="Invalid YAML in config file"):
                    config_loader.load_config_for_version("8.1.0")

    def test_load_config_missing_version_section(self, config_loader):
        """Test handling of configuration without versions section."""
        config_without_versions = """
        default_version: "8.1.0"
        """

        with patch.object(config_loader, '_load_yaml_config', return_value=yaml.safe_load(config_without_versions)):
            with pytest.raises(ConfigValidationError, match="No versions section found"):
                config_loader.load_config_for_version("8.1.0")

    def test_config_caching(self, config_loader, sample_config_yaml):
        """Test that configurations are cached after loading."""
        with patch.object(config_loader, '_load_yaml_config', return_value=yaml.safe_load(sample_config_yaml)) as mock_load:
            # First load
            config1 = config_loader.load_config_for_version("8.1.0")

            # Second load should use cache
            config2 = config_loader.load_config_for_version("8.1.0")

            assert config1.version == config2.version
            # YAML should only be loaded once
            mock_load.assert_called_once()

    def test_clear_cache(self, config_loader, sample_config_yaml):
        """Test cache clearing functionality."""
        with patch.object(config_loader, '_load_yaml_config', return_value=yaml.safe_load(sample_config_yaml)) as mock_load:
            # Load config
            config_loader.load_config_for_version("8.1.0")

            # Clear cache
            config_loader.clear_cache()

            # Load again should reload from file
            config_loader.load_config_for_version("8.1.0")

            # Should have loaded twice
            assert mock_load.call_count == 2

    def test_get_available_versions(self, config_loader, sample_config_yaml):
        """Test getting list of available versions."""
        with patch.object(config_loader, '_load_yaml_config', return_value=yaml.safe_load(sample_config_yaml)):
            versions = config_loader.get_available_versions()

            assert "8.1.0" in versions
            assert "8.2.0" in versions
            assert len(versions) == 2

    def test_get_default_version(self, config_loader, sample_config_yaml):
        """Test getting default version."""
        with patch.object(config_loader, '_load_yaml_config', return_value=yaml.safe_load(sample_config_yaml)):
            default_version = config_loader.get_default_version()

            assert default_version == "8.1.0"

    def test_custom_config_path(self):
        """Test loading configuration from custom path."""
        custom_path = Path("/custom/path/config.yaml")
        config_loader = ConfigLoader(config_path=custom_path)

        assert config_loader.config_path == custom_path


class TestGaussDbCompatibilityConfig:
    """Test cases for GaussDbCompatibilityConfig."""

    def test_config_initialization_with_defaults(self):
        """Test configuration initialization with default values."""
        config = GaussDbCompatibilityConfig(version="8.1.0")

        assert config.version == "8.1.0"
        assert config.supports_hypopg is False
        assert config.supports_pg_stat_statements is True
        assert len(config.system_views) > 0
        assert len(config.query_adaptations) > 0
        assert config.error_mappings == {}
        assert config.connection_settings == {}

    def test_config_from_dict(self):
        """Test creating configuration from dictionary."""
        config_dict = {
            "supports_hypopg": False,
            "supports_pg_stat_statements": True,
            "supports_explain_analyze": True,
            "supports_vacuum_analyze": True,
            "system_view_mappings": [
                {
                    "postgresql_view": "pg_stat_user_indexes",
                    "gaussdb_view": "pg_stat_user_indexes",
                    "description": "User index statistics"
                }
            ],
            "query_adaptations": [
                {
                    "name": "version_query",
                    "description": "Adapt version queries",
                    "pattern": "SELECT\\s+version\\(\\)",
                    "replacement": "SELECT version()",
                    "priority": 1
                }
            ],
            "error_mappings": {
                "connection_refused": "Unable to connect to GaussDB server"
            },
            "feature_alternatives": {
                "hypopg": "Use EXPLAIN ANALYZE to test index performance"
            }
        }

        config = GaussDbCompatibilityConfig("8.1.0", **config_dict)

        assert config.version == "8.1.0"
        assert config.supports_hypopg is False
        assert config.supports_pg_stat_statements is True
        assert len(config.system_views) == 1
        assert len(config.query_adaptations) == 1
        assert "connection_refused" in config.error_mappings

    def test_feature_support_methods(self):
        """Test feature support methods."""
        config = GaussDbCompatibilityConfig(version="8.1.0")
        config.supports_hypopg = False
        config.supports_pg_stat_statements = True
        config.supports_explain_analyze = True
        config.supports_vacuum_analyze = True

        assert config.is_feature_supported("hypopg") is False
        assert config.is_feature_supported("pg_stat_statements") is True
        assert config.is_feature_supported("explain_analyze") is True
        assert config.is_feature_supported("vacuum_analyze") is True
        assert config.is_feature_supported("nonexistent") is False

    def test_system_view_mapping_creation(self):
        """Test SystemViewMapping object creation."""
        mapping = SystemViewMapping(
            postgresql_view="pg_stat_user_indexes",
            gaussdb_view="pg_stat_user_indexes"
        )

        assert mapping.postgresql_view == "pg_stat_user_indexes"
        assert mapping.gaussdb_view == "pg_stat_user_indexes"

    def test_query_adaptation_rule_creation(self):
        """Test QueryAdaptationRule object creation."""
        rule = QueryAdaptationRule(
            name="version_query",
            description="Adapt version queries",
            pattern="SELECT\\s+version\\(\\)",
            replacement="SELECT version()",
            priority=1
        )

        assert rule.name == "version_query"
        assert rule.description == "Adapt version queries"
        assert rule.pattern == "SELECT\\s+version\\(\\)"
        assert rule.replacement == "SELECT version()"
        assert rule.priority == 1

    def test_config_serialization(self):
        """Test configuration serialization to dictionary."""
        config = GaussDbCompatibilityConfig(version="8.1.0")
        config.supports_hypopg = False
        config.supports_pg_stat_statements = True

        config_dict = config.to_dict()

        assert config_dict["version"] == "8.1.0"
        assert config_dict["supports_hypopg"] is False
        assert config_dict["supports_pg_stat_statements"] is True
        assert "system_views" in config_dict
        assert len(config_dict["system_views"]) > 0




class TestConfigIntegration:
    """Integration tests for configuration loading and validation."""

    def test_load_and_validate_config(self):
        """Test loading and validating configuration end-to-end."""
        config_yaml = """
versions:
  "8.1.0":
    supports_hypopg: false
    supports_pg_stat_statements: true
    supports_explain_analyze: true
    supports_vacuum_analyze: true
    
    query_adaptations:
      - name: "version_query"
        description: "Adapt version queries"
        pattern: "SELECT\\\\s+version\\\\(\\\\)"
        replacement: "SELECT version()"
        priority: 1
        
default_version: "8.1.0"
"""

        config_loader = ConfigLoader()

        with patch.object(config_loader, '_load_yaml_config', return_value=yaml.safe_load(config_yaml)):
            # Load configuration (this includes validation)
            config = config_loader.load_config_for_version("8.1.0")

            assert config.version == "8.1.0"
            assert len(config.query_adaptations) == 1

    def test_config_error_handling_integration(self):
        """Test error handling in configuration loading and validation."""
        invalid_config_yaml = """
versions:
  "8.1.0":
    query_adaptations:
      - name: ""  # Invalid: empty name
        pattern: "[invalid"  # Invalid: bad regex
        replacement: "test"
        priority: -1  # Invalid: negative priority
        
default_version: "8.1.0"
"""

        config_loader = ConfigLoader()

        with patch.object(config_loader, '_load_yaml_config', return_value=yaml.safe_load(invalid_config_yaml)):
            # Load configuration (should fail validation due to empty name)
            with pytest.raises(ConfigValidationError):
                config_loader.load_config_for_version("8.1.0")


if __name__ == "__main__":
    pytest.main([__file__])
