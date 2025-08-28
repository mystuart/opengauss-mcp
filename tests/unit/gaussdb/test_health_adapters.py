"""
Unit tests for GaussDB health check adapters.

This module tests the GaussDB-specific health check adapters to ensure they
properly handle GaussDB differences while maintaining fallback compatibility.
"""

from typing import Any
from typing import Dict
from unittest.mock import AsyncMock
from unittest.mock import patch

import pytest

from opengauss_mcp.gaussdb.health_adapters import GaussDbBufferHealthCalc
from opengauss_mcp.gaussdb.health_adapters import GaussDbConnectionHealthCalc
from opengauss_mcp.gaussdb.health_adapters import GaussDbConstraintHealthCalc
from opengauss_mcp.gaussdb.health_adapters import GaussDbIndexHealthCalc
from opengauss_mcp.gaussdb.health_adapters import GaussDbReplicationCalc
from opengauss_mcp.gaussdb.health_adapters import GaussDbSequenceHealthCalc
from opengauss_mcp.gaussdb.health_adapters import GaussDbVacuumHealthCalc
from opengauss_mcp.gaussdb.sql_driver_adapter import GaussDbSqlDriver
from opengauss_mcp.sql.sql_driver import SqlDriver


class MockRowResult:
    """Mock RowResult for testing."""

    def __init__(self, cells: Dict[str, Any]):
        self.cells = cells


@pytest.fixture
def mock_sql_driver():
    """Create a mock SQL driver for testing."""
    driver = AsyncMock(spec=SqlDriver)
    driver.execute_query = AsyncMock()
    return driver


@pytest.fixture
def mock_gaussdb_driver(mock_sql_driver):
    """Create a mock GaussDB SQL driver for testing."""
    gaussdb_driver = AsyncMock(spec=GaussDbSqlDriver)
    gaussdb_driver.base_driver = mock_sql_driver
    gaussdb_driver.execute_query = AsyncMock()
    gaussdb_driver.test_feature_support = AsyncMock(return_value=True)
    return gaussdb_driver


