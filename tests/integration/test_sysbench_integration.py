"""
Integration tests for Sysbench benchmark functionality.
"""

import subprocess
from datetime import datetime
from unittest.mock import AsyncMock
from unittest.mock import Mock
from unittest.mock import patch

import pytest

from opengauss_mcp.benchmark import BenchmarkRunner
from opengauss_mcp.benchmark import BenchmarkTool
from opengauss_mcp.benchmark import BenchmarkType
from opengauss_mcp.benchmark import SysbenchConfig
from opengauss_mcp.gaussdb.sql_driver_adapter import GaussDbSqlDriver
from opengauss_mcp.sql.sql_driver import SqlDriver


class TestSysbenchIntegration:
    """Integration tests for Sysbench benchmark functionality."""

    @pytest.fixture
    def mock_sql_driver(self):
        """Create a mock SQL driver."""
        driver = Mock(spec=SqlDriver)
        driver.execute_query = AsyncMock()
        return driver

    @pytest.fixture
    def mock_gaussdb_driver(self):
        """Create a mock GaussDB SQL driver."""
        driver = Mock(spec=GaussDbSqlDriver)
        driver.execute_query = AsyncMock()
        return driver

    @pytest.fixture
    def benchmark_runner(self, mock_sql_driver):
        """Create a benchmark runner with mock driver."""
        return BenchmarkRunner(mock_sql_driver)

    @pytest.fixture
    def gaussdb_benchmark_runner(self, mock_gaussdb_driver):
        """Create a benchmark runner with mock GaussDB driver."""
        return BenchmarkRunner(mock_gaussdb_driver)

    @pytest.fixture
    def benchmark_tool(self, mock_sql_driver):
        """Create a benchmark tool with mock driver."""
        return BenchmarkTool(mock_sql_driver)

    @pytest.fixture
    def sample_sysbench_output(self):
        """Sample Sysbench output for testing."""
        return """
sysbench 1.0.20 (using system LuaJIT 2.1.0-beta3)

Running the test with following options:
Number of threads: 4
Initializing random number generator from current time

Initializing worker threads...

Threads started!

SQL statistics:
    queries performed:
        read:                            14000
        write:                           4000
        other:                           2000
        total:                           20000
    transactions:                        1000 (100.00 per sec.)
    queries:                             20000 (2000.00 per sec.)
    ignored errors:                      0
    reconnects:                          0

General statistics:
    total time:                          10.0000s
    total number of events:              1000

Latency (ms):
         min:                                    5.50
         avg:                                   39.50
         max:                                  150.00
         95th percentile:                       75.00
         99th percentile:                      120.00
         sum:                                39500.00

Threads fairness:
    events (avg/stddev):           250.0000/0.00
    execution time (avg/stddev):   9.8750/0.05
"""

    @pytest.mark.asyncio
    async def test_sysbench_output_parsing(self, benchmark_runner, sample_sysbench_output):
        """Test parsing of Sysbench output."""
        config = SysbenchConfig()
        start_time = datetime.now()
        end_time = datetime.now()
        duration = 10.0

        result = benchmark_runner._parse_sysbench_output(
            sample_sysbench_output, config, start_time, end_time, duration
        )

        assert result.benchmark_type == BenchmarkType.SYSBENCH
        assert result.transactions_per_second == 100.0
        assert result.queries_per_second == 2000.0
        assert result.latency_avg_ms == 39.5
        assert result.latency_95th_ms == 75.0
        assert result.latency_99th_ms == 120.0
        assert result.errors == 0
        assert result.duration_seconds == 10.0

    @pytest.mark.asyncio
    async def test_sysbench_output_parsing_alternative_format(self, benchmark_runner):
        """Test parsing of alternative Sysbench output format."""
        alternative_output = """
sysbench 1.0.18

SQL statistics:
    queries performed:
        read:                            7000
        write:                           2000
        other:                           1000
        total:                           10000
    transactions:                        500 (50.25 per sec.)
    queries:                             10000 (1005.00 per sec.)
    ignored errors:                      2
    reconnects:                          0

General statistics:
    total time:                          9.9500s
    total number of events:              500

Latency (ms):
         min:                                    2.10
         avg:                                   79.20
         max:                                  250.00
         95th percentile:                      150.29
         99th percentile:                      196.89
"""

        config = SysbenchConfig()
        start_time = datetime.now()
        end_time = datetime.now()
        duration = 9.95

        result = benchmark_runner._parse_sysbench_output(
            alternative_output, config, start_time, end_time, duration
        )

        assert result.transactions_per_second == 50.25
        assert result.queries_per_second == 1005.0
        assert result.latency_avg_ms == 79.2
        assert result.latency_95th_ms == 150.29
        assert result.latency_99th_ms == 196.89
        assert result.errors == 2

    @pytest.mark.asyncio
    async def test_sysbench_output_parsing_missing_tps(self, benchmark_runner):
        """Test parsing when TPS is missing but total events are available."""
        minimal_output = """
sysbench 1.0.20

General statistics:
    total time:                          5.0000s
    total number of events:              250

Latency (ms):
         avg:                                   20.00
"""

        config = SysbenchConfig()
        start_time = datetime.now()
        end_time = datetime.now()
        duration = 5.0

        result = benchmark_runner._parse_sysbench_output(
            minimal_output, config, start_time, end_time, duration
        )

        # Should calculate TPS from total events and duration
        assert result.transactions_per_second == 50.0  # 250 events / 5 seconds
        assert result.latency_avg_ms == 20.0

    @pytest.mark.asyncio
    async def test_performance_metrics_collection(self, benchmark_runner, mock_sql_driver):
        """Test collection of performance metrics during benchmark."""
        # Mock database query results
        mock_sql_driver.execute_query.return_value = [
            (datetime.now(), 5, 1000, 0, 50000, 25000)
        ]

        metrics = await benchmark_runner._collect_performance_metrics()

        assert "timestamp" in metrics
        assert "active_connections" in metrics
        assert "total_transactions" in metrics
        assert "total_deadlocks" in metrics
        assert "total_blocks_accessed" in metrics
        assert "total_tuples_processed" in metrics
        assert metrics["active_connections"] == 5
        assert metrics["total_transactions"] == 1000
        assert metrics["total_deadlocks"] == 0
        assert metrics["total_blocks_accessed"] == 50000
        assert metrics["total_tuples_processed"] == 25000

    @pytest.mark.asyncio
    async def test_gaussdb_specific_metrics_collection(self, gaussdb_benchmark_runner, mock_gaussdb_driver):
        """Test collection of GaussDB-specific metrics."""
        # Mock GaussDB-specific query results
        mock_gaussdb_driver.execute_query.return_value = [
            (2, 500, 1500)
        ]

        metrics = await gaussdb_benchmark_runner._collect_gaussdb_specific_metrics()

        assert "gaussdb_connections" in metrics
        assert "dml_operations" in metrics
        assert "scan_operations" in metrics
        assert metrics["gaussdb_connections"] == 2
        assert metrics["dml_operations"] == 500
        assert metrics["scan_operations"] == 1500

    @pytest.mark.asyncio
    async def test_enhance_result_with_monitoring_data(self, benchmark_runner):
        """Test enhancement of results with monitoring data."""
        # Set up mock monitoring data
        benchmark_runner._performance_metrics = [
            {
                "timestamp": datetime.now(),
                "active_connections": 4,
                "total_deadlocks": 0
            },
            {
                "timestamp": datetime.now(),
                "active_connections": 6,
                "total_deadlocks": 1
            },
            {
                "timestamp": datetime.now(),
                "active_connections": 5,
                "total_deadlocks": 1
            }
        ]

        # Create a basic result
        from opengauss_mcp.benchmark.config import BenchmarkResult
        result = BenchmarkResult(
            benchmark_type=BenchmarkType.SYSBENCH,
            config={},
            start_time="2023-01-01T10:00:00",
            end_time="2023-01-01T10:01:00",
            duration_seconds=60.0,
            transactions_per_second=100.0,
            queries_per_second=400.0,
            latency_avg_ms=25.0
        )

        enhanced_result = await benchmark_runner._enhance_result_with_monitoring_data(result)

        assert enhanced_result.connections_used == 5  # Average of 4, 6, 5
        assert enhanced_result.deadlocks == 1  # 1 - 0 = 1 deadlock during test

    @pytest.mark.asyncio
    async def test_database_connection_validation(self, benchmark_runner, mock_sql_driver):
        """Test database connection validation."""
        # Test successful validation
        mock_sql_driver.execute_query.return_value = [(1,)]

        await benchmark_runner._validate_database_connection()  # Should not raise

        # Test failed validation
        mock_sql_driver.execute_query.return_value = None

        with pytest.raises(RuntimeError, match="Database connection validation failed"):
            await benchmark_runner._validate_database_connection()

    @pytest.mark.asyncio
    async def test_sysbench_config_adaptation_for_gaussdb(self, benchmark_tool):
        """Test Sysbench configuration adaptation for GaussDB."""
        config = SysbenchConfig(
            db_host="gaussdb-host",
            db_port=8000,
            db_user="gaussdb_user"
        )

        # Test with regular PostgreSQL driver (no adaptation needed)
        adapted_config = await benchmark_tool._adapt_sysbench_config_for_gaussdb(config)

        assert adapted_config.db_host == "gaussdb-host"
        assert adapted_config.db_port == 8000
        assert adapted_config.db_user == "gaussdb_user"

    @pytest.mark.asyncio
    async def test_sysbench_command_args_generation(self):
        """Test generation of Sysbench command arguments."""
        config = SysbenchConfig(
            test_type="oltp_read_only",
            table_size=50000,
            tables=2,
            threads=8,
            time=120,
            db_host="testhost",
            db_port=5433,
            db_user="testuser",
            db_password="testpass",
            db_name="testdb",
            report_interval=5,
            warmup_time=15,
            rate=100,
            extra_args=["--mysql-ignore-errors=1062"]
        )

        args = config.to_command_args()

        expected_args = [
            "--db-driver=pgsql",
            "--pgsql-host=testhost",
            "--pgsql-port=5433",
            "--pgsql-user=testuser",
            "--pgsql-password=testpass",
            "--pgsql-db=testdb",
            "--table_size=50000",
            "--tables=2",
            "--threads=8",
            "--time=120",
            "--report-interval=5",
            "--warmup-time=15",
            "--rate=100",
            "--mysql-ignore-errors=1062"
        ]

        for expected_arg in expected_args:
            assert expected_arg in args

    @pytest.mark.asyncio
    async def test_sysbench_error_handling(self, benchmark_runner):
        """Test error handling during Sysbench execution."""
        config = SysbenchConfig()

        # Test sysbench not available
        with patch.object(benchmark_runner, '_check_sysbench_available', return_value=False):
            with pytest.raises(RuntimeError, match="Sysbench is not installed"):
                await benchmark_runner.run_sysbench(config)

        # Test database validation failure
        with patch.object(benchmark_runner, '_check_sysbench_available', return_value=True):
            with patch.object(benchmark_runner, '_validate_database_connection', side_effect=RuntimeError("DB error")):
                with pytest.raises(RuntimeError, match="DB error"):
                    await benchmark_runner.run_sysbench(config)

    def test_sysbench_availability_check_with_timeout(self, benchmark_runner):
        """Test Sysbench availability check with timeout handling."""
        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("sysbench", 10)
            assert benchmark_runner._check_sysbench_available() is False

    def test_sysbench_availability_check_with_file_not_found(self, benchmark_runner):
        """Test Sysbench availability check when command not found."""
        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = FileNotFoundError()
            assert benchmark_runner._check_sysbench_available() is False

    @pytest.mark.asyncio
    async def test_full_sysbench_workflow_mock(self, benchmark_runner, mock_sql_driver, sample_sysbench_output):
        """Test full Sysbench workflow with mocked components."""
        config = SysbenchConfig(time=10, threads=2)

        # Set up mock monitoring data
        benchmark_runner._performance_metrics = [
            {
                "timestamp": datetime.now(),
                "active_connections": 4,
                "total_deadlocks": 0
            },
            {
                "timestamp": datetime.now(),
                "active_connections": 4,
                "total_deadlocks": 0
            }
        ]

        # Mock all the subprocess calls
        with patch.object(benchmark_runner, '_check_sysbench_available', return_value=True):
            with patch.object(benchmark_runner, '_validate_database_connection'):
                with patch.object(benchmark_runner, '_prepare_sysbench_database'):
                    with patch.object(benchmark_runner, '_execute_sysbench', return_value=sample_sysbench_output):
                        with patch.object(benchmark_runner, '_cleanup_sysbench_database'):
                            with patch.object(benchmark_runner, '_start_performance_monitoring'):
                                with patch.object(benchmark_runner, '_stop_performance_monitoring'):
                                    # Mock performance metrics collection
                                    mock_sql_driver.execute_query.return_value = [
                                        (datetime.now(), 4, 500, 0, 10000, 5000)
                                    ]

                                    result = await benchmark_runner.run_sysbench(config)

                                    assert result.benchmark_type == BenchmarkType.SYSBENCH
                                    assert result.transactions_per_second == 100.0
                                    assert result.queries_per_second == 2000.0
                                    assert result.latency_avg_ms == 39.5
                                    assert result.errors == 0
                                    assert isinstance(result.connections_used, int)
                                    assert result.connections_used == 4

    @pytest.mark.asyncio
    async def test_sysbench_cleanup_on_failure(self, benchmark_runner, mock_sql_driver):
        """Test that cleanup is attempted even when benchmark fails."""
        config = SysbenchConfig()

        with patch.object(benchmark_runner, '_check_sysbench_available', return_value=True):
            with patch.object(benchmark_runner, '_validate_database_connection'):
                with patch.object(benchmark_runner, '_prepare_sysbench_database'):
                    with patch.object(benchmark_runner, '_execute_sysbench', side_effect=RuntimeError("Execution failed")):
                        with patch.object(benchmark_runner, '_cleanup_sysbench_database') as mock_cleanup:
                            with pytest.raises(RuntimeError, match="Execution failed"):
                                await benchmark_runner.run_sysbench(config)

                            # Verify cleanup was called even on failure
                            mock_cleanup.assert_called_once()

    @pytest.mark.asyncio
    async def test_sysbench_cleanup_failure_handling(self, benchmark_runner, mock_sql_driver):
        """Test handling of cleanup failures."""
        config = SysbenchConfig()

        with patch.object(benchmark_runner, '_check_sysbench_available', return_value=True):
            with patch.object(benchmark_runner, '_validate_database_connection'):
                with patch.object(benchmark_runner, '_prepare_sysbench_database'):
                    with patch.object(benchmark_runner, '_execute_sysbench', side_effect=RuntimeError("Execution failed")):
                        with patch.object(benchmark_runner, '_cleanup_sysbench_database', side_effect=RuntimeError("Cleanup failed")):
                            # Should still raise the original execution error, not the cleanup error
                            with pytest.raises(RuntimeError, match="Execution failed"):
                                await benchmark_runner.run_sysbench(config)
