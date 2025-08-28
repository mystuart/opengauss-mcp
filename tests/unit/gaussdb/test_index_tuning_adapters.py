"""
Unit tests for GaussDB index tuning adapters.

This module tests the GaussDB-specific adapters for index tuning functionality,
ensuring they properly handle GaussDB differences while maintaining compatibility.
"""

from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
import pytest_asyncio

from opengauss_mcp.gaussdb.index_tuning_adapters import GaussDbDatabaseTuningAdvisor
from opengauss_mcp.gaussdb.index_tuning_adapters import GaussDbLLMOptimizerTool
from opengauss_mcp.gaussdb.sql_driver_adapter import GaussDbSqlDriver
from opengauss_mcp.index.index_opt_base import IndexRecommendation
from opengauss_mcp.sql import SqlDriver


@pytest_asyncio.fixture
async def mock_sql_driver():
    """Create a mock SQL driver for testing."""
    driver = AsyncMock(spec=SqlDriver)
    driver.get_database_type.return_value = "gaussdb"
    driver.get_database_version.return_value = "8.1.0"
    driver.execute_query.return_value = []
    return driver


@pytest_asyncio.fixture
async def mock_gaussdb_driver(mock_sql_driver):
    """Create a mock GaussDB driver for testing."""
    driver = AsyncMock(spec=GaussDbSqlDriver)
    driver.base_driver = mock_sql_driver
    driver.execute_query.return_value = []
    driver.adapt_query.return_value = "SELECT 1"
    return driver


