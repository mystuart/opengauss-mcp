"""
Integration tests for GaussDB health check adapters.

This module tests the integration of GaussDB health check adapters
with the overall system to ensure they work correctly in realistic scenarios.
"""

from typing import Any
from typing import Dict
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from opengauss_mcp.gaussdb import GaussDbBufferHealthCalc
from opengauss_mcp.gaussdb import GaussDbConnectionHealthCalc
from opengauss_mcp.gaussdb import GaussDbConstraintHealthCalc
from opengauss_mcp.gaussdb import GaussDbIndexHealthCalc
from opengauss_mcp.gaussdb import GaussDbReplicationCalc
from opengauss_mcp.gaussdb import GaussDbSequenceHealthCalc
from opengauss_mcp.gaussdb import GaussDbSqlDriver
from opengauss_mcp.gaussdb import GaussDbVacuumHealthCalc
from opengauss_mcp.sql.sql_driver import SqlDriver


class MockRowResult:
    """Mock RowResult for integration testing."""

    def __init__(self, cells: Dict[str, Any]):
        self.cells = cells


@pytest.fixture
def mock_sql_driver():
    """Create a mock SQL driver for integration testing."""
    driver = AsyncMock(spec=SqlDriver)
    driver.execute_query = AsyncMock()
    driver.get_database_version = AsyncMock(return_value="8.1.0")
    driver.get_database_type = AsyncMock(return_value="gaussdb")
    driver.is_gaussdb = AsyncMock(return_value=True)
    driver.is_postgresql = AsyncMock(return_value=False)
    return driver


@pytest.fixture
def gaussdb_driver(mock_sql_driver):
    """Create a GaussDB driver for integration testing."""
    return GaussDbSqlDriver(mock_sql_driver)


