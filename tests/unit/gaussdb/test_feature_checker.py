"""
Unit tests for GaussDB feature availability checker.

This module tests the FeatureAvailabilityChecker class and the
check_hypopg_installation_status function.
"""

from typing import Any
from typing import Dict
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from postgres_mcp.gaussdb.config import GaussDbCompatibilityConfig
from postgres_mcp.gaussdb.error_handler import GaussDbErrorHandler
from postgres_mcp.gaussdb.feature_checker import FeatureAvailabilityChecker
from postgres_mcp.gaussdb.feature_checker import check_hypopg_installation_status


class MockRowResult:
    """Mock row result for testing."""

    def __init__(self, cells: Dict[str, Any]):
        self.cells = cells


@pytest.fixture
def mock_gaussdb_driver():
    """Create a mock GaussDbSqlDriver."""
    driver = MagicMock()
    driver.execute_query = AsyncMock()
    driver._ensure_config_loaded = AsyncMock()
    driver.compatibility_config = None
    driver.get_database_version = AsyncMock(return_value="8.1.0")
    return driver


@pytest.fixture
def mock_compatibility_config():
    """Create a mock GaussDB compatibility configuration."""
    config = GaussDbCompatibilityConfig(
        version="8.1.0",
        supports_hypopg=False,
        supports_pg_stat_statements=True,
        supports_explain_analyze=True
    )
    config.is_feature_supported = MagicMock(return_value=True)
    return config


@pytest.fixture
def feature_checker(mock_gaussdb_driver, mock_compatibility_config):
    """Create a FeatureAvailabilityChecker instance for testing."""
    checker = FeatureAvailabilityChecker(mock_gaussdb_driver)
    checker._compatibility_config = mock_compatibility_config
    checker._error_handler = GaussDbErrorHandler(mock_compatibility_config)
    return checker


@pytest.mark.asyncio
async def test_feature_checker_initialization(mock_gaussdb_driver):
    """Test initialization of FeatureAvailabilityChecker."""
    checker = FeatureAvailabilityChecker(mock_gaussdb_driver)

    assert checker.sql_driver == mock_gaussdb_driver
    assert checker._compatibility_config is None
    assert checker._error_handler is None
    assert len(checker._feature_cache) == 0
    assert len(checker._checked_extensions) == 0


@pytest.mark.asyncio
async def test_ensure_config_loaded(mock_gaussdb_driver, mock_compatibility_config):
    """Test configuration loading."""
    mock_gaussdb_driver.compatibility_config = mock_compatibility_config

    checker = FeatureAvailabilityChecker(mock_gaussdb_driver)
    await checker._ensure_config_loaded()

    assert checker._compatibility_config == mock_compatibility_config
    assert checker._error_handler is not None
    mock_gaussdb_driver._ensure_config_loaded.assert_called_once()


@pytest.mark.asyncio
async def test_check_hypopg_support_not_supported_by_config(feature_checker, mock_compatibility_config):
    """Test hypopg check when not supported by configuration."""
    mock_compatibility_config.supports_hypopg = False

    is_supported, error_msg, alternative = await feature_checker.check_hypopg_support()

    assert is_supported is False
    assert "Hypothetical indexes (hypopg extension) are not supported" in error_msg
    assert "Consider these alternatives" in alternative
    assert feature_checker._feature_cache["hypopg"] is False


@pytest.mark.asyncio
async def test_check_hypopg_support_extension_not_installed(feature_checker, mock_gaussdb_driver, mock_compatibility_config):
    """Test hypopg check when extension is not installed."""
    mock_compatibility_config.supports_hypopg = True  # Config says it's supported

    # Mock extension check returning False
    mock_gaussdb_driver.execute_query.return_value = [
        MockRowResult({"has_hypopg": False})
    ]

    is_supported, error_msg, alternative = await feature_checker.check_hypopg_support()

    assert is_supported is False
    assert "Hypothetical indexes (hypopg extension) are not supported" in error_msg
    assert "Consider these alternatives" in alternative
    assert feature_checker._feature_cache["hypopg"] is False


