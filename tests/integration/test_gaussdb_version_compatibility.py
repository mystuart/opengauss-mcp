"""
Integration tests for GaussDB multi-version compatibility.

This module tests compatibility across different GaussDB versions,
including version detection, feature availability, and graceful
degradation when features are not supported.
"""

from typing import Any
from typing import Dict
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest

from postgres_mcp.gaussdb.config import FeatureSupport
from postgres_mcp.gaussdb.config import GaussDbCompatibilityConfig
from postgres_mcp.gaussdb.config_loader import ConfigLoader
from postgres_mcp.gaussdb.feature_checker import FeatureAvailabilityChecker
from postgres_mcp.gaussdb.sql_driver_adapter import GaussDbSqlDriver
from postgres_mcp.sql.database_detection import DatabaseType
from postgres_mcp.sql.sql_driver import SqlDriver


class MockRowResult:
    """Mock RowResult for version compatibility testing."""

    def __init__(self, cells: Dict[str, Any]):
        self.cells = cells


@pytest.fixture
def mock_sql_driver():
    """Create a mock SQL driver for version testing."""
    driver = AsyncMock(spec=SqlDriver)
    driver.execute_query = AsyncMock()
    driver.initialize_database_info = AsyncMock()
    return driver


class TestGaussDbVersionDetection:
    """Test cases for GaussDB version detection across different versions."""

    @pytest.mark.parametrize("version_info", [
        {
            "version_string": "GaussDB 8.1.0 on x86_64-linux-gnu",
            "expected_version": "8.1.0",
            "expected_type": DatabaseType.GAUSSDB
        },
        {
            "version_string": "GaussDB 8.2.0 build 12345 on aarch64-linux-gnu",
            "expected_version": "8.2.0",
            "expected_type": DatabaseType.GAUSSDB
        },
        {
            "version_string": "(MogDB 5.0.0 build 503a9ef7) compiled at 2023-06-26 16:30:46",
            "expected_version": "5.0.0",
            "expected_type": DatabaseType.GAUSSDB
        },
        {
            "version_string": "openGauss 3.1.0 on x86_64-linux-gnu",
            "expected_version": "3.1.0",
            "expected_type": DatabaseType.GAUSSDB
        },
        {
            "version_string": "openGauss 5.0.0 build 12345 compiled at 2023-12-01",
            "expected_version": "5.0.0",
            "expected_type": DatabaseType.GAUSSDB
        }
    ])
    @pytest.mark.asyncio
    async def test_version_detection_across_variants(self, mock_sql_driver, version_info):
        """Test version detection across different GaussDB variants."""
        # Mock version query response
        mock_sql_driver.execute_query.return_value = [
            MockRowResult({"version": version_info["version_string"]})
        ]
        mock_sql_driver.get_database_version.return_value = version_info["expected_version"]
        mock_sql_driver.get_database_type.return_value = version_info["expected_type"]

        # Create GaussDB driver
        gaussdb_driver = GaussDbSqlDriver(mock_sql_driver)

        # Test version detection
        await gaussdb_driver._ensure_config_loaded()

        assert gaussdb_driver._compatibility_config.version == version_info["expected_version"]

        # Verify database type detection
        db_type = await gaussdb_driver.get_database_type()
        assert db_type == version_info["expected_type"]

    @pytest.mark.asyncio
    async def test_version_specific_configuration_loading(self, mock_sql_driver):
        """Test that version-specific configurations are loaded correctly."""
        test_versions = ["8.1.0", "8.2.0", "5.0.0", "3.1.0"]

        for version in test_versions:
            mock_sql_driver.get_database_version.return_value = version

            # Mock version-specific configuration
            mock_config = GaussDbCompatibilityConfig(version=version)
            mock_config.feature_support = FeatureSupport(
                supports_hypopg=(version >= "8.2.0"),  # Hypothetical feature availability
                supports_pg_stat_statements=True,
                supports_explain_analyze=True,
                supports_vacuum_analyze=(version >= "5.0.0")
            )

            mock_config_loader = MagicMock(spec=ConfigLoader)
            mock_config_loader.load_config_for_version.return_value = mock_config

            gaussdb_driver = GaussDbSqlDriver(mock_sql_driver, mock_config_loader)

            # Test configuration loading
            await gaussdb_driver._ensure_config_loaded()

            assert gaussdb_driver._compatibility_config.version == version
            mock_config_loader.load_config_for_version.assert_called_with(version)

    @pytest.mark.asyncio
    async def test_unknown_version_fallback(self, mock_sql_driver):
        """Test fallback behavior for unknown GaussDB versions."""
        # Mock unknown version
        unknown_version = "9.9.9"
        mock_sql_driver.get_database_version.return_value = unknown_version

        # Mock config loader to return default configuration
        default_config = GaussDbCompatibilityConfig(version="8.1.0")  # Default fallback
        mock_config_loader = MagicMock(spec=ConfigLoader)
        mock_config_loader.load_config_for_version.return_value = default_config

        gaussdb_driver = GaussDbSqlDriver(mock_sql_driver, mock_config_loader)

        # Test fallback configuration loading
        await gaussdb_driver._ensure_config_loaded()

        # Should fallback to default version
        assert gaussdb_driver._compatibility_config.version == "8.1.0"
        mock_config_loader.load_config_for_version.assert_called_with(unknown_version)


