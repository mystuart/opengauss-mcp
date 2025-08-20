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

from postgres_mcp.gaussdb.config import FeatureSupport
from postgres_mcp.gaussdb.config import GaussDbCompatibilityConfig
from postgres_mcp.gaussdb.config import QueryAdaptationRule
from postgres_mcp.gaussdb.config import SystemViewMapping
from postgres_mcp.gaussdb.config_loader import ConfigLoader
from postgres_mcp.gaussdb.config_loader import ConfigLoadError
from postgres_mcp.gaussdb.validate_config import ConfigValidator


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
      hypopg: "Use EXPLAIN ANALYZE to test index performance"
      
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
            assert config.feature_support.supports_hypopg is False
            assert config.feature_support.supports_pg_stat_statements is True
            assert len(config.system_view_mappings) == 2
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
            with pytest.raises(ConfigLoadError, match="Configuration file not found"):
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
                with pytest.raises(ConfigLoadError, match="Failed to parse YAML"):
                    config_loader.load_config_for_version("8.1.0")

    def test_load_config_missing_version_section(self, config_loader):
        """Test handling of configuration without versions section."""
        config_without_versions = """
        default_version: "8.1.0"
        """

        with patch.object(config_loader, '_load_yaml_config', return_value=yaml.safe_load(config_without_versions)):
            with pytest.raises(ConfigLoadError, match="No versions section found"):
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
        assert config.feature_support is not None
        assert config.system_view_mappings == []
        assert config.query_adaptations == []
        assert config.error_mappings == {}
        assert config.feature_alternatives == {}

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

        config = GaussDbCompatibilityConfig.from_dict("8.1.0", config_dict)

        assert config.version == "8.1.0"
        assert config.feature_support.supports_hypopg is False
        assert config.feature_support.supports_pg_stat_statements is True
        assert len(config.system_view_mappings) == 1
        assert len(config.query_adaptations) == 1
        assert "connection_refused" in config.error_mappings
        assert "hypopg" in config.feature_alternatives

    def test_feature_support_creation(self):
        """Test FeatureSupport object creation."""
        feature_support = FeatureSupport(
            supports_hypopg=False,
            supports_pg_stat_statements=True,
            supports_explain_analyze=True,
            supports_vacuum_analyze=True
        )

        assert feature_support.supports_hypopg is False
        assert feature_support.supports_pg_stat_statements is True
        assert feature_support.supports_explain_analyze is True
        assert feature_support.supports_vacuum_analyze is True

    def test_system_view_mapping_creation(self):
        """Test SystemViewMapping object creation."""
        mapping = SystemViewMapping(
            postgresql_view="pg_stat_user_indexes",
            gaussdb_view="pg_stat_user_indexes",
            description="User index statistics"
        )

        assert mapping.postgresql_view == "pg_stat_user_indexes"
        assert mapping.gaussdb_view == "pg_stat_user_indexes"
        assert mapping.description == "User index statistics"

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
        config.feature_support = FeatureSupport(
            supports_hypopg=False,
            supports_pg_stat_statements=True
        )
        config.system_view_mappings = [
            SystemViewMapping(
                postgresql_view="pg_stat_user_indexes",
                gaussdb_view="pg_stat_user_indexes",
                description="User index statistics"
            )
        ]

        config_dict = config.to_dict()

        assert config_dict["version"] == "8.1.0"
        assert "feature_support" in config_dict
        assert "system_view_mappings" in config_dict
        assert len(config_dict["system_view_mappings"]) == 1


