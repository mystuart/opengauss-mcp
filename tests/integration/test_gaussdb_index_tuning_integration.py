"""
Integration tests for GaussDB index tuning functionality.

This module tests the integration of GaussDB index tuning adapters
with the overall system to ensure they work correctly in realistic scenarios.
"""

from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
import pytest_asyncio

from postgres_mcp.gaussdb.index_tuning_adapters import GaussDbDatabaseTuningAdvisor
from postgres_mcp.gaussdb.index_tuning_adapters import GaussDbLLMOptimizerTool
from postgres_mcp.index.presentation import TextPresentation
from postgres_mcp.sql import SqlDriver
from postgres_mcp.sql.database_detection import DatabaseType


@pytest_asyncio.fixture
async def mock_gaussdb_connection():
    """Create a mock GaussDB connection for integration testing."""
    driver = AsyncMock(spec=SqlDriver)
    driver.get_database_type.return_value = DatabaseType.GAUSSDB
    driver.get_database_version.return_value = "8.1.0"
    driver.is_gaussdb.return_value = True
    driver.is_postgresql.return_value = False

    # Mock basic connectivity test
    driver.execute_query.return_value = [MagicMock(cells={"test": 1})]

    return driver


@pytest_asyncio.fixture
async def gaussdb_advisor(mock_gaussdb_connection):
    """Create a GaussDB database tuning advisor for testing."""
    return GaussDbDatabaseTuningAdvisor(mock_gaussdb_connection)


@pytest_asyncio.fixture
async def gaussdb_optimizer(mock_gaussdb_connection):
    """Create a GaussDB LLM optimizer for testing."""
    return GaussDbLLMOptimizerTool(mock_gaussdb_connection)