class TestFeatureCompatibilityAcrossVersions:
    """Test feature compatibility across different GaussDB versions."""

    @pytest.fixture
    def version_feature_matrix(self):
        """Define feature availability matrix across versions."""
        return {
            "3.1.0": {
                "supports_hypopg": False,
                "supports_pg_stat_statements": True,
                "supports_explain_analyze": True,
                "supports_vacuum_analyze": False,
                "supports_replication_stats": False
            },
            "5.0.0": {
                "supports_hypopg": False,
                "supports_pg_stat_statements": True,
                "supports_explain_analyze": True,
                "supports_vacuum_analyze": True,
                "supports_replication_stats": True
            },
            "8.1.0": {
                "supports_hypopg": False,
                "supports_pg_stat_statements": True,
                "supports_explain_analyze": True,
                "supports_vacuum_analyze": True,
                "supports_replication_stats": True
            },
            "8.2.0": {
                "supports_hypopg": True,  # Hypothetical future support
                "supports_pg_stat_statements": True,
                "supports_explain_analyze": True,
                "supports_vacuum_analyze": True,
                "supports_replication_stats": True
            }
        }

    @pytest.mark.asyncio
    async def test_feature_availability_by_version(self, mock_sql_driver, version_feature_matrix):
        """Test feature availability detection across versions."""
        for version, features in version_feature_matrix.items():
            mock_sql_driver.get_database_version.return_value = version

            # Mock feature support configuration
            mock_config = GaussDbCompatibilityConfig(version=version)
            mock_config.feature_support = FeatureSupport(**features)

            mock_config_loader = MagicMock(spec=ConfigLoader)
            mock_config_loader.load_config_for_version.return_value = mock_config

            gaussdb_driver = GaussDbSqlDriver(mock_sql_driver, mock_config_loader)
            await gaussdb_driver._ensure_config_loaded()

            # Test feature availability
            feature_checker = FeatureAvailabilityChecker(gaussdb_driver)

            # Test hypopg support
            hypopg_support = await feature_checker.check_hypopg_support()
            assert hypopg_support == features["supports_hypopg"]

            # Test pg_stat_statements support
            pg_stat_support = await feature_checker.check_pg_stat_statements()
            assert pg_stat_support == features["supports_pg_stat_statements"]

    @pytest.mark.asyncio
    async def test_graceful_degradation_for_unsupported_features(self, mock_sql_driver):
        """Test graceful degradation when features are not supported."""
        # Mock older version with limited features
        mock_sql_driver.get_database_version.return_value = "3.1.0"

        # Mock configuration with limited feature support
        limited_config = GaussDbCompatibilityConfig(version="3.1.0")
        limited_config.feature_support = FeatureSupport(
            supports_hypopg=False,
            supports_pg_stat_statements=True,
            supports_explain_analyze=True,
            supports_vacuum_analyze=False
        )

        mock_config_loader = MagicMock(spec=ConfigLoader)
        mock_config_loader.load_config_for_version.return_value = limited_config

        gaussdb_driver = GaussDbSqlDriver(mock_sql_driver, mock_config_loader)
        await gaussdb_driver._ensure_config_loaded()

        # Test feature checker with unsupported features
        feature_checker = FeatureAvailabilityChecker(gaussdb_driver)

        # Test hypopg support (should be False)
        hypopg_support = await feature_checker.check_hypopg_support()
        assert hypopg_support is False

        # Test alternative suggestions
        hypopg_alternative = feature_checker.get_feature_alternative("hypopg")
        assert hypopg_alternative is not None
        assert "EXPLAIN ANALYZE" in hypopg_alternative

    @pytest.mark.asyncio
    async def test_feature_detection_with_runtime_checks(self, mock_sql_driver):
        """Test feature detection with runtime database checks."""
        mock_sql_driver.get_database_version.return_value = "8.1.0"

        # Mock runtime feature detection queries
        feature_check_responses = [
            # Check for hypopg extension
            [],  # Empty result = extension not available

            # Check for pg_stat_statements
            [MockRowResult({"extname": "pg_stat_statements"})],  # Available

            # Check for specific system views
            [MockRowResult({"viewname": "pg_stat_replication"})],  # Available
        ]

        mock_sql_driver.execute_query.side_effect = feature_check_responses

        gaussdb_driver = GaussDbSqlDriver(mock_sql_driver)
        feature_checker = FeatureAvailabilityChecker(gaussdb_driver)

        # Test runtime feature detection
        hypopg_available = await feature_checker.check_hypopg_support()
        pg_stat_available = await feature_checker.check_pg_stat_statements()
        replication_available = await feature_checker.check_replication_support()

        assert hypopg_available is False      # Not available
        assert pg_stat_available is True     # Available
        assert replication_available is True # Available