@pytest.mark.asyncio
async def test_check_hypopg_support_functions_not_working(feature_checker, mock_gaussdb_driver, mock_compatibility_config):
    """Test hypopg check when extension exists but functions don't work."""
    mock_compatibility_config.supports_hypopg = True

    # Mock extension check returning True, but function calls failing
    mock_gaussdb_driver.execute_query.side_effect = [
        [MockRowResult({"has_hypopg": True})],  # Extension exists
        Exception("hypopg_reset() failed"),     # Function call fails
    ]

    is_supported, error_msg, alternative = await feature_checker.check_hypopg_support()

    assert is_supported is False
    assert "Hypothetical indexes (hypopg extension) are not supported" in error_msg
    assert feature_checker._feature_cache["hypopg"] is False


@pytest.mark.asyncio
async def test_check_hypopg_support_fully_working(feature_checker, mock_gaussdb_driver, mock_compatibility_config):
    """Test hypopg check when fully working."""
    mock_compatibility_config.supports_hypopg = True

    # Mock all checks succeeding
    mock_gaussdb_driver.execute_query.side_effect = [
        [MockRowResult({"has_hypopg": True})],  # Extension exists
        [MockRowResult({})],                    # hypopg_reset() works
        [MockRowResult({})],                    # hypopg_create_index() works
        [MockRowResult({})],                    # hypopg_reset() works again
    ]

    is_supported, error_msg, alternative = await feature_checker.check_hypopg_support()

    assert is_supported is True
    assert error_msg is None
    assert alternative is None
    assert feature_checker._feature_cache["hypopg"] is True


@pytest.mark.asyncio
async def test_check_hypopg_support_cached_result(feature_checker):
    """Test that hypopg check uses cached results."""
    # Set cached result
    feature_checker._feature_cache["hypopg"] = True

    is_supported, error_msg, alternative = await feature_checker.check_hypopg_support()

    assert is_supported is True
    assert error_msg is None
    assert alternative is None

    # Verify no database queries were made
    feature_checker.sql_driver.execute_query.assert_not_called()


@pytest.mark.asyncio
async def test_check_pg_stat_statements_support_not_supported_by_config(feature_checker, mock_compatibility_config):
    """Test pg_stat_statements check when not supported by configuration."""
    mock_compatibility_config.supports_pg_stat_statements = False

    is_supported, error_msg, alternative = await feature_checker.check_pg_stat_statements_support()

    assert is_supported is False
    assert "Query statistics (pg_stat_statements or equivalent) are not available" in error_msg
    assert "Consider these alternatives" in alternative


@pytest.mark.asyncio
async def test_check_pg_stat_statements_support_working(feature_checker, mock_gaussdb_driver, mock_compatibility_config):
    """Test pg_stat_statements check when working."""
    mock_compatibility_config.supports_pg_stat_statements = True

    # Mock first query succeeding
    mock_gaussdb_driver.execute_query.return_value = [MockRowResult({"count": 0})]

    is_supported, error_msg, alternative = await feature_checker.check_pg_stat_statements_support()

    assert is_supported is True
    assert error_msg is None
    assert alternative is None
    assert feature_checker._feature_cache["pg_stat_statements"] is True


@pytest.mark.asyncio
async def test_check_pg_stat_statements_support_fallback_views(feature_checker, mock_gaussdb_driver, mock_compatibility_config):
    """Test pg_stat_statements check with fallback to alternative views."""
    mock_compatibility_config.supports_pg_stat_statements = True

    # Mock first two queries failing, third succeeding
    mock_gaussdb_driver.execute_query.side_effect = [
        Exception("pg_stat_statements not found"),
        Exception("pg_stat_user_statements not found"),
        [MockRowResult({"count": 0})],  # dbe_perf.statement works
    ]

    is_supported, error_msg, alternative = await feature_checker.check_pg_stat_statements_support()

    assert is_supported is True
    assert error_msg is None
    assert alternative is None


@pytest.mark.asyncio
async def test_check_explain_analyze_support_working(feature_checker, mock_gaussdb_driver):
    """Test EXPLAIN ANALYZE support check when working."""
    # Mock successful EXPLAIN ANALYZE
    plan_data = {"Plan": {"Node Type": "Result"}}
    mock_gaussdb_driver.execute_query.return_value = [
        MockRowResult({"QUERY PLAN": [plan_data]})
    ]

    is_supported, error_msg, alternative = await feature_checker.check_explain_analyze_support()

    assert is_supported is True
    assert error_msg is None
    assert alternative is None
    assert feature_checker._feature_cache["explain_analyze"] is True