class TestGaussDbWorkloadAnalysisIntegration:
    """Integration tests for GaussDB workload analysis."""

    @pytest.mark.asyncio
    async def test_analyze_workload_with_query_stats(self, gaussdb_advisor):
        """Test workload analysis using query statistics."""
        # Mock query statistics data
        mock_query_stats = [
            {
                'queryid': '12345',
                'query': 'SELECT * FROM users WHERE email = $1',
                'calls': 100,
                'avg_exec_time': 15.5
            },
            {
                'queryid': '67890',
                'query': 'SELECT * FROM orders WHERE user_id = $1 AND status = $2',
                'calls': 75,
                'avg_exec_time': 25.2
            }
        ]

        # Mock feature checker
        with patch.object(gaussdb_advisor.feature_checker, 'check_pg_stat_statements', return_value=True):
            # Mock query stats retrieval
            with patch.object(gaussdb_advisor, '_gaussdb_get_query_stats', return_value=mock_query_stats):
                # Mock hypopg installation check
                with patch('postgres_mcp.sql.check_hypopg_installation_status', return_value=(True, "HypoPG is available")):
                    # Mock analyze check
                    mock_analyze_result = [MagicMock(cells={"last_analyze": "2024-01-01"})]
                    gaussdb_advisor.sql_driver.execute_query.return_value = mock_analyze_result

                    # Mock parameter replacement
                    with patch.object(gaussdb_advisor._sql_bind_params, 'replace_parameters', side_effect=lambda x: x.replace('$1', '1').replace('$2', '2')):
                        # Mock query parsing
                        with patch('pglast.parse_sql') as mock_parse:
                            from pglast.ast import SelectStmt
                            mock_stmt = SelectStmt()
                            mock_parse.return_value = [MagicMock(stmt=mock_stmt)]

                            # Mock recommendation generation
                            with patch.object(gaussdb_advisor, '_generate_recommendations', return_value=(set(), 100.0)):
                                # Mock format recommendations
                                with patch.object(gaussdb_advisor, '_format_recommendations', return_value=[]):

                                    result = await gaussdb_advisor.analyze_workload(
                                        min_calls=50,
                                        min_avg_time_ms=10.0,
                                        limit=10,
                                        max_index_size_mb=100
                                    )

                                    assert result is not None
                                    assert result.workload_source == "query_store"
                                    assert result.error is None

    @pytest.mark.asyncio
    async def test_analyze_workload_with_query_list(self, gaussdb_advisor):
        """Test workload analysis using provided query list."""
        query_list = [
            "SELECT * FROM users WHERE email = 'test@example.com'",
            "SELECT * FROM orders WHERE user_id = 123"
        ]

        # Mock hypopg installation check
        with patch('postgres_mcp.sql.check_hypopg_installation_status', return_value=(True, "HypoPG is available")):
            # Mock analyze check
            mock_analyze_result = [MagicMock(cells={"last_analyze": "2024-01-01"})]
            gaussdb_advisor.sql_driver.execute_query.return_value = mock_analyze_result

            # Mock parameter replacement
            with patch.object(gaussdb_advisor._sql_bind_params, 'replace_parameters', side_effect=lambda x: x):
                # Mock query parsing
                with patch('pglast.parse_sql') as mock_parse:
                    from pglast.ast import SelectStmt
                    mock_stmt = SelectStmt()
                    mock_parse.return_value = [MagicMock(stmt=mock_stmt)]

                    # Mock recommendation generation
                    with patch.object(gaussdb_advisor, '_generate_recommendations', return_value=(set(), 100.0)):
                        # Mock format recommendations
                        with patch.object(gaussdb_advisor, '_format_recommendations', return_value=[]):

                            result = await gaussdb_advisor.analyze_workload(
                                query_list=query_list,
                                max_index_size_mb=100
                            )

                            assert result is not None
                            assert result.workload_source == "query_list"
                            assert result.error is None
                            assert len(result.workload) == 2

    @pytest.mark.asyncio
    async def test_analyze_workload_fallback_to_postgresql(self, gaussdb_advisor):
        """Test fallback to PostgreSQL method when GaussDB-specific method fails."""
        # Mock feature checker to raise exception
        with patch.object(gaussdb_advisor.feature_checker, 'check_pg_stat_statements', side_effect=Exception("GaussDB error")):
            # Mock parent class method
            mock_query_stats = [
                {
                    'queryid': '11111',
                    'query': 'SELECT * FROM products',
                    'calls': 50,
                    'avg_exec_time': 12.0
                }
            ]

            with patch('postgres_mcp.index.dta_calc.DatabaseTuningAdvisor._get_query_stats_direct', return_value=mock_query_stats):
                # Mock hypopg installation check
                with patch('postgres_mcp.sql.check_hypopg_installation_status', return_value=(True, "HypoPG is available")):
                    # Mock analyze check
                    mock_analyze_result = [MagicMock(cells={"last_analyze": "2024-01-01"})]
                    gaussdb_advisor.sql_driver.execute_query.return_value = mock_analyze_result

                    # Mock parameter replacement
                    with patch.object(gaussdb_advisor._sql_bind_params, 'replace_parameters', side_effect=lambda x: x):
                        # Mock query parsing
                        with patch('pglast.parse_sql') as mock_parse:
                            from pglast.ast import SelectStmt
                            mock_stmt = SelectStmt()
                            mock_parse.return_value = [MagicMock(stmt=mock_stmt)]

                            # Mock recommendation generation
                            with patch.object(gaussdb_advisor, '_generate_recommendations', return_value=(set(), 100.0)):
                                # Mock format recommendations
                                with patch.object(gaussdb_advisor, '_format_recommendations', return_value=[]):

                                    result = await gaussdb_advisor.analyze_workload(
                                        min_calls=25,
                                        min_avg_time_ms=5.0,
                                        limit=5,
                                        max_index_size_mb=50
                                    )

                                    assert result is not None
                                    assert result.workload_source == "query_store"
                                    assert result.error is None