class TestVersionSpecificQueryAdaptation:
    """Test query adaptation across different GaussDB versions."""

    @pytest.mark.asyncio
    async def test_version_specific_query_adaptations(self, mock_sql_driver):
        """Test that query adaptations are version-specific."""
        version_adaptations = {
            "3.1.0": {
                # Older version might need more adaptations
                "SELECT version()": "SELECT version()",
                "FROM pg_stat_activity": "FROM pg_stat_activity"
            },
            "8.1.0": {
                # Newer version might need fewer adaptations
                "SELECT version()": "SELECT version()"
            },
            "8.2.0": {
                # Latest version might have new features
                "SELECT version()": "SELECT version()",
                "FROM pg_stat_statements": "FROM pg_stat_statements"
            }
        }

        for version, adaptations in version_adaptations.items():
            mock_sql_driver.get_database_version.return_value = version

            # Mock version-specific configuration
            from postgres_mcp.gaussdb.config import QueryAdaptationRule

            mock_config = GaussDbCompatibilityConfig(version=version)
            mock_config.query_adaptations = [
                QueryAdaptationRule(
                    name=f"rule_{i}",
                    description=f"Adaptation rule {i}",
                    pattern=pattern,
                    replacement=replacement,
                    priority=i+1
                )
                for i, (pattern, replacement) in enumerate(adaptations.items())
            ]

            mock_config_loader = MagicMock(spec=ConfigLoader)
            mock_config_loader.load_config_for_version.return_value = mock_config

            gaussdb_driver = GaussDbSqlDriver(mock_sql_driver, mock_config_loader)
            await gaussdb_driver._ensure_config_loaded()

            # Test version-specific query adaptations
            for original_query, expected_adapted in adaptations.items():
                adapted_query = await gaussdb_driver.adapt_query(original_query)
                assert adapted_query == expected_adapted

    @pytest.mark.asyncio
    async def test_backward_compatibility_adaptations(self, mock_sql_driver):
        """Test backward compatibility adaptations for older versions."""
        # Mock older GaussDB version
        mock_sql_driver.get_database_version.return_value = "3.1.0"

        # Mock configuration with backward compatibility adaptations
        from postgres_mcp.gaussdb.config import QueryAdaptationRule

        backward_compat_config = GaussDbCompatibilityConfig(version="3.1.0")
        backward_compat_config.query_adaptations = [
            QueryAdaptationRule(
                name="legacy_stats_view",
                description="Adapt to legacy statistics view",
                pattern=r"FROM\s+pg_stat_user_indexes",
                replacement="FROM pg_stat_user_indexes",  # Might need different view name
                priority=1
            ),
            QueryAdaptationRule(
                name="legacy_function",
                description="Adapt to legacy function syntax",
                pattern=r"pg_size_pretty\((.+)\)",
                replacement=r"pg_size_pretty(\1)",  # Might need different function
                priority=2
            )
        ]

        mock_config_loader = MagicMock(spec=ConfigLoader)
        mock_config_loader.load_config_for_version.return_value = backward_compat_config

        gaussdb_driver = GaussDbSqlDriver(mock_sql_driver, mock_config_loader)
        await gaussdb_driver._ensure_config_loaded()

        # Test backward compatibility adaptations
        test_queries = [
            "SELECT * FROM pg_stat_user_indexes",
            "SELECT pg_size_pretty(pg_total_relation_size('table'))"
        ]

        for query in test_queries:
            adapted_query = await gaussdb_driver.adapt_query(query)
            # Should apply appropriate adaptations without errors
            assert adapted_query is not None
            assert len(adapted_query) > 0