@pytest.mark.asyncio
async def test_check_explain_analyze_support_not_working(feature_checker, mock_gaussdb_driver):
    """Test EXPLAIN ANALYZE support check when not working."""
    # Mock EXPLAIN ANALYZE failing, but basic EXPLAIN working
    mock_gaussdb_driver.execute_query.side_effect = [
        Exception("EXPLAIN ANALYZE not supported"),
        [MockRowResult({"QUERY PLAN": [{"Plan": {"Node Type": "Result"}}]})],  # Basic EXPLAIN works
    ]

    is_supported, error_msg, alternative = await feature_checker.check_explain_analyze_support()

    assert is_supported is False
    assert "EXPLAIN ANALYZE is not supported" in error_msg
    assert "Use EXPLAIN (without ANALYZE)" in alternative
    assert feature_checker._feature_cache["explain_analyze"] is False


@pytest.mark.asyncio
async def test_check_extension_availability_installed(feature_checker, mock_gaussdb_driver):
    """Test extension availability check when extension is installed."""
    mock_gaussdb_driver.execute_query.return_value = [
        MockRowResult({"has_extension": True})
    ]

    is_available, error_msg = await feature_checker.check_extension_availability("pg_trgm")

    assert is_available is True
    assert error_msg is None
    assert feature_checker._checked_extensions["pg_trgm"] is True


@pytest.mark.asyncio
async def test_check_extension_availability_not_installed(feature_checker, mock_gaussdb_driver):
    """Test extension availability check when extension is not installed."""
    mock_gaussdb_driver.execute_query.return_value = [
        MockRowResult({"has_extension": False})
    ]

    is_available, error_msg = await feature_checker.check_extension_availability("pg_trgm")

    assert is_available is False
    assert "Extension 'pg_trgm' is not installed or available" in error_msg
    assert feature_checker._checked_extensions["pg_trgm"] is False


@pytest.mark.asyncio
async def test_check_extension_availability_cached(feature_checker):
    """Test that extension availability check uses cached results."""
    # Set cached result
    feature_checker._checked_extensions["pg_trgm"] = True

    is_available, error_msg = await feature_checker.check_extension_availability("pg_trgm")

    assert is_available is True
    assert error_msg is None

    # Verify no database queries were made
    feature_checker.sql_driver.execute_query.assert_not_called()


@pytest.mark.asyncio
async def test_get_comprehensive_feature_report(feature_checker):
    """Test getting comprehensive feature report."""
    # Mock feature checks
    with patch.object(feature_checker, 'check_hypopg_support',
                     return_value=(False, "Not supported", "Use alternatives")):
        with patch.object(feature_checker, 'check_pg_stat_statements_support',
                         return_value=(True, None, None)):
            with patch.object(feature_checker, 'check_explain_analyze_support',
                             return_value=(True, None, None)):
                with patch.object(feature_checker, 'check_extension_availability',
                                 return_value=(False, "Not available")):

                    report = await feature_checker.get_comprehensive_feature_report()

    assert report["database_info"]["type"] == "gaussdb"
    assert report["database_info"]["version"] == "8.1.0"
    assert "core_features" in report
    assert "extensions" in report
    assert "recommendations" in report

    # Check core features
    assert "hypopg" in report["core_features"]
    assert "pg_stat_statements" in report["core_features"]
    assert "explain_analyze" in report["core_features"]

    # Check that recommendations were added for unsupported features
    assert len(report["recommendations"]) > 0


@pytest.mark.asyncio
async def test_validate_required_features_all_available(feature_checker):
    """Test validation when all required features are available."""
    required_features = ["pg_stat_statements", "explain_analyze"]

    with patch.object(feature_checker, 'check_pg_stat_statements_support',
                     return_value=(True, None, None)):
        with patch.object(feature_checker, 'check_explain_analyze_support',
                         return_value=(True, None, None)):

            all_available, missing = await feature_checker.validate_required_features(required_features)

    assert all_available is True
    assert len(missing) == 0


@pytest.mark.asyncio
async def test_validate_required_features_some_missing(feature_checker):
    """Test validation when some required features are missing."""
    required_features = ["hypopg", "pg_stat_statements"]

    with patch.object(feature_checker, 'check_hypopg_support',
                     return_value=(False, "Not supported", "Use alternatives")):
        with patch.object(feature_checker, 'check_pg_stat_statements_support',
                         return_value=(True, None, None)):

            all_available, missing = await feature_checker.validate_required_features(required_features)

    assert all_available is False
    assert "hypopg" in missing
    assert "pg_stat_statements" not in missing


