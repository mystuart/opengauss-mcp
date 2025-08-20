"""
Unit tests for GaussDB SQL driver adapter.

This module contains tests for the GaussDbSqlDriver class and its
query adaptation, error handling, and fallback mechanisms.
"""

from unittest.mock import AsyncMock
from unittest.mock import Mock

import pytest

from postgres_mcp.gaussdb.config import GaussDbCompatibilityConfig
from postgres_mcp.gaussdb.config import QueryAdaptationRule
from postgres_mcp.gaussdb.config_loader import ConfigLoader
from postgres_mcp.gaussdb.error_handler import ErrorCategory
from postgres_mcp.gaussdb.error_handler import GaussDbErrorHandler
from postgres_mcp.gaussdb.sql_driver_adapter import GaussDbSqlDriver
from postgres_mcp.gaussdb.sql_driver_adapter import QueryAdaptationCache
from postgres_mcp.sql.database_detection import DatabaseType
from postgres_mcp.sql.sql_driver import SqlDriver


class TestQueryAdaptationCache:
    """Test cases for QueryAdaptationCache."""

    def test_cache_initialization(self):
        """Test cache initialization with default and custom sizes."""
        cache = QueryAdaptationCache()
        assert cache.max_size == 1000
        assert cache.size() == 0

        cache_custom = QueryAdaptationCache(max_size=500)
        assert cache_custom.max_size == 500
        assert cache_custom.size() == 0

    def test_cache_put_and_get(self):
        """Test basic cache put and get operations."""
        cache = QueryAdaptationCache(max_size=3)

        # Test put and get
        cache.put("SELECT 1", "SELECT 1")
        assert cache.get("SELECT 1") == "SELECT 1"
        assert cache.size() == 1

        # Test cache miss
        assert cache.get("SELECT 2") is None

    def test_cache_lru_eviction(self):
        """Test LRU eviction when cache is full."""
        cache = QueryAdaptationCache(max_size=2)

        # Fill cache
        cache.put("query1", "adapted1")
        cache.put("query2", "adapted2")
        assert cache.size() == 2

        # Access first query to make it more recent
        cache.get("query1")

        # Add third query, should evict query2
        cache.put("query3", "adapted3")
        assert cache.size() == 2
        assert cache.get("query1") == "adapted1"  # Still there
        assert cache.get("query2") is None        # Evicted
        assert cache.get("query3") == "adapted3"  # New entry

    def test_cache_clear(self):
        """Test cache clearing."""
        cache = QueryAdaptationCache()
        cache.put("query1", "adapted1")
        cache.put("query2", "adapted2")
        assert cache.size() == 2

        cache.clear()
        assert cache.size() == 0
        assert cache.get("query1") is None


