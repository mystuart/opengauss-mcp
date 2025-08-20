"""
Unit tests for the benchmark framework components.
"""

from datetime import datetime
from unittest.mock import AsyncMock
from unittest.mock import Mock
from unittest.mock import patch

import pytest

from postgres_mcp.benchmark import BenchmarkResult
from postgres_mcp.benchmark import BenchmarkRunner
from postgres_mcp.benchmark import BenchmarkTool
from postgres_mcp.benchmark import BenchmarkType
from postgres_mcp.benchmark import SysbenchConfig
from postgres_mcp.benchmark import TpccConfig
from postgres_mcp.sql.sql_driver import SqlDriver


class TestSysbenchConfig:
    """Test SysbenchConfig data model."""

    def test_default_config(self):
        """Test default configuration values."""
        config = SysbenchConfig()

        assert config.test_type == "oltp_read_write"
        assert config.table_size == 100000
        assert config.tables == 4
        assert config.threads == 4
        assert config.time == 60
        assert config.db_driver == "pgsql"
        assert config.db_host == "localhost"
        assert config.db_port == 5432

    def test_custom_config(self):
        """Test custom configuration values."""
        config = SysbenchConfig(
            test_type="oltp_read_only",
            table_size=50000,
            threads=8,
            time=120
        )

        assert config.test_type == "oltp_read_only"
        assert config.table_size == 50000
        assert config.threads == 8
        assert config.time == 120

    def test_to_command_args(self):
        """Test conversion to command arguments."""
        config = SysbenchConfig(
            db_host="testhost",
            db_port=5433,
            db_user="testuser",
            db_password="testpass",
            table_size=10000,
            threads=2
        )

        args = config.to_command_args()

        assert "--db-driver=pgsql" in args
        assert "--pgsql-host=testhost" in args
        assert "--pgsql-port=5433" in args
        assert "--pgsql-user=testuser" in args
        assert "--pgsql-password=testpass" in args
        assert "--table_size=10000" in args
        assert "--threads=2" in args


class TestTpccConfig:
    """Test TpccConfig data model."""

    def test_default_config(self):
        """Test default configuration values."""
        config = TpccConfig()

        assert config.warehouses == 4
        assert config.duration == 300
        assert config.connections == 4
        assert config.ramp_up_time == 30
        assert config.new_order_pct == 45.0
        assert config.payment_pct == 43.0

    def test_to_command_args(self):
        """Test conversion to command arguments."""
        config = TpccConfig(
            db_host="testhost",
            db_port=5433,
            warehouses=2,
            duration=60
        )

        args = config.to_command_args()

        assert "--host=testhost" in args
        assert "--port=5433" in args
        assert "--warehouses=2" in args
        assert "--duration=60" in args


class TestBenchmarkResult:
    """Test BenchmarkResult data model."""

    def test_result_creation(self):
        """Test benchmark result creation."""
        result = BenchmarkResult(
            benchmark_type=BenchmarkType.SYSBENCH,
            config={"test": "value"},
            start_time="2023-01-01T10:00:00",
            end_time="2023-01-01T10:01:00",
            duration_seconds=60.0,
            transactions_per_second=100.5,
            queries_per_second=400.2,
            latency_avg_ms=25.5
        )

        assert result.benchmark_type == BenchmarkType.SYSBENCH
        assert result.transactions_per_second == 100.5
        assert result.queries_per_second == 400.2
        assert result.latency_avg_ms == 25.5

    def test_to_dict(self):
        """Test conversion to dictionary."""
        result = BenchmarkResult(
            benchmark_type=BenchmarkType.SYSBENCH,
            config={"test": "value"},
            start_time="2023-01-01T10:00:00",
            end_time="2023-01-01T10:01:00",
            duration_seconds=60.0,
            transactions_per_second=100.5,
            queries_per_second=400.2,
            latency_avg_ms=25.5
        )

        result_dict = result.to_dict()

        assert result_dict["benchmark_type"] == "sysbench"
        assert result_dict["transactions_per_second"] == 100.5
        assert result_dict["config"] == {"test": "value"}