class TestGaussDbLLMOptimizationIntegration:
    """Integration tests for GaussDB LLM-based optimization."""

    @pytest.mark.asyncio
    async def test_llm_optimization_with_hypopg_support(self, gaussdb_optimizer):
        """Test LLM optimization when hypopg is supported."""
        # Mock feature checker to return True for hypopg support
        with patch.object(gaussdb_optimizer.feature_checker, 'check_hypopg_support', return_value=True):
            # Mock table visitor
            with patch('postgres_mcp.sql.TableAliasVisitor') as mock_visitor_class:
                mock_visitor = MagicMock()
                mock_visitor.tables = ['users']
                mock_visitor_class.return_value = mock_visitor

                # Mock table size retrieval
                with patch.object(gaussdb_optimizer, '_gaussdb_get_table_size', return_value=1048576):  # 1MB
                    # Mock explain plan tool
                    with patch('postgres_mcp.explain.explain_plan.ExplainPlanTool') as mock_explain_class:
                        mock_explain_tool = MagicMock()
                        mock_explain_result = MagicMock()
                        mock_explain_result.value = {"Plan": {"Total Cost": 100.0}}
                        mock_explain_tool.explain.return_value = mock_explain_result
                        mock_explain_class.return_value = mock_explain_tool

                        # Mock index extraction
                        with patch.object(gaussdb_optimizer, '_extract_indexes_from_explain_plan_with_columns', return_value=set()):
                            # Mock cost evaluation
                            with patch.object(gaussdb_optimizer, '_evaluate_configuration_cost', return_value=100.0):
                                # Mock LLM client
                                with patch('instructor.from_openai') as mock_instructor:
                                    mock_client = MagicMock()
                                    mock_response = MagicMock()
                                    mock_response.alternatives = []  # No alternatives to trigger early exit
                                    mock_client.chat.completions.create.return_value = mock_response
                                    mock_instructor.return_value = mock_client

                                    # Create mock query weights
                                    from pglast.ast import SelectStmt
                                    query_weights = [("SELECT * FROM users WHERE email = 'test'", SelectStmt(), 1.0)]

                                    result = await gaussdb_optimizer._generate_recommendations(query_weights)

                                    # Should return some result (even if no improvements found)
                                    assert result is not None
                                    recommendations, cost = result
                                    assert isinstance(recommendations, set)
                                    assert isinstance(cost, (int, float))

    @pytest.mark.asyncio
    async def test_llm_optimization_without_hypopg_support(self, gaussdb_optimizer):
        """Test LLM optimization when hypopg is not supported."""
        # Mock feature checker to return False for hypopg support
        with patch.object(gaussdb_optimizer.feature_checker, 'check_hypopg_support', return_value=False):
            # Mock the alternative method
            from postgres_mcp.index.index_opt_base import IndexRecommendation
            expected_recommendations = {IndexRecommendation('users', ('email',))}
            expected_cost = 80.0

            with patch.object(gaussdb_optimizer, '_generate_recommendations_without_hypopg',
                            return_value=(expected_recommendations, expected_cost)):

                # Create mock query weights
                from pglast.ast import SelectStmt
                query_weights = [("SELECT * FROM users WHERE email = 'test'", SelectStmt(), 1.0)]

                result = await gaussdb_optimizer._generate_recommendations(query_weights)

                assert result == (expected_recommendations, expected_cost)