class TestGaussDbIndexHealthCalc:
    """Test cases for GaussDbIndexHealthCalc."""

    @pytest.mark.asyncio
    async def test_init_with_regular_driver(self, mock_sql_driver):
        """Test initialization with regular SqlDriver."""
        calc = GaussDbIndexHealthCalc(mock_sql_driver)
        assert calc.sql_driver == mock_sql_driver
        assert isinstance(calc.gaussdb_driver, GaussDbSqlDriver)

    @pytest.mark.asyncio
    async def test_init_with_gaussdb_driver(self, mock_gaussdb_driver):
        """Test initialization with GaussDbSqlDriver."""
        calc = GaussDbIndexHealthCalc(mock_gaussdb_driver)
        assert calc.sql_driver == mock_gaussdb_driver.base_driver
        assert calc.gaussdb_driver == mock_gaussdb_driver

    @pytest.mark.asyncio
    async def test_invalid_index_check_success(self, mock_gaussdb_driver):
        """Test successful invalid index check."""
        # Mock index data with no invalid indexes
        mock_indexes = [
            {"name": "idx1", "table": "table1", "valid": True},
            {"name": "idx2", "table": "table2", "valid": True}
        ]

        calc = GaussDbIndexHealthCalc(mock_gaussdb_driver)
        calc._gaussdb_indexes = AsyncMock(return_value=mock_indexes)

        result = await calc.invalid_index_check()
        assert result == "No invalid indexes found."

    @pytest.mark.asyncio
    async def test_invalid_index_check_with_invalid_indexes(self, mock_gaussdb_driver):
        """Test invalid index check with invalid indexes found."""
        # Mock index data with invalid indexes
        mock_indexes = [
            {"name": "idx1", "table": "table1", "valid": True},
            {"name": "idx2", "table": "table2", "valid": False}
        ]

        calc = GaussDbIndexHealthCalc(mock_gaussdb_driver)
        calc._gaussdb_indexes = AsyncMock(return_value=mock_indexes)

        result = await calc.invalid_index_check()
        assert "Invalid indexes found:" in result
        assert "idx2 on table2 is invalid." in result

    @pytest.mark.asyncio
    async def test_invalid_index_check_fallback(self, mock_gaussdb_driver):
        """Test fallback to PostgreSQL when GaussDB-specific check fails."""
        calc = GaussDbIndexHealthCalc(mock_gaussdb_driver)
        calc._gaussdb_indexes = AsyncMock(side_effect=Exception("GaussDB error"))

        # Mock the parent class method
        with patch.object(calc.__class__.__bases__[0], 'invalid_index_check',
                         new_callable=AsyncMock, return_value="Fallback result"):
            result = await calc.invalid_index_check()
            assert result == "Fallback result"

    @pytest.mark.asyncio
    async def test_duplicate_index_check_no_duplicates(self, mock_gaussdb_driver):
        """Test duplicate index check with no duplicates."""
        mock_indexes = [
            {
                "name": "idx1", "table": "table1", "schema": "public", "valid": True,
                "primary": False, "unique": False, "columns": ["col1"], "using": "btree",
                "indexprs": None, "indpred": None
            }
        ]

        calc = GaussDbIndexHealthCalc(mock_gaussdb_driver)
        calc._gaussdb_indexes = AsyncMock(return_value=mock_indexes)

        result = await calc.duplicate_index_check()
        assert result == "No duplicate indexes found."

    @pytest.mark.asyncio
    async def test_index_bloat_no_bloat(self, mock_gaussdb_driver):
        """Test index bloat check with no bloated indexes."""
        mock_gaussdb_driver.execute_query = AsyncMock(return_value=[])

        with patch('postgres_mcp.gaussdb.health_adapters.SafeSqlDriver.execute_param_query',
                  new_callable=AsyncMock, return_value=[]):
            calc = GaussDbIndexHealthCalc(mock_gaussdb_driver)
            result = await calc.index_bloat()
            assert result == "No bloated indexes found."

    @pytest.mark.asyncio
    async def test_index_bloat_with_bloated_indexes(self, mock_gaussdb_driver):
        """Test index bloat check with bloated indexes found."""
        mock_bloated_data = [
            MockRowResult({
                "index": "bloated_idx",
                "table": "test_table",
                "bloat_bytes": 209715200,  # 200MB
                "index_bytes": 314572800   # 300MB
            })
        ]

        with patch('postgres_mcp.gaussdb.health_adapters.SafeSqlDriver.execute_param_query',
                  new_callable=AsyncMock, return_value=mock_bloated_data):
            calc = GaussDbIndexHealthCalc(mock_gaussdb_driver)
            result = await calc.index_bloat()
            assert "Bloated indexes found:" in result
            assert "bloated_idx" in result
            assert "200.0MB bloat" in result

    @pytest.mark.asyncio
    async def test_unused_indexes_no_unused(self, mock_gaussdb_driver):
        """Test unused indexes check with no unused indexes."""
        with patch('postgres_mcp.gaussdb.health_adapters.SafeSqlDriver.execute_param_query',
                  new_callable=AsyncMock, return_value=[]):
            calc = GaussDbIndexHealthCalc(mock_gaussdb_driver)
            result = await calc.unused_indexes()
            assert result == "No unused indexes found."

    @pytest.mark.asyncio
    async def test_unused_indexes_with_unused(self, mock_gaussdb_driver):
        """Test unused indexes check with unused indexes found."""
        mock_unused_data = [
            MockRowResult({
                "index": "unused_idx",
                "table": "test_table",
                "size_bytes": 10485760,  # 10MB
                "index_scans": 5,
                "primary": False
            })
        ]

        with patch('postgres_mcp.gaussdb.health_adapters.SafeSqlDriver.execute_param_query',
                  new_callable=AsyncMock, return_value=mock_unused_data):
            calc = GaussDbIndexHealthCalc(mock_gaussdb_driver)
            result = await calc.unused_indexes()
            assert "Rarely used indexes found:" in result
            assert "unused_idx" in result
            assert "scanned 5 times" in result