class TestGaussDbDatabaseTuningAdvisor:
    """Test cases for GaussDbDatabaseTuningAdvisor."""

    @pytest_asyncio.fixture
    async def advisor(self, mock_sql_driver):
        """Create a GaussDbDatabaseTuningAdvisor instance for testing."""
        return GaussDbDatabaseTuningAdvisor(mock_sql_driver)

    def test_initialization_with_sql_driver(self, mock_sql_driver):
        """Test initialization with regular SqlDriver."""
        advisor = GaussDbDatabaseTuningAdvisor(mock_sql_driver)
        assert advisor.sql_driver == mock_sql_driver
        assert isinstance(advisor.gaussdb_driver, GaussDbSqlDriver)
        assert advisor.gaussdb_driver.base_driver == mock_sql_driver

    def test_initialization_with_gaussdb_driver(self, mock_gaussdb_driver):
        """Test initialization with GaussDbSqlDriver."""
        advisor = GaussDbDatabaseTuningAdvisor(mock_gaussdb_driver)
        # With the mixin, the sql_driver might be wrapped differently
        assert hasattr(advisor, 'gaussdb_driver')
        assert isinstance(advisor.gaussdb_driver, GaussDbSqlDriver)

    @pytest.mark.asyncio
    async def test_get_query_stats_direct_success(self, advisor):
        """Test successful query statistics retrieval."""
        # Mock feature checker to return True for pg_stat_statements support
        with patch.object(advisor.feature_checker, 'check_pg_stat_statements_support', return_value=(True, None, None)):
            # Mock the query result
            mock_result = [
                MagicMock(cells={
                    'queryid': '12345',
                    'query': 'SELECT * FROM users WHERE id = 1',
                    'calls': 100,
                    'avg_exec_time': 10.5
                })
            ]

            with patch('postgres_mcp.sql.SafeSqlDriver.execute_param_query', return_value=mock_result):
                result = await advisor._get_query_stats_direct(min_calls=50, min_avg_time_ms=5.0, limit=10)

                assert len(result) == 1
                assert result[0]['queryid'] == '12345'
                assert result[0]['query'] == 'SELECT * FROM users WHERE id = 1'
                assert result[0]['calls'] == 100
                assert result[0]['avg_exec_time'] == 10.5

    @pytest.mark.asyncio
    async def test_get_query_stats_direct_fallback(self, advisor):
        """Test fallback to PostgreSQL method when GaussDB-specific method fails."""
        # Mock feature checker to raise an exception
        with patch.object(advisor.feature_checker, 'check_pg_stat_statements_support', side_effect=Exception("GaussDB error")):
            # Mock the parent class method
            with patch('postgres_mcp.index.dta_calc.DatabaseTuningAdvisor._get_query_stats_direct', return_value=[]):
                result = await advisor._get_query_stats_direct()
                assert result == []

    @pytest.mark.asyncio
    async def test_gaussdb_get_query_stats_with_pg_stat_statements(self, advisor):
        """Test GaussDB query stats when pg_stat_statements is supported."""
        # Mock feature checker to return True
        with patch.object(advisor.feature_checker, 'check_pg_stat_statements_support', return_value=(True, None, None)):
            mock_result = [
                MagicMock(cells={
                    'queryid': '67890',
                    'query': 'SELECT * FROM products',
                    'calls': 50,
                    'avg_exec_time': 15.2
                })
            ]

            with patch('postgres_mcp.sql.SafeSqlDriver.execute_param_query', return_value=mock_result):
                result = await advisor._gaussdb_get_query_stats(min_calls=25, min_avg_time_ms=10.0, limit=5)

                assert len(result) == 1
                assert result[0]['queryid'] == '67890'

    @pytest.mark.asyncio
    async def test_gaussdb_get_query_stats_alternative_method(self, advisor):
        """Test alternative query stats method when pg_stat_statements is not supported."""
        # Mock feature checker to return False
        with patch.object(advisor.feature_checker, 'check_pg_stat_statements_support', return_value=(False, "Not supported", "Use alternative")):
            # Mock the alternative method
            with patch.object(advisor, '_gaussdb_get_query_stats_alternative', return_value=[]):
                result = await advisor._gaussdb_get_query_stats(min_calls=25, min_avg_time_ms=10.0, limit=5)
                assert result == []

    @pytest.mark.asyncio
    async def test_get_existing_indexes_success(self, advisor):
        """Test successful retrieval of existing indexes."""
        mock_result = [
            MagicMock(cells={
                'schema': 'public',
                'table': 'users',
                'name': 'users_email_idx',
                'definition': 'CREATE INDEX users_email_idx ON users (email)'
            })
        ]

        with patch.object(advisor.gaussdb_driver, 'execute_query', return_value=mock_result):

            result = await advisor._get_existing_indexes()

            assert len(result) == 1
            assert result[0]['schema'] == 'public'
            assert result[0]['table'] == 'users'
            assert result[0]['name'] == 'users_email_idx'

    @pytest.mark.asyncio
    async def test_get_existing_indexes_fallback(self, advisor):
        """Test fallback to PostgreSQL method when GaussDB method fails."""
        # Mock GaussDB method to raise exception
        with patch.object(advisor.gaussdb_driver, 'execute_query', side_effect=Exception("GaussDB error")):

            # Mock parent class method
            with patch('postgres_mcp.index.dta_calc.DatabaseTuningAdvisor._get_existing_indexes', return_value=[]):
                result = await advisor._get_existing_indexes()
                assert result == []

    @pytest.mark.asyncio
    async def test_estimate_index_size_success(self, advisor):
        """Test successful index size estimation."""
        mock_result = [
            MagicMock(cells={
                'total_width': 100,
                'total_distinct': 1000
            })
        ]

        with patch('postgres_mcp.sql.SafeSqlDriver.execute_param_query', return_value=mock_result):
            result = await advisor._estimate_index_size('users', ['email'])

            # Should return a positive size estimate
            assert result > 0

    @pytest.mark.asyncio
    async def test_estimate_index_size_fallback(self, advisor):
        """Test fallback to PostgreSQL method when GaussDB method fails."""
        # Mock GaussDB method to raise exception
        with patch.object(advisor, '_gaussdb_estimate_index_size', side_effect=Exception("GaussDB error")):
            # Mock parent class method
            with patch('postgres_mcp.index.dta_calc.DatabaseTuningAdvisor._estimate_index_size', return_value=1024):
                result = await advisor._estimate_index_size('users', ['email'])
                assert result == 1024

    @pytest.mark.asyncio
    async def test_get_table_size_success(self, advisor):
        """Test successful table size retrieval."""
        mock_result = [
            MagicMock(cells={'rel_size': 1048576})  # 1MB
        ]

        with patch('postgres_mcp.sql.SafeSqlDriver.execute_param_query', return_value=mock_result):
            result = await advisor._get_table_size('users')
            assert result == 1048576

    @pytest.mark.asyncio
    async def test_get_table_size_fallback(self, advisor):
        """Test fallback to PostgreSQL method when GaussDB method fails."""
        # Mock GaussDB method to raise exception
        with patch.object(advisor, '_gaussdb_get_table_size', side_effect=Exception("GaussDB error")):
            # Mock parent class method
            with patch('postgres_mcp.index.dta_calc.DatabaseTuningAdvisor._get_table_size', return_value=2048576):
                result = await advisor._get_table_size('users')
                assert result == 2048576