class TestBenchmarkRunner:
    """Test BenchmarkRunner functionality."""

    @pytest.fixture
    def mock_sql_driver(self):
        """Create a mock SQL driver."""
        driver = Mock(spec=SqlDriver)
        driver.execute_query = AsyncMock()
        return driver

    @pytest.fixture
    def benchmark_runner(self, mock_sql_driver):
        """Create a benchmark runner with mock driver."""
        return BenchmarkRunner(mock_sql_driver)

    def test_check_sysbench_available_true(self, benchmark_runner):
        """Test sysbench availability check when available."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value.returncode = 0
            assert benchmark_runner._check_sysbench_available() is True

    def test_check_sysbench_available_false(self, benchmark_runner):
        """Test sysbench availability check when not available."""
        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = FileNotFoundError()
            assert benchmark_runner._check_sysbench_available() is False

    def test_parse_sysbench_output(self, benchmark_runner):
        """Test parsing of sysbench output."""
        sample_output = """
        sysbench 1.0.20 (using system LuaJIT 2.1.0-beta3)
        
        Running the test with following options:
        Number of threads: 4
        
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
        """

        config = SysbenchConfig()
        start_time = datetime.now()
        end_time = datetime.now()
        duration = 10.0

        result = benchmark_runner._parse_sysbench_output(
            sample_output, config, start_time, end_time, duration
        )

        assert result.benchmark_type == BenchmarkType.SYSBENCH
        assert result.transactions_per_second == 100.0
        assert result.queries_per_second == 2000.0
        assert result.latency_avg_ms == 39.5
        assert result.latency_95th_ms == 75.0
        assert result.latency_99th_ms == 120.0

    @pytest.mark.asyncio
    async def test_collect_performance_metrics(self, benchmark_runner, mock_sql_driver):
        """Test performance metrics collection."""
        # Mock database query result with all expected columns
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


class TestBenchmarkTool:
    """Test BenchmarkTool functionality."""

    @pytest.fixture
    def mock_sql_driver(self):
        """Create a mock SQL driver."""
        driver = Mock(spec=SqlDriver)
        driver.execute_query = AsyncMock()
        return driver

    @pytest.fixture
    def benchmark_tool(self, mock_sql_driver):
        """Create a benchmark tool with mock driver."""
        return BenchmarkTool(mock_sql_driver)

    def test_initialization(self, benchmark_tool, mock_sql_driver):
        """Test benchmark tool initialization."""
        assert benchmark_tool.sql_driver == mock_sql_driver
        assert isinstance(benchmark_tool.benchmark_runner, BenchmarkRunner)
        assert benchmark_tool._is_gaussdb is False

    @pytest.mark.asyncio
    async def test_analyze_sysbench_results(self, benchmark_tool):
        """Test sysbench results analysis."""
        result = BenchmarkResult(
            benchmark_type=BenchmarkType.SYSBENCH,
            config={},
            start_time="2023-01-01T10:00:00",
            end_time="2023-01-01T10:01:00",
            duration_seconds=60.0,
            transactions_per_second=1500.0,
            queries_per_second=6000.0,
            latency_avg_ms=8.5,
            latency_95th_ms=15.0,
            latency_99th_ms=25.0
        )

        analysis = await benchmark_tool._analyze_sysbench_results(result)

        assert "Sysbench Performance Summary" in analysis
        assert "1500.00" in analysis  # TPS
        assert "6000.00" in analysis  # QPS
        assert "8.50" in analysis     # Avg latency
        assert "Excellent throughput" in analysis
        assert "Excellent response times" in analysis

    @pytest.mark.asyncio
    async def test_generate_sysbench_recommendations(self, benchmark_tool):
        """Test sysbench recommendations generation."""
        # Low performance result
        result = BenchmarkResult(
            benchmark_type=BenchmarkType.SYSBENCH,
            config={},
            start_time="2023-01-01T10:00:00",
            end_time="2023-01-01T10:01:00",
            duration_seconds=60.0,
            transactions_per_second=50.0,  # Low TPS
            queries_per_second=200.0,
            latency_avg_ms=150.0  # High latency
        )

        recommendations = await benchmark_tool._generate_sysbench_recommendations(result)

        assert len(recommendations) > 0
        assert any("shared_buffers" in rec for rec in recommendations)
        assert any("I/O bottlenecks" in rec for rec in recommendations)
        assert any("work_mem" in rec for rec in recommendations)

    def test_compare_same_type_results(self, benchmark_tool):
        """Test comparison of same benchmark type results."""
        results = [
            BenchmarkResult(
                benchmark_type=BenchmarkType.SYSBENCH,
                config={},
                start_time="2023-01-01T10:00:00",
                end_time="2023-01-01T10:01:00",
                duration_seconds=60.0,
                transactions_per_second=100.0,
                queries_per_second=400.0,
                latency_avg_ms=50.0
            ),
            BenchmarkResult(
                benchmark_type=BenchmarkType.SYSBENCH,
                config={},
                start_time="2023-01-01T10:00:00",
                end_time="2023-01-01T10:01:00",
                duration_seconds=60.0,
                transactions_per_second=200.0,
                queries_per_second=800.0,
                latency_avg_ms=25.0
            )
        ]

        comparison = benchmark_tool._compare_same_type_results(results)

        assert comparison["best_tps"] == 200.0
        assert comparison["worst_tps"] == 100.0
        assert comparison["tps_improvement_pct"] == 100.0  # 100% improvement
        assert comparison["best_latency"] == 25.0
        assert comparison["worst_latency"] == 50.0
        assert comparison["latency_improvement_pct"] == 50.0  # 50% improvement
        assert comparison["results_count"] == 2

    @pytest.mark.asyncio
    async def test_compare_benchmarks(self, benchmark_tool):
        """Test benchmark comparison functionality."""
        results = [
            BenchmarkResult(
                benchmark_type=BenchmarkType.SYSBENCH,
                config={},
                start_time="2023-01-01T10:00:00",
                end_time="2023-01-01T10:01:00",
                duration_seconds=60.0,
                transactions_per_second=100.0,
                queries_per_second=400.0,
                latency_avg_ms=50.0
            ),
            BenchmarkResult(
                benchmark_type=BenchmarkType.SYSBENCH,
                config={},
                start_time="2023-01-01T10:00:00",
                end_time="2023-01-01T10:01:00",
                duration_seconds=60.0,
                transactions_per_second=200.0,
                queries_per_second=800.0,
                latency_avg_ms=25.0
            )
        ]

        comparison = await benchmark_tool.compare_benchmarks(results)

        assert comparison["summary"]["total_results"] == 2
        assert "sysbench" in comparison["summary"]["benchmark_types"]
        assert "sysbench" in comparison["comparisons"]
        assert comparison["comparisons"]["sysbench"]["tps_improvement_pct"] == 100.0

    @pytest.mark.asyncio
    async def test_compare_benchmarks_empty(self, benchmark_tool):
        """Test benchmark comparison with empty results."""
        comparison = await benchmark_tool.compare_benchmarks([])
        assert "error" in comparison
        assert comparison["error"] == "No results to compare"

    @pytest.mark.asyncio
    async def test_compare_benchmarks_single_result(self, benchmark_tool):
        """Test benchmark comparison with single result."""
        results = [
            BenchmarkResult(
                benchmark_type=BenchmarkType.SYSBENCH,
                config={},
                start_time="2023-01-01T10:00:00",
                end_time="2023-01-01T10:01:00",
                duration_seconds=60.0,
                transactions_per_second=100.0,
                queries_per_second=400.0,
                latency_avg_ms=50.0
            )
        ]

        comparison = await benchmark_tool.compare_benchmarks(results)
        assert "error" in comparison
        assert comparison["error"] == "Need at least 2 results to compare"