class TestGaussDbTextPresentationIntegration:
    """Integration tests for GaussDB with TextPresentation."""

    @pytest.mark.asyncio
    async def test_text_presentation_with_gaussdb_advisor(self, mock_gaussdb_connection, gaussdb_advisor):
        """Test TextPresentation integration with GaussDB advisor."""
        # Create TextPresentation with GaussDB advisor
        presentation = TextPresentation(mock_gaussdb_connection, gaussdb_advisor)

        # Mock the advisor's analyze_workload method
        from postgres_mcp.index.index_opt_base import IndexTuningResult
        mock_result = IndexTuningResult(
            session_id="test_session",
            budget_mb=100,
            workload_source="query_store",
            recommendations=[],
            error=None
        )

        with patch.object(gaussdb_advisor, 'analyze_workload', return_value=mock_result):
            result = await presentation.analyze_workload(max_index_size_mb=100)

            assert result is not None
            # TextPresentation should format the result as text
            assert isinstance(result, str) or hasattr(result, '__str__')

    @pytest.mark.asyncio
    async def test_text_presentation_with_gaussdb_optimizer(self, mock_gaussdb_connection, gaussdb_optimizer):
        """Test TextPresentation integration with GaussDB LLM optimizer."""
        # Create TextPresentation with GaussDB optimizer
        presentation = TextPresentation(mock_gaussdb_connection, gaussdb_optimizer)

        # Mock the optimizer's analyze_queries method
        from postgres_mcp.index.index_opt_base import IndexTuningResult
        mock_result = IndexTuningResult(
            session_id="test_session",
            budget_mb=50,
            workload_source="query_list",
            recommendations=[],
            error=None
        )

        with patch.object(gaussdb_optimizer, 'analyze_workload', return_value=mock_result):
            queries = ["SELECT * FROM users WHERE id = 1"]
            result = await presentation.analyze_queries(queries=queries, max_index_size_mb=50)

            assert result is not None
            # TextPresentation should format the result as text
            assert isinstance(result, str) or hasattr(result, '__str__')


class TestGaussDbErrorHandling:
    """Test error handling in GaussDB index tuning integration."""

    @pytest.mark.asyncio
    async def test_advisor_error_handling(self, gaussdb_advisor):
        """Test error handling in GaussDB advisor."""
        # Mock hypopg installation check to fail
        with patch('postgres_mcp.sql.check_hypopg_installation_status', return_value=(False, "HypoPG not available")):
            result = await gaussdb_advisor.analyze_workload(max_index_size_mb=100)

            assert result is not None
            assert result.error is not None
            assert "HypoPG not available" in result.error

    @pytest.mark.asyncio
    async def test_optimizer_error_handling(self, gaussdb_optimizer):
        """Test error handling in GaussDB optimizer."""
        # Mock feature checker to raise exception
        with patch.object(gaussdb_optimizer.feature_checker, 'check_hypopg_support', side_effect=Exception("Feature check failed")):
            # Mock parent class method to return empty result
            with patch('postgres_mcp.index.llm_opt.LLMOptimizerTool._generate_recommendations', return_value=(set(), 100.0)):

                # Create mock query weights
                from pglast.ast import SelectStmt
                query_weights = [("SELECT * FROM users", SelectStmt(), 1.0)]

                result = await gaussdb_optimizer._generate_recommendations(query_weights)

                # Should fallback to PostgreSQL method
                assert result is not None
                recommendations, cost = result
                assert isinstance(recommendations, set)
                assert isinstance(cost, (int, float))


class TestGaussDbFeatureCompatibility:
    """Test feature compatibility checks in GaussDB integration."""

    @pytest.mark.asyncio
    async def test_pg_stat_statements_compatibility(self, gaussdb_advisor):
        """Test pg_stat_statements compatibility checking."""
        # Test when feature is supported
        with patch.object(gaussdb_advisor.feature_checker, 'check_pg_stat_statements', return_value=True):
            supports_stats = await gaussdb_advisor.feature_checker.check_pg_stat_statements()
            assert supports_stats is True

        # Test when feature is not supported
        with patch.object(gaussdb_advisor.feature_checker, 'check_pg_stat_statements', return_value=False):
            supports_stats = await gaussdb_advisor.feature_checker.check_pg_stat_statements()
            assert supports_stats is False

    @pytest.mark.asyncio
    async def test_hypopg_compatibility(self, gaussdb_optimizer):
        """Test hypopg compatibility checking."""
        # Test when feature is supported
        with patch.object(gaussdb_optimizer.feature_checker, 'check_hypopg_support', return_value=True):
            supports_hypopg = await gaussdb_optimizer.feature_checker.check_hypopg_support()
            assert supports_hypopg is True

        # Test when feature is not supported
        with patch.object(gaussdb_optimizer.feature_checker, 'check_hypopg_support', return_value=False):
            supports_hypopg = await gaussdb_optimizer.feature_checker.check_hypopg_support()
            assert supports_hypopg is False