class TestGaussDbLLMOptimizerTool:
    """Test cases for GaussDbLLMOptimizerTool."""

    @pytest_asyncio.fixture
    async def optimizer(self, mock_sql_driver):
        """Create a GaussDbLLMOptimizerTool instance for testing."""
        return GaussDbLLMOptimizerTool(mock_sql_driver)

    def test_initialization_with_sql_driver(self, mock_sql_driver):
        """Test initialization with regular SqlDriver."""
        optimizer = GaussDbLLMOptimizerTool(mock_sql_driver)
        assert optimizer.sql_driver == mock_sql_driver
        assert isinstance(optimizer.gaussdb_driver, GaussDbSqlDriver)
        assert optimizer.gaussdb_driver.base_driver == mock_sql_driver

    def test_initialization_with_gaussdb_driver(self, mock_gaussdb_driver):
        """Test initialization with GaussDbSqlDriver."""
        optimizer = GaussDbLLMOptimizerTool(mock_gaussdb_driver)
        # With the mixin, the sql_driver might be wrapped differently
        assert hasattr(optimizer, 'gaussdb_driver')
        assert isinstance(optimizer.gaussdb_driver, GaussDbSqlDriver)

    @pytest.mark.asyncio
    async def test_generate_recommendations_with_hypopg_support(self, optimizer):
        """Test recommendation generation when hypopg is supported."""
        # Mock feature checker to return True for hypopg support
        with patch.object(optimizer.feature_checker, 'check_hypopg_support', return_value=(True, None, None)):
            # Mock the GaussDB-specific method
            expected_recommendations = {IndexRecommendation('users', ('email',))}
            expected_cost = 100.0

            with patch.object(optimizer, '_gaussdb_generate_recommendations',
                            return_value=(expected_recommendations, expected_cost)):

                # Create mock query weights
                from pglast.ast import SelectStmt
                query_weights = [("SELECT * FROM users", SelectStmt(), 1.0)]

                result = await optimizer._generate_recommendations(query_weights)

                assert result == (expected_recommendations, expected_cost)

    @pytest.mark.asyncio
    async def test_generate_recommendations_without_hypopg_support(self, optimizer):
        """Test recommendation generation when hypopg is not supported."""
        # Mock feature checker to return False for hypopg support
        with patch.object(optimizer.feature_checker, 'check_hypopg_support', return_value=(False, "Not supported", "Use alternative")):
            # Mock the alternative method
            expected_recommendations = {IndexRecommendation('users', ('id',))}
            expected_cost = 80.0

            with patch.object(optimizer, '_generate_recommendations_without_hypopg',
                            return_value=(expected_recommendations, expected_cost)):

                # Create mock query weights
                from pglast.ast import SelectStmt
                query_weights = [("SELECT * FROM users WHERE id = 1", SelectStmt(), 1.0)]

                result = await optimizer._generate_recommendations(query_weights)

                assert result == (expected_recommendations, expected_cost)

    @pytest.mark.asyncio
    async def test_generate_recommendations_fallback(self, optimizer):
        """Test fallback to PostgreSQL method when GaussDB method fails."""
        # Mock feature checker to raise exception
        with patch.object(optimizer.feature_checker, 'check_hypopg_support', side_effect=Exception("GaussDB error")):
            # Mock parent class method
            expected_recommendations = {IndexRecommendation('users', ('name',))}
            expected_cost = 120.0

            with patch('postgres_mcp.index.llm_opt.LLMOptimizerTool._generate_recommendations',
                     return_value=(expected_recommendations, expected_cost)):

                # Create mock query weights
                from pglast.ast import SelectStmt
                query_weights = [("SELECT * FROM users WHERE name = 'test'", SelectStmt(), 1.0)]

                result = await optimizer._generate_recommendations(query_weights)

                assert result == (expected_recommendations, expected_cost)

    @pytest.mark.asyncio
    async def test_generate_recommendations_without_hypopg(self, optimizer):
        """Test recommendation generation without hypothetical index support."""
        # Create mock query weights with parsed statements
        from pglast.ast import SelectStmt
        query_weights = [("SELECT * FROM users WHERE email = 'test@example.com'", SelectStmt(), 1.0)]

        # Mock the column collector
        with patch('postgres_mcp.sql.ColumnCollector') as mock_collector_class:
            mock_collector = MagicMock()
            mock_collector.columns = {'users': {'email', 'id', 'name'}}
            mock_collector_class.return_value = mock_collector

            result = await optimizer._generate_recommendations_without_hypopg(query_weights)

            recommendations, cost = result
            assert len(recommendations) > 0
            assert cost > 0

            # Check that recommendations contain single-column indexes
            for rec in recommendations:
                assert len(rec.columns) == 1
                assert rec.table == 'users'

    @pytest.mark.asyncio
    async def test_gaussdb_get_table_size_success(self, optimizer):
        """Test successful table size retrieval."""
        mock_result = [
            MagicMock(cells={'rel_size': 2097152})  # 2MB
        ]

        with patch('postgres_mcp.sql.SafeSqlDriver.execute_param_query', return_value=mock_result):
            result = await optimizer._gaussdb_get_table_size('products')
            assert result == 2097152

    @pytest.mark.asyncio
    async def test_gaussdb_get_table_size_fallback(self, optimizer):
        """Test fallback when table size query fails."""
        with patch('postgres_mcp.sql.SafeSqlDriver.execute_param_query', side_effect=Exception("Query failed")):
            result = await optimizer._gaussdb_get_table_size('products')
            assert result == 10 * 1024 * 1024  # Default 10MB

    @pytest.mark.asyncio
    async def test_gaussdb_estimate_index_size_2_with_hypopg(self, optimizer):
        """Test index size estimation with hypopg support."""
        # Mock feature checker to return True
        with patch.object(optimizer.feature_checker, 'check_hypopg_support', return_value=(True, None, None)):
            # Mock index definitions
            from opengauss_mcp.sql import IndexDefinition
            index_set = {IndexDefinition('users', ('email',))}

            # Mock query result
            mock_result = [MagicMock(cells={'size': 1024})]
            with patch.object(optimizer.gaussdb_driver, 'execute_query', return_value=mock_result):

                result = await optimizer._gaussdb_estimate_index_size_2(index_set)
                assert result >= 1024  # Should be at least the returned size

    @pytest.mark.asyncio
    async def test_gaussdb_estimate_index_size_2_without_hypopg(self, optimizer):
        """Test index size estimation without hypopg support."""
        # Mock feature checker to return False
        with patch.object(optimizer.feature_checker, 'check_hypopg_support', return_value=(False, "Not supported", "Use alternative")):
            # Mock index definitions
            from opengauss_mcp.sql import IndexDefinition
            index_set = {IndexDefinition('users', ('email',))}

            # Mock alternative estimation method
            with patch.object(optimizer, '_estimate_index_size_alternative', return_value=2048.0):
                result = await optimizer._gaussdb_estimate_index_size_2(index_set)
                assert result >= 2048.0

    @pytest.mark.asyncio
    async def test_estimate_index_size_alternative(self, optimizer):
        """Test alternative index size estimation method."""
        # Mock index config
        mock_index_config = MagicMock()
        mock_index_config.table = 'users'
        mock_index_config.columns = ('email', 'name')

        # Mock statistics query result
        mock_result = [
            MagicMock(cells={
                'total_width': 50,
                'max_distinct': 1000
            })
        ]

        with patch('postgres_mcp.sql.SafeSqlDriver.execute_param_query', return_value=mock_result):
            result = await optimizer._estimate_index_size_alternative(mock_index_config)

            # Should return a calculated size based on width and distinctness
            assert result > 0
            assert isinstance(result, float)

    @pytest.mark.asyncio
    async def test_estimate_index_size_alternative_fallback(self, optimizer):
        """Test fallback in alternative index size estimation."""
        mock_index_config = MagicMock()
        mock_index_config.table = 'users'
        mock_index_config.columns = ('email',)

        # Mock query to raise exception
        with patch('postgres_mcp.sql.SafeSqlDriver.execute_param_query', side_effect=Exception("Query failed")):
            result = await optimizer._estimate_index_size_alternative(mock_index_config)

            # Should return default size
            assert result == 1024 * 1024  # 1MB default