@pytest.mark.asyncio
async def test_validate_required_features_extension(feature_checker):
    """Test validation of required extensions."""
    required_features = ["pg_trgm"]

    with patch.object(feature_checker, 'check_extension_availability',
                     return_value=(True, None)):

        all_available, missing = await feature_checker.validate_required_features(required_features)

    assert all_available is True
    assert len(missing) == 0


@pytest.mark.asyncio
async def test_clear_cache(feature_checker):
    """Test clearing the feature cache."""
    # Add some cached data
    feature_checker._feature_cache["hypopg"] = False
    feature_checker._checked_extensions["pg_trgm"] = True

    feature_checker.clear_cache()

    assert len(feature_checker._feature_cache) == 0
    assert len(feature_checker._checked_extensions) == 0


@pytest.mark.asyncio
async def test_get_cache_info(feature_checker):
    """Test getting cache information."""
    # Add some cached data
    feature_checker._feature_cache["hypopg"] = False
    feature_checker._checked_extensions["pg_trgm"] = True

    cache_info = feature_checker.get_cache_info()

    assert cache_info["cached_features"] == ["hypopg"]
    assert cache_info["cached_extensions"] == ["pg_trgm"]
    assert cache_info["feature_cache_size"] == 1
    assert cache_info["extension_cache_size"] == 1


@pytest.mark.asyncio
async def test_check_hypopg_installation_status_function(mock_gaussdb_driver):
    """Test the standalone check_hypopg_installation_status function."""
    # Mock successful hypopg check
    with patch.object(FeatureAvailabilityChecker, 'check_hypopg_support',
                     return_value=(True, None, None)):

        status = await check_hypopg_installation_status(mock_gaussdb_driver)

    assert status["installed"] is True
    assert status["available"] is True
    assert status["database_type"] == "gaussdb"
    assert status["status"] == "hypopg extension is available and working"
    assert len(status["functions_available"]) > 0


@pytest.mark.asyncio
async def test_check_hypopg_installation_status_function_not_available(mock_gaussdb_driver):
    """Test the standalone function when hypopg is not available."""
    with patch.object(FeatureAvailabilityChecker, 'check_hypopg_support',
                     return_value=(False, "Not supported", "Use alternatives")):

        status = await check_hypopg_installation_status(mock_gaussdb_driver)

    assert status["installed"] is False
    assert status["available"] is False
    assert status["database_type"] == "gaussdb"
    assert status["status"] == "hypopg extension is not available"
    assert status["error_message"] == "Not supported"
    assert status["suggested_alternative"] == "Use alternatives"
    assert "gaussdb_guidance" in status


@pytest.mark.asyncio
async def test_check_hypopg_installation_status_function_error(mock_gaussdb_driver):
    """Test the standalone function when an error occurs."""
    with patch.object(FeatureAvailabilityChecker, 'check_hypopg_support',
                     side_effect=Exception("Database connection failed")):

        status = await check_hypopg_installation_status(mock_gaussdb_driver)

    assert status["installed"] is False
    assert status["available"] is False
    assert status["database_type"] == "gaussdb"
    assert status["status"] == "error"
    assert "Error checking hypopg status" in status["error_message"]


@pytest.mark.asyncio
async def test_error_messages_and_alternatives(feature_checker, mock_compatibility_config):
    """Test that appropriate error messages and alternatives are provided."""
    mock_compatibility_config.version = "8.1.0"

    # Test hypopg error message
    error_msg = feature_checker._get_hypopg_error_message()
    assert "GaussDB 8.1.0" in error_msg
    assert "Hypothetical indexes" in error_msg

    # Test hypopg alternative
    alternative = feature_checker._get_hypopg_alternative()
    assert "Consider these alternatives" in alternative
    assert "PostgreSQL with hypopg extension" in alternative

    # Test pg_stat_statements error and alternative
    error_msg = feature_checker._get_pg_stat_statements_error()
    assert "Query statistics" in error_msg

    alternative = feature_checker._get_pg_stat_statements_alternative()
    assert "Consider these alternatives" in alternative

    # Test explain_analyze error and alternative
    error_msg = feature_checker._get_explain_analyze_error()
    assert "EXPLAIN ANALYZE is not supported" in error_msg

    alternative = feature_checker._get_explain_analyze_alternative()
    assert "Use EXPLAIN (without ANALYZE)" in alternative
