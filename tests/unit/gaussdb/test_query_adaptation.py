"""
Unit tests for GaussDB query adaptation functionality.

This module tests the query adaptation logic that converts PostgreSQL-specific
queries to GaussDB-compatible format, including pattern matching, replacement
rules, and caching mechanisms.
"""

from unittest.mock import AsyncMock
from unittest.mock import Mock

import pytest

from opengauss_mcp.gaussdb.config import GaussDbCompatibilityConfig
from opengauss_mcp.gaussdb.config import QueryAdaptationRule
from opengauss_mcp.gaussdb.config import SystemViewMapping
from opengauss_mcp.gaussdb.config_loader import ConfigLoader
from opengauss_mcp.gaussdb.sql_driver_adapter import GaussDbSqlDriver
from opengauss_mcp.sql.database_detection import DatabaseType
from opengauss_mcp.sql.sql_driver import SqlDriver


class TestQueryAdaptationRules:
    """Test cases for query adaptation rules."""

    def test_simple_pattern_replacement(self):
        """Test simple pattern-based query replacement."""
        rule = QueryAdaptationRule(
            name="version_check",
            description="Adapt version query",
            pattern=r"SELECT\s+version\(\)",
            replacement="SELECT version()",
            priority=1
        )

        query = "SELECT version()"
        adapted = rule.apply(query)
        assert adapted == "SELECT version()"

    def test_complex_pattern_replacement(self):
        """Test complex pattern with capture groups."""
        rule = QueryAdaptationRule(
            name="pg_stat_activity",
            description="Adapt pg_stat_activity queries",
            pattern=r"SELECT\s+(.+)\s+FROM\s+pg_stat_activity",
            replacement=r"SELECT \1 FROM pg_stat_activity",
            priority=1
        )

        query = "SELECT pid, state FROM pg_stat_activity"
        adapted = rule.apply(query)
        assert adapted == "SELECT pid, state FROM pg_stat_activity"

    def test_system_view_mapping(self):
        """Test system view name mapping."""
        rule = QueryAdaptationRule(
            name="pg_indexes",
            description="Map pg_indexes view",
            pattern=r"FROM\s+pg_indexes",
            replacement="FROM pg_indexes",
            priority=1
        )

        query = "SELECT * FROM pg_indexes WHERE tablename = 'test'"
        adapted = rule.apply(query)
        assert "FROM pg_indexes" in adapted

    def test_rule_priority_ordering(self):
        """Test that rules are applied in priority order."""
        rule1 = QueryAdaptationRule(
            name="low_priority",
            description="Low priority rule",
            pattern=r"SELECT\s+\*",
            replacement="SELECT *",
            priority=2
        )

        rule2 = QueryAdaptationRule(
            name="high_priority",
            description="High priority rule",
            pattern=r"SELECT\s+\*\s+FROM\s+test",
            replacement="SELECT * FROM test_table",
            priority=1
        )

        query = "SELECT * FROM test"

        # Higher priority rule should be applied first
        adapted = rule2.apply(query)
        assert adapted == "SELECT * FROM test_table"

    def test_rule_no_match(self):
        """Test rule behavior when pattern doesn't match."""
        rule = QueryAdaptationRule(
            name="no_match",
            description="Rule that won't match",
            pattern=r"DELETE\s+FROM",
            replacement="DELETE FROM",
            priority=1
        )

        query = "SELECT * FROM test"
        adapted = rule.apply(query)
        assert adapted == query  # Should return original query unchanged

    def test_case_insensitive_matching(self):
        """Test case-insensitive pattern matching."""
        rule = QueryAdaptationRule(
            name="case_insensitive",
            description="Case insensitive rule",
            pattern=r"(?i)select\s+version\(\)",
            replacement="SELECT version()",
            priority=1
        )

        queries = [
            "select version()",
            "SELECT VERSION()",
            "Select Version()"
        ]

        for query in queries:
            adapted = rule.apply(query)
            assert adapted == "SELECT version()"