class TestGaussDbConnectionHealthCalc:
    """Test cases for GaussDbConnectionHealthCalc."""

    @pytest.mark.asyncio
    async def test_total_connections_check_healthy(self, mock_gaussdb_driver):
        """Test total connections check with healthy connection count."""
        mock_result = [MockRowResult({"count": 50})]
        mock_gaussdb_driver.execute_query = AsyncMock(return_value=mock_result)

        calc = GaussDbConnectionHealthCalc(mock_gaussdb_driver, max_total_connections=100)
        result = await calc.total_connections_check()
        assert result == "Total connections healthy: 50"

    @pytest.mark.asyncio
    async def test_total_connections_check_unhealthy(self, mock_gaussdb_driver):
        """Test total connections check with high connection count."""
        mock_result = [MockRowResult({"count": 150})]
        mock_gaussdb_driver.execute_query = AsyncMock(return_value=mock_result)

        calc = GaussDbConnectionHealthCalc(mock_gaussdb_driver, max_total_connections=100)
        result = await calc.total_connections_check()
        assert result == "High number of connections: 150 (max: 100)"

    @pytest.mark.asyncio
    async def test_idle_connections_check_healthy(self, mock_gaussdb_driver):
        """Test idle connections check with healthy idle count."""
        mock_result = [MockRowResult({"count": 10})]
        mock_gaussdb_driver.execute_query = AsyncMock(return_value=mock_result)

        calc = GaussDbConnectionHealthCalc(mock_gaussdb_driver, max_idle_connections=50)
        result = await calc.idle_connections_check()
        assert result == "Idle connections healthy: 10"

    @pytest.mark.asyncio
    async def test_connection_health_check_combined(self, mock_gaussdb_driver):
        """Test combined connection health check."""
        # Mock both total and idle connection queries
        mock_gaussdb_driver.execute_query = AsyncMock(side_effect=[
            [MockRowResult({"count": 50})],  # total connections
            [MockRowResult({"count": 10})]   # idle connections
        ])

        calc = GaussDbConnectionHealthCalc(mock_gaussdb_driver)
        result = await calc.connection_health_check()
        assert result == "Connections healthy: 50 total, 10 idle"

    @pytest.mark.asyncio
    async def test_get_connection_details_success(self, mock_gaussdb_driver):
        """Test getting detailed connection information."""
        mock_result = [
            MockRowResult({
                "state": "active",
                "count": 5,
                "application_name": "test_app",
                "client_addr": "127.0.0.1",
                "backend_start": "2023-01-01",
                "query_start": "2023-01-01",
                "state_change": "2023-01-01"
            })
        ]
        mock_gaussdb_driver.execute_query = AsyncMock(return_value=mock_result)

        calc = GaussDbConnectionHealthCalc(mock_gaussdb_driver)
        result = await calc.get_connection_details()

        assert result["total_connections"] == 5
        assert result["unique_applications"] == 1
        assert len(result["connections_by_state"]) == 1


class TestGaussDbBufferHealthCalc:
    """Test cases for GaussDbBufferHealthCalc."""

    @pytest.mark.asyncio
    async def test_index_hit_rate_healthy(self, mock_gaussdb_driver):
        """Test index hit rate check with healthy rate."""
        mock_result = [MockRowResult({"rate": 0.98})]
        mock_gaussdb_driver.execute_query = AsyncMock(return_value=mock_result)

        calc = GaussDbBufferHealthCalc(mock_gaussdb_driver)
        result = await calc.index_hit_rate()
        assert "Index cache hit rate: 98.0%" in result
        assert "above 95.0% threshold" in result

    @pytest.mark.asyncio
    async def test_index_hit_rate_unhealthy(self, mock_gaussdb_driver):
        """Test index hit rate check with low rate."""
        mock_result = [MockRowResult({"rate": 0.85})]
        mock_gaussdb_driver.execute_query = AsyncMock(return_value=mock_result)

        calc = GaussDbBufferHealthCalc(mock_gaussdb_driver)
        result = await calc.index_hit_rate()
        assert "Index cache hit rate: 85.0%" in result
        assert "below 95.0% threshold" in result

    @pytest.mark.asyncio
    async def test_table_hit_rate_no_stats(self, mock_gaussdb_driver):
        """Test table hit rate check with no statistics available."""
        mock_result = [MockRowResult({"rate": None})]
        mock_gaussdb_driver.execute_query = AsyncMock(return_value=mock_result)

        calc = GaussDbBufferHealthCalc(mock_gaussdb_driver)
        result = await calc.table_hit_rate()
        assert result == "No table cache statistics available."

    @pytest.mark.asyncio
    async def test_get_buffer_statistics_success(self, mock_gaussdb_driver):
        """Test getting buffer statistics."""
        mock_result = [
            MockRowResult({
                "setting_name": "shared_buffers",
                "setting_value": "128MB",
                "unit": None
            })
        ]
        mock_gaussdb_driver.execute_query = AsyncMock(return_value=mock_result)

        calc = GaussDbBufferHealthCalc(mock_gaussdb_driver)
        calc._gaussdb_index_hit_rate = AsyncMock(return_value="Index hit rate: 98.0%")
        calc._gaussdb_table_hit_rate = AsyncMock(return_value="Table hit rate: 97.0%")

        result = await calc.get_buffer_statistics()
        assert result["shared_buffers"] == "128MB"
        assert "index_hit_rate_status" in result