class TestVersionSpecificErrorHandling:
    """Test version-specific error handling and messaging."""

    @pytest.mark.asyncio
    async def test_version_specific_error_messages(self, mock_sql_driver):
        """Test that error messages are appropriate for specific versions."""
        version_error_scenarios = [
            {
                "version": "3.1.0",
                "error": Exception("function pg_stat_statements does not exist"),
                "expected_message_contains": ["not available", "3.1.0", "upgrade"]
            },
            {
                "version": "8.1.0",
                "error": Exception("extension hypopg is not installed"),
                "expected_message_contains": ["hypopg", "not supported", "EXPLAIN ANALYZE"]
            },
            {
                "version": "5.0.0",
                "error": Exception("permission denied for relation pg_stat_replication"),
                "expected_message_contains": ["permission", "replication", "privileges"]
            }
        ]

        for scenario in version_error_scenarios:
            mock_sql_driver.get_database_version.return_value = scenario["version"]

            # Mock error handling configuration
            mock_config = GaussDbCompatibilityConfig(version=scenario["version"])
            mock_config.error_mappings = {
                "function.*does not exist": f"Function not available in GaussDB {scenario['version']}",
                "extension.*not installed": f"Extension not supported in GaussDB {scenario['version']}",
                "permission denied": f"Insufficient privileges for GaussDB {scenario['version']}"
            }

            mock_config_loader = MagicMock(spec=ConfigLoader)
            mock_config_loader.load_config_for_version.return_value = mock_config

            gaussdb_driver = GaussDbSqlDriver(mock_sql_driver, mock_config_loader)
            await gaussdb_driver._ensure_config_loaded()

            # Test error handling
            error_handler = gaussdb_driver._error_handler
            message, category, action = error_handler.handle_error(scenario["error"])

            # Verify version-specific error message
            for expected_text in scenario["expected_message_contains"]:
                assert expected_text.lower() in message.lower()

    @pytest.mark.asyncio
    async def test_version_upgrade_recommendations(self, mock_sql_driver):
        """Test upgrade recommendations for older versions."""
        # Mock older version
        mock_sql_driver.get_database_version.return_value = "3.1.0"

        mock_config = GaussDbCompatibilityConfig(version="3.1.0")
        mock_config.feature_alternatives = {
            "pg_stat_statements": "Consider upgrading to GaussDB 5.0.0+ for pg_stat_statements support",
            "vacuum_analyze": "Consider upgrading to GaussDB 5.0.0+ for advanced vacuum features",
            "replication_stats": "Consider upgrading to GaussDB 5.0.0+ for replication monitoring"
        }

        mock_config_loader = MagicMock(spec=ConfigLoader)
        mock_config_loader.load_config_for_version.return_value = mock_config

        gaussdb_driver = GaussDbSqlDriver(mock_sql_driver, mock_config_loader)
        await gaussdb_driver._ensure_config_loaded()

        # Test upgrade recommendations
        feature_checker = FeatureAvailabilityChecker(gaussdb_driver)

        for feature, expected_recommendation in mock_config.feature_alternatives.items():
            recommendation = feature_checker.get_feature_alternative(feature)
            assert recommendation == expected_recommendation
            assert "upgrading" in recommendation.lower()
            assert "5.0.0" in recommendation


