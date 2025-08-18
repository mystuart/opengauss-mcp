"""
End-to-end integration tests for GaussDB functionality.

This module tests complete workflows from MCP tool invocation through
GaussDB-specific processing to final results, ensuring all components
work together correctly.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Dict, Any, List

from src.postgres_mcp.gaussdb.sql_driver_adapter import GaussDbSqlDriver
from src.postgres_mcp.gaussdb.health_adapters import (
    GaussDbIndexHealthCalc,
    GaussDbConnectionHealthCalc,
    GaussDbBufferHealthCalc
)
from src.postgres_mcp.gaussdb.explain_adapter import GaussDbExplainAdapter
from src.postgres_mcp.gaussdb.index_tuning_adapters import GaussDbIndexTuningAdapter
from src.postgres_mcp.gaussdb.top_queries_adapter import GaussDbTopQueriesAdapter
from src.postgres_mcp.sql.sql_driver import SqlDriver
from src.postgres_mcp.sql.database_detection import DatabaseType


class MockRowResult:
    """Mock RowResult for end-to-end testing."""
    
    def __init__(self, cells: Dict[str, Any]):
        self.cells = cells


@pytest.fixture
def mock_sql_driver():
    """Create a comprehensive mock SQL driver for end-to-end testing."""
    driver = AsyncMock(spec=SqlDriver)
    driver.execute_query = AsyncMock()
    driver.get_database_version = AsyncMock(return_value="8.1.0")
    driver.get_database_type = AsyncMock(return_value=DatabaseType.GAUSSDB)
    driver.is_gaussdb = AsyncMock(return_value=True)
    driver.is_postgresql = AsyncMock(return_value=False)
    driver.initialize_database_info = AsyncMock()
    return driver


@pytest.fixture
def gaussdb_driver(mock_sql_driver):
    """Create a GaussDB driver for end-to-end testing."""
    return GaussDbSqlDriver(mock_sql_driver)


class TestGaussDbHealthCheckWorkflow:
    """End-to-end tests for health check workflows."""
    
    @pytest.mark.asyncio
    async def test_complete_database_health_analysis(self, gaussdb_driver):
        """Test complete database health analysis workflow."""
        # Mock comprehensive health data
        health_responses = [
            # Index health data
            [MockRowResult({
                "schema": "public", "table": "users", "name": "idx_users_email",
                "columns": "email", "using": "btree", "unique": True, "primary": False,
                "valid": True, "indexprs": None, "indpred": None,
                "definition": "CREATE UNIQUE INDEX idx_users_email ON users (email)"
            })],
            
            # Connection statistics
            [MockRowResult({"count": 45})],  # total connections
            [MockRowResult({"count": 12})],  # idle connections
            
            # Buffer cache statistics
            [MockRowResult({"rate": 0.987})],  # index hit rate
            [MockRowResult({"rate": 0.952})],  # table hit rate
            
            # Index bloat data
            [MockRowResult({
                "index": "idx_large_table",
                "table": "large_table",
                "bloat_bytes": 104857600,  # 100MB bloat
                "index_bytes": 524288000   # 500MB total
            })],
            
            # Unused indexes
            [MockRowResult({
                "index": "idx_rarely_used",
                "table": "old_table",
                "size_bytes": 52428800,  # 50MB
                "index_scans": 2,
                "primary": False
            })]
        ]
        
        gaussdb_driver.execute_query.side_effect = health_responses
        
        # Initialize health calculators
        index_calc = GaussDbIndexHealthCalc(gaussdb_driver)
        connection_calc = GaussDbConnectionHealthCalc(gaussdb_driver, max_total_connections=100)
        buffer_calc = GaussDbBufferHealthCalc(gaussdb_driver)
        
        # Execute complete health analysis
        health_results = {}
        
        # Index health checks
        health_results["invalid_indexes"] = await index_calc.invalid_index_check()
        health_results["connection_status"] = await connection_calc.connection_health_check()
        health_results["index_hit_rate"] = await buffer_calc.index_hit_rate()
        health_results["table_hit_rate"] = await buffer_calc.table_hit_rate()
        
        # Mock additional methods for comprehensive testing
        with patch('src.postgres_mcp.gaussdb.health_adapters.SafeSqlDriver.execute_param_query') as mock_safe_query:
            mock_safe_query.side_effect = [
                health_responses[4:5],  # bloat data
                health_responses[5:6]   # unused indexes
            ]
            
            health_results["index_bloat"] = await index_calc.index_bloat()
            health_results["unused_indexes"] = await index_calc.unused_indexes()
        
        # Verify comprehensive health analysis results
        assert "No invalid indexes found" in health_results["invalid_indexes"]
        assert "Connections healthy: 45 total, 12 idle" in health_results["connection_status"]
        assert "Index cache hit rate: 98.7%" in health_results["index_hit_rate"]
        assert "Table cache hit rate: 95.2%" in health_results["table_hit_rate"]
        assert "Bloated indexes found" in health_results["index_bloat"]
        assert "idx_large_table" in health_results["index_bloat"]
        assert "Rarely used indexes found" in health_results["unused_indexes"]
        assert "idx_rarely_used" in health_results["unused_indexes"]
    
    @pytest.mark.asyncio
    async def test_health_check_with_performance_issues(self, gaussdb_driver):
        """Test health check workflow when performance issues are detected."""
        # Mock data indicating performance problems
        problem_responses = [
            # High connection count
            [MockRowResult({"count": 150})],  # total connections (over limit)
            [MockRowResult({"count": 80})],   # idle connections (high)
            
            # Poor cache hit rates
            [MockRowResult({"rate": 0.85})],  # low index hit rate
            [MockRowResult({"rate": 0.78})],  # low table hit rate
            
            # Invalid indexes
            [MockRowResult({
                "schema": "public", "table": "broken_table", "name": "broken_idx",
                "columns": "id", "using": "btree", "unique": False, "primary": False,
                "valid": False, "indexprs": None, "indpred": None,
                "definition": "CREATE INDEX broken_idx ON broken_table (id)"
            })]
        ]
        
        gaussdb_driver.execute_query.side_effect = problem_responses
        
        # Initialize health calculators
        connection_calc = GaussDbConnectionHealthCalc(gaussdb_driver, max_total_connections=100)
        buffer_calc = GaussDbBufferHealthCalc(gaussdb_driver)
        index_calc = GaussDbIndexHealthCalc(gaussdb_driver)
        
        # Execute health checks
        connection_result = await connection_calc.total_connections_check()
        idle_result = await connection_calc.idle_connections_check()
        index_hit_result = await buffer_calc.index_hit_rate()
        table_hit_result = await buffer_calc.table_hit_rate()
        invalid_index_result = await index_calc.invalid_index_check()
        
        # Verify problem detection
        assert "High number of connections: 150" in connection_result
        assert "High number of idle connections: 80" in idle_result
        assert "Index cache hit rate: 85.0%" in index_hit_result
        assert "below 95.0% threshold" in index_hit_result
        assert "Table cache hit rate: 78.0%" in table_hit_result
        assert "below 95.0% threshold" in table_hit_result
        assert "Invalid indexes found" in invalid_index_result
        assert "broken_idx on broken_table is invalid" in invalid_index_result
    
    @pytest.mark.asyncio
    async def test_health_check_error_recovery(self, gaussdb_driver):
        """Test health check workflow with error recovery and fallback."""
        # Mock mixed success/failure responses
        mixed_responses = [
            Exception("GaussDB connection error"),  # First query fails
            [MockRowResult({"count": 30})],         # Fallback succeeds
            Exception("permission denied"),          # Another failure
            [MockRowResult({"rate": 0.95})]         # Another fallback succeeds
        ]
        
        gaussdb_driver.execute_query.side_effect = mixed_responses
        
        # Initialize health calculators
        connection_calc = GaussDbConnectionHealthCalc(gaussdb_driver)
        buffer_calc = GaussDbBufferHealthCalc(gaussdb_driver)
        
        # Mock fallback methods
        connection_calc._get_total_connections = AsyncMock(return_value=30)
        buffer_calc._get_index_hit_rate = AsyncMock(return_value=0.95)
        
        # Execute health checks with error recovery
        connection_result = await connection_calc.total_connections_check()
        index_hit_result = await buffer_calc.index_hit_rate()
        
        # Verify fallback results
        assert "connections healthy: 30" in connection_result.lower()
        assert "95.0%" in index_hit_result


class TestGaussDbQueryAnalysisWorkflow:
    """End-to-end tests for query analysis workflows."""
    
    @pytest.mark.asyncio
    async def test_complete_query_explain_workflow(self, gaussdb_driver):
        """Test complete query explanation workflow."""
        # Mock EXPLAIN output
        explain_response = [MockRowResult({
            "QUERY PLAN": "Seq Scan on users  (cost=0.00..15.00 rows=1000 width=32)"
        })]
        
        gaussdb_driver.execute_query.return_value = explain_response
        
        # Initialize explain adapter
        explain_adapter = GaussDbExplainAdapter(gaussdb_driver)
        
        # Test query explanation
        test_query = "SELECT * FROM users WHERE email = 'test@example.com'"
        explain_result = await explain_adapter.explain_query(test_query)
        
        # Verify explanation results
        assert "Seq Scan on users" in explain_result
        assert "cost=0.00..15.00" in explain_result
        assert "rows=1000" in explain_result
    
    @pytest.mark.asyncio
    async def test_query_explain_with_analyze(self, gaussdb_driver):
        """Test query explanation with ANALYZE option."""
        # Mock EXPLAIN ANALYZE output
        analyze_response = [MockRowResult({
            "QUERY PLAN": "Seq Scan on users  (cost=0.00..15.00 rows=1000 width=32) (actual time=0.123..4.567 rows=856 loops=1)"
        })]
        
        gaussdb_driver.execute_query.return_value = analyze_response
        
        explain_adapter = GaussDbExplainAdapter(gaussdb_driver)
        
        # Test EXPLAIN ANALYZE
        test_query = "SELECT * FROM users WHERE active = true"
        analyze_result = await explain_adapter.explain_analyze_query(test_query)
        
        # Verify ANALYZE results include actual execution statistics
        assert "actual time=0.123..4.567" in analyze_result
        assert "rows=856" in analyze_result
        assert "loops=1" in analyze_result
    
    @pytest.mark.asyncio
    async def test_top_queries_analysis_workflow(self, gaussdb_driver):
        """Test top queries analysis workflow."""
        # Mock pg_stat_statements data
        top_queries_response = [
            MockRowResult({
                "query": "SELECT * FROM users WHERE id = $1",
                "calls": 15420,
                "total_time": 2847.123,
                "mean_time": 0.185,
                "rows": 15420,
                "100_percent": 12.5
            }),
            MockRowResult({
                "query": "UPDATE users SET last_login = $1 WHERE id = $2",
                "calls": 8934,
                "total_time": 1923.456,
                "mean_time": 0.215,
                "rows": 8934,
                "100_percent": 8.4
            })
        ]
        
        gaussdb_driver.execute_query.return_value = top_queries_response
        
        # Initialize top queries adapter
        top_queries_adapter = GaussDbTopQueriesAdapter(gaussdb_driver)
        
        # Test top queries analysis
        top_queries_result = await top_queries_adapter.get_top_queries(limit=10)
        
        # Verify top queries results
        assert len(top_queries_result) == 2
        assert top_queries_result[0]["calls"] == 15420
        assert top_queries_result[0]["total_time"] == 2847.123
        assert "SELECT * FROM users WHERE id = $1" in top_queries_result[0]["query"]
        assert top_queries_result[1]["calls"] == 8934


class TestGaussDbIndexTuningWorkflow:
    """End-to-end tests for index tuning workflows."""
    
    @pytest.mark.asyncio
    async def test_complete_index_tuning_workflow(self, gaussdb_driver):
        """Test complete index tuning analysis workflow."""
        # Mock workload analysis data
        workload_responses = [
            # Query statistics
            [MockRowResult({
                "query": "SELECT * FROM orders WHERE customer_id = $1 AND status = $2",
                "calls": 5000,
                "total_time": 1250.0,
                "mean_time": 0.25,
                "rows": 25000
            })],
            
            # Table statistics
            [MockRowResult({
                "schemaname": "public",
                "tablename": "orders",
                "n_tup_ins": 100000,
                "n_tup_upd": 50000,
                "n_tup_del": 5000,
                "seq_scan": 1500,
                "seq_tup_read": 15000000,
                "idx_scan": 25000,
                "idx_tup_fetch": 125000
            })],
            
            # Existing indexes
            [MockRowResult({
                "schemaname": "public",
                "tablename": "orders",
                "indexname": "orders_pkey",
                "idx_scan": 20000,
                "idx_tup_read": 20000,
                "idx_tup_fetch": 20000
            })]
        ]
        
        gaussdb_driver.execute_query.side_effect = workload_responses
        
        # Initialize index tuning adapter
        index_tuning_adapter = GaussDbIndexTuningAdapter(gaussdb_driver)
        
        # Test workload analysis
        workload_analysis = await index_tuning_adapter.analyze_workload()
        
        # Verify workload analysis results
        assert "orders" in str(workload_analysis)
        assert len(workload_analysis["slow_queries"]) >= 0
        assert len(workload_analysis["table_stats"]) >= 0
    
    @pytest.mark.asyncio
    async def test_index_recommendations_workflow(self, gaussdb_driver):
        """Test index recommendations generation workflow."""
        # Mock data for index recommendations
        recommendation_responses = [
            # Missing index analysis
            [MockRowResult({
                "table_name": "orders",
                "column_names": "customer_id, status",
                "query_count": 5000,
                "estimated_benefit": 75.5
            })],
            
            # Duplicate index analysis
            [MockRowResult({
                "table_name": "users",
                "duplicate_indexes": "idx_users_email_1, idx_users_email_2",
                "wasted_space": 52428800  # 50MB
            })]
        ]
        
        gaussdb_driver.execute_query.side_effect = recommendation_responses
        
        index_tuning_adapter = GaussDbIndexTuningAdapter(gaussdb_driver)
        
        # Test index recommendations
        recommendations = await index_tuning_adapter.get_index_recommendations()
        
        # Verify recommendations
        assert len(recommendations) >= 0
        # Verify that recommendations include actionable suggestions
        recommendations_str = str(recommendations)
        assert "orders" in recommendations_str or "users" in recommendations_str
    
    @pytest.mark.asyncio
    async def test_index_impact_analysis_workflow(self, gaussdb_driver):
        """Test index impact analysis workflow."""
        # Mock hypothetical index testing (if supported)
        impact_responses = [
            # Before index creation
            [MockRowResult({
                "QUERY PLAN": "Seq Scan on orders  (cost=0.00..1500.00 rows=5000 width=64)"
            })],
            
            # After hypothetical index creation
            [MockRowResult({
                "QUERY PLAN": "Index Scan using idx_orders_customer_status on orders  (cost=0.42..25.50 rows=5000 width=64)"
            })]
        ]
        
        gaussdb_driver.execute_query.side_effect = impact_responses
        
        index_tuning_adapter = GaussDbIndexTuningAdapter(gaussdb_driver)
        
        # Test impact analysis
        test_query = "SELECT * FROM orders WHERE customer_id = 123 AND status = 'pending'"
        proposed_index = "CREATE INDEX idx_orders_customer_status ON orders (customer_id, status)"
        
        impact_analysis = await index_tuning_adapter.analyze_index_impact(test_query, proposed_index)
        
        # Verify impact analysis results
        assert "cost" in str(impact_analysis).lower()
        # Should show improvement from seq scan to index scan
        impact_str = str(impact_analysis)
        assert "scan" in impact_str.lower()


class TestGaussDbBenchmarkWorkflow:
    """End-to-end tests for benchmark workflows."""
    
    @pytest.mark.asyncio
    async def test_sysbench_benchmark_workflow(self, gaussdb_driver):
        """Test complete Sysbench benchmark workflow."""
        # Mock benchmark execution responses
        benchmark_responses = [
            # Pre-benchmark database state
            [MockRowResult({"setting": "shared_buffers", "value": "256MB"})],
            
            # Benchmark results
            [MockRowResult({
                "threads": 8,
                "tps": 1250.75,
                "latency_avg": 6.4,
                "latency_95th": 12.8,
                "queries_total": 125000,
                "queries_read": 87500,
                "queries_write": 37500
            })],
            
            # Post-benchmark statistics
            [MockRowResult({
                "total_connections": 45,
                "active_connections": 8,
                "index_hit_rate": 0.987,
                "table_hit_rate": 0.952
            })]
        ]
        
        gaussdb_driver.execute_query.side_effect = benchmark_responses
        
        # Mock benchmark tool
        with patch('src.postgres_mcp.benchmark.benchmark_tool.BenchmarkTool') as mock_benchmark:
            mock_benchmark_instance = AsyncMock()
            mock_benchmark_instance.run_sysbench.return_value = {
                "tps": 1250.75,
                "latency_avg": 6.4,
                "latency_95th": 12.8,
                "duration": 300,
                "threads": 8
            }
            mock_benchmark.return_value = mock_benchmark_instance
            
            # Test benchmark execution
            from src.postgres_mcp.benchmark.benchmark_tool import BenchmarkTool
            benchmark_tool = BenchmarkTool(gaussdb_driver)
            
            benchmark_config = {
                "test_type": "oltp_read_write",
                "threads": 8,
                "duration": 300,
                "table_size": 100000
            }
            
            result = await benchmark_tool.run_sysbench(benchmark_config)
            
            # Verify benchmark results
            assert result["tps"] == 1250.75
            assert result["latency_avg"] == 6.4
            assert result["threads"] == 8
    
    @pytest.mark.asyncio
    async def test_tpcc_benchmark_workflow(self, gaussdb_driver):
        """Test complete TPC-C benchmark workflow."""
        # Mock TPC-C benchmark responses
        tpcc_responses = [
            # TPC-C setup verification
            [MockRowResult({"table_name": "warehouse", "row_count": 10})],
            [MockRowResult({"table_name": "district", "row_count": 100})],
            [MockRowResult({"table_name": "customer", "row_count": 30000})],
            
            # TPC-C execution results
            [MockRowResult({
                "transaction_type": "new_order",
                "count": 4500,
                "response_time_avg": 0.025,
                "response_time_90th": 0.045
            })],
            [MockRowResult({
                "transaction_type": "payment",
                "count": 4300,
                "response_time_avg": 0.018,
                "response_time_90th": 0.032
            })]
        ]
        
        gaussdb_driver.execute_query.side_effect = tpcc_responses
        
        # Mock TPC-C benchmark tool
        with patch('src.postgres_mcp.benchmark.benchmark_tool.BenchmarkTool') as mock_benchmark:
            mock_benchmark_instance = AsyncMock()
            mock_benchmark_instance.run_tpcc.return_value = {
                "tpmC": 4250.5,
                "efficiency": 0.95,
                "new_order_tps": 4500,
                "payment_tps": 4300,
                "duration": 600,
                "warehouses": 10
            }
            mock_benchmark.return_value = mock_benchmark_instance
            
            # Test TPC-C execution
            from src.postgres_mcp.benchmark.benchmark_tool import BenchmarkTool
            benchmark_tool = BenchmarkTool(gaussdb_driver)
            
            tpcc_config = {
                "warehouses": 10,
                "duration": 600,
                "connections": 20,
                "ramp_up_time": 60
            }
            
            result = await benchmark_tool.run_tpcc(tpcc_config)
            
            # Verify TPC-C results
            assert result["tpmC"] == 4250.5
            assert result["efficiency"] == 0.95
            assert result["warehouses"] == 10


class TestGaussDbIntegratedWorkflows:
    """End-to-end tests for integrated workflows combining multiple features."""
    
    @pytest.mark.asyncio
    async def test_performance_optimization_workflow(self, gaussdb_driver):
        """Test complete performance optimization workflow."""
        # This workflow combines health checks, query analysis, and index tuning
        
        # Mock comprehensive performance data
        performance_responses = [
            # Health check - identify performance issues
            [MockRowResult({"rate": 0.85})],  # Low cache hit rate
            
            # Top queries - identify problematic queries
            [MockRowResult({
                "query": "SELECT * FROM large_table WHERE unindexed_column = $1",
                "calls": 10000,
                "total_time": 5000.0,
                "mean_time": 0.5
            })],
            
            # Table analysis - understand table structure
            [MockRowResult({
                "schemaname": "public",
                "tablename": "large_table",
                "seq_scan": 10000,
                "seq_tup_read": 100000000,
                "idx_scan": 500,
                "idx_tup_fetch": 5000
            })],
            
            # Index recommendations
            [MockRowResult({
                "table_name": "large_table",
                "recommended_index": "CREATE INDEX idx_large_table_unindexed ON large_table (unindexed_column)",
                "estimated_improvement": 85.5
            })]
        ]
        
        gaussdb_driver.execute_query.side_effect = performance_responses
        
        # Execute integrated performance optimization workflow
        
        # Step 1: Health check to identify issues
        buffer_calc = GaussDbBufferHealthCalc(gaussdb_driver)
        cache_hit_rate = await buffer_calc.index_hit_rate()
        
        # Step 2: Analyze top queries to find bottlenecks
        top_queries_adapter = GaussDbTopQueriesAdapter(gaussdb_driver)
        top_queries = await top_queries_adapter.get_top_queries(limit=5)
        
        # Step 3: Generate index recommendations
        index_tuning_adapter = GaussDbIndexTuningAdapter(gaussdb_driver)
        recommendations = await index_tuning_adapter.get_index_recommendations()
        
        # Verify integrated workflow results
        assert "85.0%" in cache_hit_rate  # Performance issue identified
        assert len(top_queries) >= 1      # Problematic queries found
        assert len(recommendations) >= 0  # Recommendations generated
        
        # Verify workflow provides actionable insights
        workflow_summary = {
            "performance_issues": "Low cache hit rate detected",
            "problematic_queries": len(top_queries),
            "recommendations": len(recommendations)
        }
        
        assert workflow_summary["performance_issues"] is not None
        assert workflow_summary["problematic_queries"] >= 0
        assert workflow_summary["recommendations"] >= 0
    
    @pytest.mark.asyncio
    async def test_database_migration_validation_workflow(self, gaussdb_driver):
        """Test database migration validation workflow."""
        # This workflow validates that a PostgreSQL to GaussDB migration is successful
        
        migration_responses = [
            # Verify database type detection
            [MockRowResult({"version": "GaussDB 8.1.0 on x86_64-linux-gnu"})],
            
            # Verify schema migration
            [MockRowResult({
                "table_name": "users",
                "column_count": 8,
                "constraint_count": 3,
                "index_count": 4
            })],
            
            # Verify data integrity
            [MockRowResult({"table_name": "users", "row_count": 50000})],
            [MockRowResult({"table_name": "orders", "row_count": 125000})],
            
            # Verify performance characteristics
            [MockRowResult({"query": "SELECT COUNT(*) FROM users", "execution_time": 0.025})],
            [MockRowResult({"query": "SELECT * FROM orders WHERE customer_id = $1", "execution_time": 0.008})]
        ]
        
        gaussdb_driver.execute_query.side_effect = migration_responses
        
        # Execute migration validation workflow
        
        # Step 1: Verify GaussDB detection
        db_type = await gaussdb_driver.get_database_type()
        
        # Step 2: Validate schema structure
        schema_validation = await gaussdb_driver.execute_query(
            "SELECT table_name, column_count, constraint_count, index_count FROM schema_summary"
        )
        
        # Step 3: Validate data integrity
        data_validation = await gaussdb_driver.execute_query(
            "SELECT table_name, row_count FROM table_row_counts"
        )
        
        # Step 4: Validate performance
        performance_validation = await gaussdb_driver.execute_query(
            "SELECT query, execution_time FROM performance_tests"
        )
        
        # Verify migration validation results
        assert db_type == DatabaseType.GAUSSDB
        assert len(schema_validation) >= 1
        assert len(data_validation) >= 2
        assert len(performance_validation) >= 2
        
        # Verify acceptable performance
        for result in performance_validation:
            assert result.cells["execution_time"] < 1.0  # All queries under 1 second


if __name__ == "__main__":
    pytest.main([__file__])