class TestGaussDbSqlDriver:
    """Test cases for GaussDbSqlDriver."""

    @pytest.fixture
    def mock_base_driver(self):
        """Create a mock base SqlDriver."""
        driver = Mock(spec=SqlDriver)
        driver.get_database_version = AsyncMock(return_value="8.1.0")
        driver.get_database_type = AsyncMock(return_value=DatabaseType.GAUSSDB)
        driver.is_gaussdb = AsyncMock(return_value=True)
        driver.is_postgresql = AsyncMock(return_value=False)
        driver.execute_query = AsyncMock(return_value=[])
        driver.connect = Mock()
        driver.initialize_database_info = AsyncMock()
        return driver

    @pytest.fixture
    def mock_config_loader(self):
        """Create a mock ConfigLoader."""
        loader = Mock(spec=ConfigLoader)
        config = GaussDbCompatibilityConfig(version="8.1.0")
        config.query_adaptations = [
            QueryAdaptationRule(
                name="test_rule",
                description="Test adaptation rule",
                pattern=r"SELECT\s+version\(\)",
                replacement="SELECT version()",
                priority=1
            )
        ]
        loader.load_config_for_version = Mock(return_value=config)
        return loader

    @pytest.fixture
    def gaussdb_driver(self, mock_base_driver, mock_config_loader):
        """Create a GaussDbSqlDriver instance with mocks."""
        return GaussDbSqlDriver(mock_base_driver, mock_config_loader)

    @pytest.mark.asyncio
    async def test_initialization(self, gaussdb_driver, mock_base_driver, mock_config_loader):
        """Test driver initialization."""
        assert gaussdb_driver.base_driver == mock_base_driver
        assert gaussdb_driver.config_loader == mock_config_loader
        assert gaussdb_driver._compatibility_config is None
        assert gaussdb_driver._error_handler is None
        assert not gaussdb_driver._fallback_mode

    @pytest.mark.asyncio
    async def test_ensure_config_loaded(self, gaussdb_driver, mock_base_driver, mock_config_loader):
        """Test configuration loading."""
        await gaussdb_driver._ensure_config_loaded()

        mock_base_driver.get_database_version.assert_called_once()
        mock_config_loader.load_config_for_version.assert_called_once_with("8.1.0")
        assert gaussdb_driver._compatibility_config is not None
        assert gaussdb_driver._error_handler is not None

    @pytest.mark.asyncio
    async def test_adapt_query_simple(self, gaussdb_driver):
        """Test simple query adaptation."""
        # Ensure config is loaded
        await gaussdb_driver._ensure_config_loaded()

        original_query = "SELECT version()"
        adapted_query = await gaussdb_driver.adapt_query(original_query)

        # Should apply the test rule
        assert adapted_query == "SELECT version()"

    @pytest.mark.asyncio
    async def test_adapt_query_caching(self, gaussdb_driver):
        """Test query adaptation caching."""
        await gaussdb_driver._ensure_config_loaded()

        query = "SELECT 1"

        # First call should process and cache
        result1 = await gaussdb_driver.adapt_query(query)
        assert gaussdb_driver._query_cache.size() == 1

        # Second call should use cache
        result2 = await gaussdb_driver.adapt_query(query)
        assert result1 == result2
        assert gaussdb_driver._query_cache.size() == 1

    @pytest.mark.asyncio
    async def test_execute_query_success(self, gaussdb_driver, mock_base_driver):
        """Test successful query execution."""
        mock_results = [SqlDriver.RowResult(cells={"test": 1})]
        mock_base_driver.execute_query.return_value = mock_results

        result = await gaussdb_driver.execute_query("SELECT 1")

        assert result == mock_results
        mock_base_driver.execute_query.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_query_with_fallback(self, gaussdb_driver, mock_base_driver):
        """Test query execution with fallback on error."""
        # First call fails, second succeeds
        mock_base_driver.execute_query.side_effect = [
            Exception("Column does not exist"),
            [SqlDriver.RowResult(cells={"test": 1})]
        ]

        result = await gaussdb_driver.execute_query("SELECT invalid_column")

        # Should have called execute_query twice (adapted, then fallback)
        assert mock_base_driver.execute_query.call_count == 2
        assert result == [SqlDriver.RowResult(cells={"test": 1})]

    @pytest.mark.asyncio
    async def test_fallback_mode(self, gaussdb_driver):
        """Test fallback mode functionality."""
        assert not gaussdb_driver.is_fallback_mode()

        gaussdb_driver.enable_fallback_mode()
        assert gaussdb_driver.is_fallback_mode()

        gaussdb_driver.disable_fallback_mode()
        assert not gaussdb_driver.is_fallback_mode()

    @pytest.mark.asyncio
    async def test_validate_connection_success(self, gaussdb_driver, mock_base_driver):
        """Test successful connection validation."""
        mock_base_driver.execute_query.return_value = [SqlDriver.RowResult(cells={"test": 1})]

        is_valid, error_msg = await gaussdb_driver.validate_connection()

        assert is_valid is True
        assert error_msg is None

    @pytest.mark.asyncio
    async def test_validate_connection_failure(self, gaussdb_driver, mock_base_driver):
        """Test connection validation failure."""
        mock_base_driver.execute_query.side_effect = Exception("Connection failed")

        is_valid, error_msg = await gaussdb_driver.validate_connection()

        assert is_valid is False
        assert "Connection validation failed" in error_msg

    @pytest.mark.asyncio
    async def test_feature_support_info(self, gaussdb_driver):
        """Test getting feature support information."""
        await gaussdb_driver._ensure_config_loaded()

        info = await gaussdb_driver.get_feature_support_info()

        assert "version" in info
        assert "features" in info
        assert "hypopg" in info["features"]
        assert "pg_stat_statements" in info["features"]

    def test_cache_management(self, gaussdb_driver):
        """Test query cache management."""
        # Test cache stats
        stats = gaussdb_driver.get_cache_stats()
        assert "cache_size" in stats
        assert "max_size" in stats

        # Test cache clearing
        gaussdb_driver.clear_query_cache()
        assert gaussdb_driver.get_cache_stats()["cache_size"] == 0

    def test_retry_configuration(self, gaussdb_driver):
        """Test retry configuration."""
        assert gaussdb_driver.get_max_retries() == 3

        gaussdb_driver.set_max_retries(5)
        assert gaussdb_driver.get_max_retries() == 5

        gaussdb_driver.set_max_retries(-1)  # Should be clamped to 0
        assert gaussdb_driver.get_max_retries() == 0

    @pytest.mark.asyncio
    async def test_delegation_to_base_driver(self, gaussdb_driver, mock_base_driver):
        """Test that unknown attributes are delegated to base driver."""
        # Test attribute delegation
        mock_base_driver.some_attribute = "test_value"
        assert gaussdb_driver.some_attribute == "test_value"

        # Test method delegation
        mock_base_driver.some_method = Mock(return_value="method_result")
        result = gaussdb_driver.some_method()
        assert result == "method_result"
        mock_base_driver.some_method.assert_called_once()