class TestGaussDbVacuumHealthCalc:
    """Test cases for GaussDbVacuumHealthCalc."""

    @pytest.mark.asyncio
    async def test_transaction_id_danger_check_healthy(self, mock_gaussdb_driver):
        """Test transaction ID danger check with healthy tables."""
        calc = GaussDbVacuumHealthCalc(mock_gaussdb_driver)
        calc._gaussdb_get_transaction_id_metrics = AsyncMock(return_value=[])

        result = await calc.transaction_id_danger_check()
        assert result == "No tables found with transaction ID wraparound danger."

    @pytest.mark.asyncio
    async def test_get_vacuum_statistics_success(self, mock_gaussdb_driver):
        """Test getting vacuum statistics."""
        mock_result = [
            MockRowResult({
                "schemaname": "public",
                "relname": "test_table",
                "last_vacuum": "2023-01-01",
                "last_autovacuum": "2023-01-02",
                "vacuum_count": 5,
                "autovacuum_count": 10,
                "n_tup_ins": 1000,
                "n_tup_upd": 500,
                "n_tup_del": 100,
                "n_dead_tup": 50
            })
        ]
        mock_gaussdb_driver.execute_query = AsyncMock(return_value=mock_result)

        calc = GaussDbVacuumHealthCalc(mock_gaussdb_driver)
        result = await calc.get_vacuum_statistics()

        assert result["total_tables"] == 1
        assert result["tables_with_dead_tuples"] == 1
        assert result["tables_needing_vacuum"] == 0  # 50 dead tuples < 1000 threshold