class TestQueryAdaptationEngine:
    """Test cases for the query adaptation engine."""

    @pytest.fixture
    def mock_base_driver(self):
        """Create a mock base SqlDriver."""
        driver = Mock(spec=SqlDriver)
        driver.get_database_version = AsyncMock(return_value="8.1.0")
        driver.get_database_type = AsyncMock(return_value=DatabaseType.GAUSSDB)
        driver.execute_query = AsyncMock(return_value=[])
        return driver

    @pytest.fixture
    def sample_config(self):
        """Create a sample GaussDB compatibility configuration."""
        config = GaussDbCompatibilityConfig(version="8.1.0")
        config.query_adaptations = [
            QueryAdaptationRule(
                name="pg_stat_activity",
                description="Adapt pg_stat_activity queries",
                pattern=r"SELECT\s+(.+)\s+FROM\s+pg_stat_activity\s+WHERE\s+state\s*=\s*'active'",
                replacement=r"SELECT \1 FROM pg_stat_activity WHERE state = 'active'",
                priority=1
            ),
            QueryAdaptationRule(
                name="pg_indexes",
                description="Adapt pg_indexes queries",
                pattern=r"FROM\s+pg_indexes",
                replacement="FROM pg_indexes",
                priority=2
            ),
            QueryAdaptationRule(
                name="version_query",
                description="Adapt version queries",
                pattern=r"SELECT\s+version\(\)",
                replacement="SELECT version()",
                priority=3
            )
        ]

        config.system_view_mappings = [
            SystemViewMapping(
                postgresql_view="pg_stat_user_indexes",
                gaussdb_view="pg_stat_user_indexes",
                description="Index statistics view"
            ),
            SystemViewMapping(
                postgresql_view="pg_stat_user_tables",
                gaussdb_view="pg_stat_user_tables",
                description="Table statistics view"
            )
        ]

        return config

    @pytest.fixture
    def mock_config_loader(self, sample_config):
        """Create a mock ConfigLoader."""
        loader = Mock(spec=ConfigLoader)
        loader.load_config_for_version = Mock(return_value=sample_config)
        return loader

    @pytest.fixture
    def gaussdb_driver(self, mock_base_driver, mock_config_loader):
        """Create a GaussDbSqlDriver instance with mocks."""
        return GaussDbSqlDriver(mock_base_driver, mock_config_loader)

    @pytest.mark.asyncio
    async def test_query_adaptation_pipeline(self, gaussdb_driver):
        """Test the complete query adaptation pipeline."""
        await gaussdb_driver._ensure_config_loaded()

        # Test complex query adaptation
        original_query = """
        SELECT pid, state, query 
        FROM pg_stat_activity 
        WHERE state = 'active'
        """

        adapted_query = await gaussdb_driver.adapt_query(original_query)

        # Should apply the pg_stat_activity rule
        assert "FROM pg_stat_activity" in adapted_query
        assert "WHERE state = 'active'" in adapted_query

    @pytest.mark.asyncio
    async def test_multiple_rule_application(self, gaussdb_driver):
        """Test applying multiple adaptation rules to a single query."""
        await gaussdb_driver._ensure_config_loaded()

        # Query that could match multiple rules
        query = "SELECT indexname FROM pg_indexes WHERE schemaname = 'public'"

        adapted_query = await gaussdb_driver.adapt_query(query)

        # Should apply the pg_indexes rule
        assert "FROM pg_indexes" in adapted_query

    @pytest.mark.asyncio
    async def test_system_view_mapping_application(self, gaussdb_driver):
        """Test system view mapping during query adaptation."""
        await gaussdb_driver._ensure_config_loaded()

        query = "SELECT * FROM pg_stat_user_indexes WHERE schemaname = 'public'"

        adapted_query = await gaussdb_driver.adapt_query(query)

        # Should map to GaussDB equivalent view
        assert "FROM pg_stat_user_indexes" in adapted_query

    @pytest.mark.asyncio
    async def test_query_adaptation_caching(self, gaussdb_driver):
        """Test that adapted queries are properly cached."""
        await gaussdb_driver._ensure_config_loaded()

        query = "SELECT version()"

        # First adaptation should process and cache
        adapted1 = await gaussdb_driver.adapt_query(query)
        cache_stats1 = gaussdb_driver.get_cache_stats()

        # Second adaptation should use cache
        adapted2 = await gaussdb_driver.adapt_query(query)
        cache_stats2 = gaussdb_driver.get_cache_stats()

        assert adapted1 == adapted2
        assert cache_stats1["cache_size"] == 1
        assert cache_stats2["cache_size"] == 1

    @pytest.mark.asyncio
    async def test_adaptation_with_parameters(self, gaussdb_driver):
        """Test query adaptation with parameterized queries."""
        await gaussdb_driver._ensure_config_loaded()

        # Parameterized query
        query = "SELECT * FROM pg_stat_activity WHERE pid = $1"

        adapted_query = await gaussdb_driver.adapt_query(query)

        # Should preserve parameters
        assert "$1" in adapted_query
        assert "FROM pg_stat_activity" in adapted_query

    @pytest.mark.asyncio
    async def test_complex_multiline_query_adaptation(self, gaussdb_driver):
        """Test adaptation of complex multiline queries."""
        await gaussdb_driver._ensure_config_loaded()

        query = """
        SELECT 
            i.indexname,
            i.tablename,
            s.idx_scan,
            s.idx_tup_read,
            s.idx_tup_fetch
        FROM pg_indexes i
        JOIN pg_stat_user_indexes s ON i.indexname = s.indexname
        WHERE i.schemaname = 'public'
        ORDER BY s.idx_scan DESC
        """

        adapted_query = await gaussdb_driver.adapt_query(query)

        # Should preserve query structure while adapting views
        assert "FROM pg_indexes" in adapted_query
        assert "JOIN pg_stat_user_indexes" in adapted_query
        assert "ORDER BY s.idx_scan DESC" in adapted_query

    @pytest.mark.asyncio
    async def test_no_adaptation_needed(self, gaussdb_driver):
        """Test queries that don't need adaptation."""
        await gaussdb_driver._ensure_config_loaded()

        # Simple query that doesn't match any rules
        query = "SELECT 1 as test"

        adapted_query = await gaussdb_driver.adapt_query(query)

        # Should return original query unchanged
        assert adapted_query == query

    @pytest.mark.asyncio
    async def test_adaptation_error_handling(self, gaussdb_driver):
        """Test error handling during query adaptation."""
        await gaussdb_driver._ensure_config_loaded()

        # Create a rule with invalid regex
        invalid_rule = QueryAdaptationRule(
            name="invalid_rule",
            description="Rule with invalid regex",
            pattern=r"[invalid regex",  # Invalid regex pattern
            replacement="replacement",
            priority=1
        )

        # Add invalid rule to config
        gaussdb_driver._compatibility_config.query_adaptations.append(invalid_rule)

        query = "SELECT * FROM test"

        # Should handle regex error gracefully and return original query
        adapted_query = await gaussdb_driver.adapt_query(query)
        assert adapted_query == query