class TestErrorHandling:
    """Test cases for error handling functionality."""

    @pytest.fixture
    def error_handler(self):
        """Create a GaussDbErrorHandler instance."""
        config = GaussDbCompatibilityConfig(version="8.1.0")
        return GaussDbErrorHandler(config)

    def test_error_categorization(self, error_handler):
        """Test error categorization."""
        # Connection error
        conn_error = Exception("connection refused")
        message, category, action = error_handler.handle_error(conn_error)
        assert category == ErrorCategory.CONNECTION
        assert "connect to GaussDB server" in message

        # Feature not supported error
        feature_error = Exception("function does not exist")
        message, category, action = error_handler.handle_error(feature_error)
        assert category == ErrorCategory.FEATURE_NOT_SUPPORTED
        assert "not available" in message

    def test_retryable_error_detection(self, error_handler):
        """Test detection of retryable errors."""
        retryable_error = Exception("connection refused")
        assert error_handler.is_retryable_error(retryable_error)

        non_retryable_error = Exception("syntax error")
        assert not error_handler.is_retryable_error(non_retryable_error)

    def test_fallback_recommendation(self, error_handler):
        """Test fallback recommendation logic."""
        fallback_error = Exception("column does not exist")
        assert error_handler.should_fallback_to_postgresql(fallback_error)

        no_fallback_error = Exception("permission denied")
        assert not error_handler.should_fallback_to_postgresql(no_fallback_error)

    def test_custom_error_mappings(self, error_handler):
        """Test custom error mappings."""
        error_handler.add_custom_error_mapping("custom_error", "Custom message")

        custom_error = Exception("custom_error occurred")
        message, category, action = error_handler.handle_error(custom_error)
        assert message == "Custom message"
        assert category == ErrorCategory.FEATURE_NOT_SUPPORTED

    def test_feature_alternatives(self, error_handler):
        """Test feature alternative suggestions."""
        alternative = error_handler.get_feature_alternative("hypopg")
        assert alternative is not None
        assert "EXPLAIN ANALYZE" in alternative

        no_alternative = error_handler.get_feature_alternative("unknown_feature")
        assert no_alternative is None

    def test_error_formatting(self, error_handler):
        """Test error message formatting for users."""
        error = Exception("connection refused")
        formatted = error_handler.format_error_for_user(error)

        assert "Error:" in formatted
        assert "Category:" in formatted
        assert "Suggestions:" in formatted


if __name__ == "__main__":
    pytest.main([__file__])