class TestCrossVersionCompatibilityMatrix:
    """Test compatibility matrix across multiple GaussDB versions."""

    @pytest.fixture
    def compatibility_matrix(self):
        """Define compatibility matrix for testing."""
        return {
            "features": {
                "basic_queries": ["3.1.0", "5.0.0", "8.1.0", "8.2.0"],
                "pg_stat_statements": ["5.0.0", "8.1.0", "8.2.0"],
                "explain_analyze": ["3.1.0", "5.0.0", "8.1.0", "8.2.0"],
                "vacuum_analyze": ["5.0.0", "8.1.0", "8.2.0"],
                "replication_stats": ["5.0.0", "8.1.0", "8.2.0"],
                "hypopg": ["8.2.0"]  # Hypothetical future support
            },
            "system_views": {
                "pg_stat_activity": ["3.1.0", "5.0.0", "8.1.0", "8.2.0"],
                "pg_stat_user_indexes": ["3.1.0", "5.0.0", "8.1.0", "8.2.0"],
                "pg_stat_replication": ["5.0.0", "8.1.0", "8.2.0"],
                "pg_stat_statements": ["5.0.0", "8.1.0", "8.2.0"]
            }
        }

    @pytest.mark.asyncio
    async def test_feature_compatibility_matrix(self, mock_sql_driver, compatibility_matrix):
        """Test feature compatibility across the version matrix."""
        all_versions = ["3.1.0", "5.0.0", "8.1.0", "8.2.0"]

        for version in all_versions:
            mock_sql_driver.get_database_version.return_value = version

            # Create feature support based on compatibility matrix
            feature_support = FeatureSupport(
                supports_hypopg=(version in compatibility_matrix["features"]["hypopg"]),
                supports_pg_stat_statements=(version in compatibility_matrix["features"]["pg_stat_statements"]),
                supports_explain_analyze=(version in compatibility_matrix["features"]["explain_analyze"]),
                supports_vacuum_analyze=(version in compatibility_matrix["features"]["vacuum_analyze"])
            )

            mock_config = GaussDbCompatibilityConfig(version=version)
            mock_config.feature_support = feature_support

            mock_config_loader = MagicMock(spec=ConfigLoader)
            mock_config_loader.load_config_for_version.return_value = mock_config

            gaussdb_driver = GaussDbSqlDriver(mock_sql_driver, mock_config_loader)
            await gaussdb_driver._ensure_config_loaded()

            # Test each feature's availability
            feature_checker = FeatureAvailabilityChecker(gaussdb_driver)

            # Test hypopg support
            hypopg_expected = version in compatibility_matrix["features"]["hypopg"]
            hypopg_actual = await feature_checker.check_hypopg_support()
            assert hypopg_actual == hypopg_expected, f"hypopg support mismatch for version {version}"

            # Test pg_stat_statements support
            pg_stat_expected = version in compatibility_matrix["features"]["pg_stat_statements"]
            pg_stat_actual = await feature_checker.check_pg_stat_statements()
            assert pg_stat_actual == pg_stat_expected, f"pg_stat_statements support mismatch for version {version}"

    @pytest.mark.asyncio
    async def test_system_view_compatibility_matrix(self, mock_sql_driver, compatibility_matrix):
        """Test system view compatibility across versions."""
        all_versions = ["3.1.0", "5.0.0", "8.1.0", "8.2.0"]

        for version in all_versions:
            mock_sql_driver.get_database_version.return_value = version

            # Mock system view availability checks
            view_responses = {}
            for view, supported_versions in compatibility_matrix["system_views"].items():
                if version in supported_versions:
                    view_responses[view] = [MockRowResult({"viewname": view})]
                else:
                    view_responses[view] = []  # View not available

            def mock_execute_query(query, **kwargs):
                # Determine which view is being queried
                for view in compatibility_matrix["system_views"]:
                    if view in query:
                        return view_responses[view]
                return []

            mock_sql_driver.execute_query.side_effect = mock_execute_query

            gaussdb_driver = GaussDbSqlDriver(mock_sql_driver)
            feature_checker = FeatureAvailabilityChecker(gaussdb_driver)

            # Test system view availability
            for view, supported_versions in compatibility_matrix["system_views"].items():
                expected_available = version in supported_versions

                # Test view availability
                query = f"SELECT * FROM information_schema.views WHERE table_name = '{view}'"
                result = await gaussdb_driver.execute_query(query)
                actual_available = len(result) > 0

                assert actual_available == expected_available, \
                    f"System view {view} availability mismatch for version {version}"


if __name__ == "__main__":
    pytest.main([__file__])