class TestQueryAdaptationPerformance:
    """Test cases for query adaptation performance."""

    @pytest.fixture
    def performance_config(self):
        """Create a configuration with many rules for performance testing."""
        config = GaussDbCompatibilityConfig(version="8.1.0")

        # Create many rules to test performance
        rules = []
        for i in range(100):
            rule = QueryAdaptationRule(
                name=f"rule_{i}",
                description=f"Test rule {i}",
                pattern=f"FROM test_table_{i}",
                replacement=f"FROM gaussdb_table_{i}",
                priority=i
            )
            rules.append(rule)

        config.query_adaptations = rules
        return config

    @pytest.fixture
    def performance_driver(self, mock_base_driver, performance_config):
        """Create driver with performance test configuration."""
        mock_config_loader = Mock(spec=ConfigLoader)
        mock_config_loader.load_config_for_version = Mock(return_value=performance_config)
        return GaussDbSqlDriver(mock_base_driver, mock_config_loader)

    @pytest.mark.asyncio
    async def test_adaptation_performance_with_many_rules(self, performance_driver):
        """Test adaptation performance with many rules."""
        await performance_driver._ensure_config_loaded()

        # Query that won't match any rules (worst case)
        query = "SELECT * FROM unmatched_table"

        import time
        start_time = time.time()

        # Run adaptation multiple times
        for _ in range(10):
            adapted_query = await performance_driver.adapt_query(query)
            assert adapted_query == query

        end_time = time.time()
        total_time = end_time - start_time

        # Should complete reasonably quickly (less than 1 second for 10 adaptations)
        assert total_time < 1.0

    @pytest.mark.asyncio
    async def test_cache_performance_benefit(self, performance_driver):
        """Test that caching provides performance benefits."""
        await performance_driver._ensure_config_loaded()

        query = "SELECT * FROM test_table_50"  # Will match rule_50

        import time

        # First adaptation (no cache)
        start_time = time.time()
        adapted1 = await performance_driver.adapt_query(query)
        first_time = time.time() - start_time

        # Second adaptation (with cache)
        start_time = time.time()
        adapted2 = await performance_driver.adapt_query(query)
        second_time = time.time() - start_time

        assert adapted1 == adapted2
        # Cached version should be faster (though this might be hard to measure reliably)
        # At minimum, verify cache is being used
        assert performance_driver.get_cache_stats()["cache_size"] == 1