class TestConfigValidator:
    """Test cases for ConfigValidator."""

    @pytest.fixture
    def validator(self):
        """Create a ConfigValidator instance."""
        return ConfigValidator()

    def test_validate_valid_config(self, validator):
        """Test validation of a valid configuration."""
        config = GaussDbCompatibilityConfig(version="8.1.0")
        config.feature_support = FeatureSupport(
            supports_hypopg=False,
            supports_pg_stat_statements=True
        )
        config.query_adaptations = [
            QueryAdaptationRule(
                name="test_rule",
                description="Test rule",
                pattern="SELECT\\s+version\\(\\)",
                replacement="SELECT version()",
                priority=1
            )
        ]

        result = validator.validate_config(config)

        assert result.is_valid is True
        assert len(result.errors) == 0
        assert len(result.warnings) == 0

    def test_validate_invalid_regex_pattern(self, validator):
        """Test validation of configuration with invalid regex pattern."""
        config = GaussDbCompatibilityConfig(version="8.1.0")
        config.query_adaptations = [
            QueryAdaptationRule(
                name="invalid_rule",
                description="Invalid rule",
                pattern="[invalid regex",  # Invalid regex
                replacement="replacement",
                priority=1
            )
        ]

        result = validator.validate_config(config)

        assert result.is_valid is False
        assert len(result.errors) > 0
        assert any("Invalid regex pattern" in error for error in result.errors)

    def test_validate_duplicate_rule_names(self, validator):
        """Test validation of configuration with duplicate rule names."""
        config = GaussDbCompatibilityConfig(version="8.1.0")
        config.query_adaptations = [
            QueryAdaptationRule(
                name="duplicate_rule",
                description="First rule",
                pattern="SELECT 1",
                replacement="SELECT 1",
                priority=1
            ),
            QueryAdaptationRule(
                name="duplicate_rule",
                description="Second rule",
                pattern="SELECT 2",
                replacement="SELECT 2",
                priority=2
            )
        ]

        result = validator.validate_config(config)

        assert result.is_valid is False
        assert any("Duplicate rule name" in error for error in result.errors)

    def test_validate_invalid_priority_values(self, validator):
        """Test validation of configuration with invalid priority values."""
        config = GaussDbCompatibilityConfig(version="8.1.0")
        config.query_adaptations = [
            QueryAdaptationRule(
                name="invalid_priority",
                description="Rule with invalid priority",
                pattern="SELECT 1",
                replacement="SELECT 1",
                priority=-1  # Invalid priority
            )
        ]

        result = validator.validate_config(config)

        assert result.is_valid is False
        assert any("Priority must be positive" in error for error in result.errors)

    def test_validate_empty_rule_name(self, validator):
        """Test validation of configuration with empty rule name."""
        config = GaussDbCompatibilityConfig(version="8.1.0")
        config.query_adaptations = [
            QueryAdaptationRule(
                name="",  # Empty name
                description="Rule with empty name",
                pattern="SELECT 1",
                replacement="SELECT 1",
                priority=1
            )
        ]

        result = validator.validate_config(config)

        assert result.is_valid is False
        assert any("Rule name cannot be empty" in error for error in result.errors)

    def test_validate_system_view_mappings(self, validator):
        """Test validation of system view mappings."""
        config = GaussDbCompatibilityConfig(version="8.1.0")
        config.system_view_mappings = [
            SystemViewMapping(
                postgresql_view="",  # Empty view name
                gaussdb_view="pg_stat_user_indexes",
                description="Invalid mapping"
            )
        ]

        result = validator.validate_config(config)

        assert result.is_valid is False
        assert any("PostgreSQL view name cannot be empty" in error for error in result.errors)

    def test_validate_with_warnings(self, validator):
        """Test validation that produces warnings but is still valid."""
        config = GaussDbCompatibilityConfig(version="8.1.0")
        config.query_adaptations = [
            QueryAdaptationRule(
                name="low_priority_rule",
                description="Rule with very low priority",
                pattern="SELECT 1",
                replacement="SELECT 1",
                priority=1000  # Very low priority, should generate warning
            )
        ]

        result = validator.validate_config(config)

        assert result.is_valid is True
        assert len(result.warnings) > 0
        assert any("very low priority" in warning for warning in result.warnings)

    def test_validation_result_summary(self, validator):
        """Test ValidationResult summary functionality."""
        config = GaussDbCompatibilityConfig(version="8.1.0")
        config.query_adaptations = [
            QueryAdaptationRule(
                name="",  # Invalid: empty name
                description="Rule with issues",
                pattern="[invalid",  # Invalid: bad regex
                replacement="SELECT 1",
                priority=-1  # Invalid: negative priority
            )
        ]

        result = validator.validate_config(config)

        summary = result.get_summary()

        assert "Configuration validation failed" in summary
        assert "3 errors found" in summary
        assert len(result.errors) == 3

    def test_validate_feature_support_consistency(self, validator):
        """Test validation of feature support consistency."""
        config = GaussDbCompatibilityConfig(version="8.1.0")
        config.feature_support = FeatureSupport(
            supports_hypopg=True,  # Claim to support hypopg
            supports_pg_stat_statements=False
        )
        # But provide alternative for hypopg (inconsistent)
        config.feature_alternatives = {
            "hypopg": "Use EXPLAIN ANALYZE instead"
        }

        result = validator.validate_config(config)

        # Should generate warning about inconsistency
        assert len(result.warnings) > 0
        assert any("hypopg" in warning and "inconsistent" in warning for warning in result.warnings)


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
        validator = ConfigValidator()

        with patch.object(config_loader, '_load_yaml_config', return_value=yaml.safe_load(config_yaml)):
            # Load configuration
            config = config_loader.load_config_for_version("8.1.0")

            # Validate configuration
            result = validator.validate_config(config)

            assert result.is_valid is True
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
        validator = ConfigValidator()

        with patch.object(config_loader, '_load_yaml_config', return_value=yaml.safe_load(invalid_config_yaml)):
            # Load configuration (should succeed despite invalid content)
            config = config_loader.load_config_for_version("8.1.0")

            # Validate configuration (should fail)
            result = validator.validate_config(config)

            assert result.is_valid is False
            assert len(result.errors) >= 3  # At least 3 errors from the invalid rule


if __name__ == "__main__":
    pytest.main([__file__])