class TestGaussDbHealthAdaptersIntegration:
    """Integration tests for all GaussDB health adapters."""

    @pytest.mark.asyncio
    async def test_complete_health_check_workflow(self, gaussdb_driver):
        """Test a complete health check workflow using all adapters."""
        # Mock database responses for different health checks
        gaussdb_driver.execute_query = AsyncMock(side_effect=[
            # Index health check - no invalid indexes
            [MockRowResult({
                "schema": "public", "table": "test_table", "name": "test_idx",
                "columns": "id", "using": "btree", "unique": False, "primary": False,
                "valid": True, "indexprs": None, "indpred": None, "definition": "CREATE INDEX..."
            })],

            # Connection health check - total connections
            [MockRowResult({"count": 25})],

            # Connection health check - idle connections
            [MockRowResult({"count": 5})],

            # Buffer health check - index hit rate
            [MockRowResult({"rate": 0.98})],

            # Buffer health check - table hit rate
            [MockRowResult({"rate": 0.96})],

            # Replication health check - is replica
            [MockRowResult({"pg_is_in_recovery": False})],

            # Constraint health check - invalid constraints
            []
        ])

        # Initialize all health adapters
        index_calc = GaussDbIndexHealthCalc(gaussdb_driver)
        connection_calc = GaussDbConnectionHealthCalc(gaussdb_driver, max_total_connections=100)
        buffer_calc = GaussDbBufferHealthCalc(gaussdb_driver)
        replication_calc = GaussDbReplicationCalc(gaussdb_driver)
        constraint_calc = GaussDbConstraintHealthCalc(gaussdb_driver)

        # Run health checks
        index_result = await index_calc.invalid_index_check()
        connection_result = await connection_calc.connection_health_check()
        index_hit_rate = await buffer_calc.index_hit_rate()
        table_hit_rate = await buffer_calc.table_hit_rate()
        replication_result = await replication_calc.replication_health_check()
        constraint_result = await constraint_calc.invalid_constraints_check()

        # Verify results
        assert "No invalid indexes found" in index_result
        assert "Connections healthy: 25 total, 5 idle" in connection_result
        assert "Index cache hit rate: 98.0%" in index_hit_rate
        assert "Table cache hit rate: 96.0%" in table_hit_rate
        assert "This is a primary database" in replication_result
        assert "No invalid constraints found" in constraint_result

    @pytest.mark.asyncio
    async def test_health_adapters_with_gaussdb_specific_features(self, gaussdb_driver):
        """Test health adapters with GaussDB-specific features and configurations."""
        # Mock GaussDB-specific configuration
        gaussdb_driver.test_feature_support = AsyncMock(return_value=True)

        # Mock the compatibility config property
        mock_config = MagicMock()
        mock_config.supports_replication_stats = True
        gaussdb_driver._compatibility_config = mock_config

        # Mock GaussDB-specific query responses
        gaussdb_driver.execute_query = AsyncMock(side_effect=[
            # Vacuum health check - transaction ID metrics
            [MockRowResult({
                "schema": "public",
                "table": "test_table",
                "transactions_left": 50000000
            })],

            # Sequence health check - sequence information
            [MockRowResult({
                "table_schema": "public",
                "table": "test_table",
                "column": "id",
                "column_type": "integer",
                "default_value": "nextval('test_seq'::regclass)"
            })],

            # Sequence attributes
            [MockRowResult({
                "readable": True,
                "last_value": 1000
            })]
        ])

        # Initialize adapters
        vacuum_calc = GaussDbVacuumHealthCalc(gaussdb_driver)
        sequence_calc = GaussDbSequenceHealthCalc(gaussdb_driver)

        # Test vacuum health check
        with patch('postgres_mcp.gaussdb.health_adapters.SafeSqlDriver.execute_param_query',
                  new_callable=AsyncMock, return_value=[]):
            vacuum_result = await vacuum_calc.transaction_id_danger_check()
            assert "No tables found with transaction ID wraparound danger" in vacuum_result

        # Test sequence health check - mock the internal method to avoid complex parsing
        from opengauss_mcp.database_health.sequence_health_calc import SequenceMetrics
        mock_sequence_metrics = [
            SequenceMetrics(
                schema="public",
                table="test_table",
                column="id",
                sequence="test_seq",
                column_type="integer",
                last_value=1000,
                max_value=2147483647,
                is_healthy=True
            )
        ]
        sequence_calc._gaussdb_get_sequence_metrics = AsyncMock(return_value=mock_sequence_metrics)

        sequence_result = await sequence_calc.sequence_danger_check()
        assert "All sequences have healthy usage levels" in sequence_result

    @pytest.mark.asyncio
    async def test_health_adapters_fallback_behavior(self, gaussdb_driver):
        """Test that health adapters properly fallback when GaussDB-specific queries fail."""
        # Mock GaussDB driver to fail on specific queries
        gaussdb_driver.execute_query = AsyncMock(side_effect=Exception("GaussDB connection error"))

        # Initialize adapter
        connection_calc = GaussDbConnectionHealthCalc(gaussdb_driver)

        # Mock the fallback methods to succeed
        connection_calc._get_total_connections = AsyncMock(return_value=30)
        connection_calc._get_idle_connections = AsyncMock(return_value=8)

        # Test that fallback works
        result = await connection_calc.connection_health_check()
        assert "Connections healthy: 30 total, 8 idle" in result

    @pytest.mark.asyncio
    async def test_health_adapters_error_handling(self, gaussdb_driver):
        """Test error handling in health adapters."""
        # Initialize adapter
        buffer_calc = GaussDbBufferHealthCalc(gaussdb_driver)

        # Mock GaussDB-specific method to fail
        buffer_calc._gaussdb_index_hit_rate = AsyncMock(side_effect=Exception("GaussDB error"))

        # Mock parent class method to succeed
        with patch.object(buffer_calc.__class__.__bases__[0], 'index_hit_rate',
                         new_callable=AsyncMock, return_value="Fallback: Index hit rate 95.0%"):
            result = await buffer_calc.index_hit_rate()
            assert "Fallback: Index hit rate 95.0%" in result

    @pytest.mark.asyncio
    async def test_health_adapters_with_empty_results(self, gaussdb_driver):
        """Test health adapters behavior with empty database results."""
        # Mock empty results
        gaussdb_driver.execute_query = AsyncMock(return_value=[])

        # Initialize adapters
        index_calc = GaussDbIndexHealthCalc(gaussdb_driver)
        constraint_calc = GaussDbConstraintHealthCalc(gaussdb_driver)

        # Test with empty results
        index_result = await index_calc.invalid_index_check()
        constraint_result = await constraint_calc.invalid_constraints_check()

        assert "No invalid indexes found" in index_result
        assert "No invalid constraints found" in constraint_result

    @pytest.mark.asyncio
    async def test_health_adapters_performance_metrics(self, gaussdb_driver):
        """Test health adapters with performance-related metrics."""
        # Mock performance data
        gaussdb_driver.execute_query = AsyncMock(side_effect=[
            # Buffer statistics
            [MockRowResult({
                "setting_name": "shared_buffers",
                "setting_value": "256MB",
                "unit": None
            })],

            # Connection details
            [MockRowResult({
                "state": "active",
                "count": 10,
                "application_name": "test_app",
                "client_addr": "192.168.1.100",
                "backend_start": "2023-01-01 10:00:00",
                "query_start": "2023-01-01 10:05:00",
                "state_change": "2023-01-01 10:05:00"
            })]
        ])

        # Initialize adapters
        buffer_calc = GaussDbBufferHealthCalc(gaussdb_driver)
        connection_calc = GaussDbConnectionHealthCalc(gaussdb_driver)

        # Mock additional methods
        buffer_calc._gaussdb_index_hit_rate = AsyncMock(return_value="Index hit rate: 98.5%")
        buffer_calc._gaussdb_table_hit_rate = AsyncMock(return_value="Table hit rate: 97.2%")

        # Test performance metrics
        buffer_stats = await buffer_calc.get_buffer_statistics()
        connection_details = await connection_calc.get_connection_details()

        assert buffer_stats["shared_buffers"] == "256MB"
        assert "index_hit_rate_status" in buffer_stats
        assert connection_details["total_connections"] == 10
        assert connection_details["unique_applications"] == 1

    @pytest.mark.asyncio
    async def test_health_adapters_with_large_datasets(self, gaussdb_driver):
        """Test health adapters with large dataset scenarios."""
        # Mock large dataset responses
        large_index_data = []
        for i in range(100):
            large_index_data.append(MockRowResult({
                "schema": "public",
                "table": f"table_{i}",
                "name": f"idx_{i}",
                "columns": f"col_{i}",
                "using": "btree",
                "unique": False,
                "primary": False,
                "valid": True,
                "indexprs": None,
                "indpred": None,
                "definition": f"CREATE INDEX idx_{i}..."
            }))

        gaussdb_driver.execute_query = AsyncMock(return_value=large_index_data)

        # Initialize adapter
        index_calc = GaussDbIndexHealthCalc(gaussdb_driver)

        # Test with large dataset
        result = await index_calc.invalid_index_check()
        assert "No invalid indexes found" in result

        # Verify that the adapter can handle large datasets efficiently
        assert gaussdb_driver.execute_query.call_count == 1

    @pytest.mark.asyncio
    async def test_health_adapters_concurrent_execution(self, gaussdb_driver):
        """Test concurrent execution of multiple health adapters."""
        import asyncio

        # Mock responses for concurrent queries
        gaussdb_driver.execute_query = AsyncMock(side_effect=[
            [MockRowResult({"count": 50})],  # connections
            [MockRowResult({"rate": 0.95})], # index hit rate
            [MockRowResult({"pg_is_in_recovery": False})], # replication
            []  # constraints
        ])

        # Initialize adapters
        connection_calc = GaussDbConnectionHealthCalc(gaussdb_driver)
        buffer_calc = GaussDbBufferHealthCalc(gaussdb_driver)
        replication_calc = GaussDbReplicationCalc(gaussdb_driver)
        constraint_calc = GaussDbConstraintHealthCalc(gaussdb_driver)

        # Run health checks concurrently
        tasks = [
            connection_calc.total_connections_check(),
            buffer_calc.index_hit_rate(),
            replication_calc._gaussdb_is_replica(),
            constraint_calc.invalid_constraints_check()
        ]

        results = await asyncio.gather(*tasks)

        # Verify all tasks completed successfully
        assert len(results) == 4
        assert "connections healthy" in results[0].lower()
        assert "hit rate" in results[1].lower()
        assert results[2] is False  # not a replica
        assert "no invalid constraints" in results[3].lower()