class TestGaussDbSequenceHealthCalc:
    """Test cases for GaussDbSequenceHealthCalc."""

    @pytest.mark.asyncio
    async def test_sequence_danger_check_no_sequences(self, mock_gaussdb_driver):
        """Test sequence danger check with no sequences."""
        calc = GaussDbSequenceHealthCalc(mock_gaussdb_driver)
        calc._gaussdb_get_sequence_metrics = AsyncMock(return_value=[])

        result = await calc.sequence_danger_check()
        assert result == "No sequences found in the database."

    @pytest.mark.asyncio
    async def test_sequence_danger_check_healthy_sequences(self, mock_gaussdb_driver):
        """Test sequence danger check with healthy sequences."""
        from opengauss_mcp.database_health.sequence_health_calc import SequenceMetrics

        mock_metrics = [
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

        calc = GaussDbSequenceHealthCalc(mock_gaussdb_driver)
        calc._gaussdb_get_sequence_metrics = AsyncMock(return_value=mock_metrics)

        result = await calc.sequence_danger_check()
        assert result == "All sequences have healthy usage levels."


class TestGaussDbReplicationCalc:
    """Test cases for GaussDbReplicationCalc."""

    @pytest.mark.asyncio
    async def test_replication_health_check_primary(self, mock_gaussdb_driver):
        """Test replication health check for primary database."""
        from opengauss_mcp.database_health.replication_calc import ReplicationMetrics

        mock_metrics = ReplicationMetrics(
            is_replica=False,
            replication_lag_seconds=None,
            is_replicating=False,
            replication_slots=[]
        )

        calc = GaussDbReplicationCalc(mock_gaussdb_driver)
        calc._gaussdb_get_replication_metrics = AsyncMock(return_value=mock_metrics)

        result = await calc.replication_health_check()
        assert "This is a primary database." in result
        assert "No active replicas connected." in result
        assert "No replication slots found." in result

    @pytest.mark.asyncio
    async def test_replication_health_check_replica(self, mock_gaussdb_driver):
        """Test replication health check for replica database."""
        from opengauss_mcp.database_health.replication_calc import ReplicationMetrics

        mock_metrics = ReplicationMetrics(
            is_replica=True,
            replication_lag_seconds=0.5,
            is_replicating=True,
            replication_slots=[]
        )

        calc = GaussDbReplicationCalc(mock_gaussdb_driver)
        calc._gaussdb_get_replication_metrics = AsyncMock(return_value=mock_metrics)

        result = await calc.replication_health_check()
        assert "This is a replica database." in result
        assert "Replica is actively replicating from primary." in result
        assert "Replication lag: 0.5 seconds" in result


class TestGaussDbConstraintHealthCalc:
    """Test cases for GaussDbConstraintHealthCalc."""

    @pytest.mark.asyncio
    async def test_invalid_constraints_check_no_invalid(self, mock_gaussdb_driver):
        """Test invalid constraints check with no invalid constraints."""
        calc = GaussDbConstraintHealthCalc(mock_gaussdb_driver)
        calc._gaussdb_get_invalid_constraints = AsyncMock(return_value=[])

        result = await calc.invalid_constraints_check()
        assert result == "No invalid constraints found."

    @pytest.mark.asyncio
    async def test_invalid_constraints_check_with_invalid(self, mock_gaussdb_driver):
        """Test invalid constraints check with invalid constraints found."""
        from opengauss_mcp.database_health.constraint_health_calc import ConstraintMetrics

        mock_metrics = [
            ConstraintMetrics(
                schema="public",
                table="test_table",
                name="test_constraint",
                referenced_schema="public",
                referenced_table="ref_table"
            )
        ]

        calc = GaussDbConstraintHealthCalc(mock_gaussdb_driver)
        calc._gaussdb_get_invalid_constraints = AsyncMock(return_value=mock_metrics)

        result = await calc.invalid_constraints_check()
        assert "Invalid constraints found:" in result
        assert "test_constraint" in result
        assert "test_table" in result

    @pytest.mark.asyncio
    async def test_get_constraint_statistics_success(self, mock_gaussdb_driver):
        """Test getting constraint statistics."""
        mock_gaussdb_driver.execute_query = AsyncMock(side_effect=[
            [MockRowResult({"count": 100})],  # total constraints
            [MockRowResult({"count": 95})],   # active constraints
            [MockRowResult({"count": 2})]     # invalid constraints
        ])

        calc = GaussDbConstraintHealthCalc(mock_gaussdb_driver)
        result = await calc.get_constraint_statistics()

        assert result["total_constraints"] == 100
        assert result["active_constraints"] == 95
        assert result["invalid_constraints"] == 2
        assert result["valid_constraints"] == 98
        assert result["health_status"] == "needs_attention"


# Integration test for all adapters
class TestHealthAdaptersIntegration:
    """Integration tests for all health adapters."""

    @pytest.mark.asyncio
    async def test_all_adapters_initialization(self, mock_sql_driver):
        """Test that all adapters can be initialized properly."""
        adapters = [
            GaussDbIndexHealthCalc(mock_sql_driver),
            GaussDbConnectionHealthCalc(mock_sql_driver),
            GaussDbBufferHealthCalc(mock_sql_driver),
            GaussDbVacuumHealthCalc(mock_sql_driver),
            GaussDbSequenceHealthCalc(mock_sql_driver),
            GaussDbReplicationCalc(mock_sql_driver),
            GaussDbConstraintHealthCalc(mock_sql_driver)
        ]

        for adapter in adapters:
            assert adapter.sql_driver == mock_sql_driver
            assert hasattr(adapter, 'gaussdb_driver')
            assert isinstance(adapter.gaussdb_driver, GaussDbSqlDriver)

    @pytest.mark.asyncio
    async def test_fallback_behavior(self, mock_gaussdb_driver):
        """Test that all adapters properly fallback to PostgreSQL methods on error."""
        # Test one adapter as representative
        calc = GaussDbIndexHealthCalc(mock_gaussdb_driver)

        # Mock GaussDB-specific method to fail
        calc._gaussdb_invalid_index_check = AsyncMock(side_effect=Exception("GaussDB error"))

        # Mock parent class method to succeed
        with patch.object(calc.__class__.__bases__[0], 'invalid_index_check',
                         new_callable=AsyncMock, return_value="Fallback success"):
            result = await calc.invalid_index_check()
            assert result == "Fallback success"