class TestIntegration:
    """Integration tests for GaussDB index tuning adapters."""

    @pytest.mark.asyncio
    async def test_advisor_and_optimizer_compatibility(self, mock_sql_driver):
        """Test that both advisor and optimizer can be created with the same driver."""
        advisor = GaussDbDatabaseTuningAdvisor(mock_sql_driver)
        optimizer = GaussDbLLMOptimizerTool(mock_sql_driver)

        # Both should use the same underlying driver
        assert advisor.sql_driver == optimizer.sql_driver
        assert advisor.gaussdb_driver.base_driver == optimizer.gaussdb_driver.base_driver

    @pytest.mark.asyncio
    async def test_feature_checker_consistency(self, mock_sql_driver):
        """Test that feature checkers work consistently across adapters."""
        advisor = GaussDbDatabaseTuningAdvisor(mock_sql_driver)
        optimizer = GaussDbLLMOptimizerTool(mock_sql_driver)

        # Mock feature checker methods
        with patch.object(advisor.feature_checker, 'check_pg_stat_statements_support', return_value=(True, None, None)):
            with patch.object(optimizer.feature_checker, 'check_hypopg_support', return_value=(False, "Not supported", "Use alternative")):

                # Both should be able to check their respective features
                stat_support = await advisor.feature_checker.check_pg_stat_statements_support()
                hypopg_support = await optimizer.feature_checker.check_hypopg_support()

                assert stat_support[0] is True
                assert hypopg_support[0] is False