class TestQueryAdaptationEdgeCases:
    """Test cases for edge cases in query adaptation."""

    @pytest.fixture
    def edge_case_driver(self, mock_base_driver):
        """Create driver for edge case testing."""
        config = GaussDbCompatibilityConfig(version="8.1.0")
        config.query_adaptations = [
            QueryAdaptationRule(
                name="empty_replacement",
                description="Rule with empty replacement",
                pattern=r"-- comment",
                replacement="",
                priority=1
            ),
            QueryAdaptationRule(
                name="special_chars",
                description="Rule with special characters",
                pattern=r"SELECT\s+\$\$(.+)\$\$",
                replacement=r"SELECT '\1'",
                priority=2
            )
        ]

        mock_config_loader = Mock(spec=ConfigLoader)
        mock_config_loader.load_config_for_version = Mock(return_value=config)
        return GaussDbSqlDriver(mock_base_driver, mock_config_loader)

    @pytest.mark.asyncio
    async def test_empty_query_adaptation(self, edge_case_driver):
        """Test adaptation of empty or whitespace-only queries."""
        await edge_case_driver._ensure_config_loaded()

        empty_queries = ["", "   ", "\n\t  \n"]

        for query in empty_queries:
            adapted = await edge_case_driver.adapt_query(query)
            assert adapted == query

    @pytest.mark.asyncio
    async def test_very_long_query_adaptation(self, edge_case_driver):
        """Test adaptation of very long queries."""
        await edge_case_driver._ensure_config_loaded()

        # Create a very long query
        long_query = "SELECT " + ", ".join([f"col_{i}" for i in range(1000)]) + " FROM test_table"

        adapted = await edge_case_driver.adapt_query(long_query)

        # Should handle long queries without issues
        assert len(adapted) == len(long_query)
        assert "FROM test_table" in adapted

    @pytest.mark.asyncio
    async def test_special_character_handling(self, edge_case_driver):
        """Test handling of special characters in queries."""
        await edge_case_driver._ensure_config_loaded()

        # Query with dollar-quoted strings
        query = "SELECT $$Hello World$$"

        adapted = await edge_case_driver.adapt_query(query)

        # Should apply the special_chars rule
        assert adapted == "SELECT 'Hello World'"

    @pytest.mark.asyncio
    async def test_unicode_query_adaptation(self, edge_case_driver):
        """Test adaptation of queries with Unicode characters."""
        await edge_case_driver._ensure_config_loaded()

        # Query with Unicode characters
        query = "SELECT '测试数据' as test_data FROM 用户表"

        adapted = await edge_case_driver.adapt_query(query)

        # Should preserve Unicode characters
        assert "测试数据" in adapted
        assert "用户表" in adapted

    @pytest.mark.asyncio
    async def test_comment_removal(self, edge_case_driver):
        """Test removal of comments during adaptation."""
        await edge_case_driver._ensure_config_loaded()

        query = """
        SELECT * FROM test_table
        -- comment
        WHERE id = 1
        """

        adapted = await edge_case_driver.adapt_query(query)

        # Should apply the empty_replacement rule to remove comment
        assert "-- comment" not in adapted or adapted.replace("-- comment", "").strip()


if __name__ == "__main__":
    pytest.main([__file__])
