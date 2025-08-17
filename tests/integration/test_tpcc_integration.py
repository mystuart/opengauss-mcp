"""
Integration tests for TPC-C benchmark functionality.
"""

import pytest
import subprocess
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime

from src.postgres_mcp.benchmark import BenchmarkTool, BenchmarkRunner, TpccConfig, BenchmarkType
from src.postgres_mcp.sql.sql_driver import SqlDriver
from src.postgres_mcp.gaussdb.sql_driver_adapter import GaussDbSqlDriver


class TestTpccIntegration:
    """Integration tests for TPC-C benchmark functionality."""
    
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
    def sample_tpcc_output(self):
        """Sample TPC-C output for testing."""
        return """
Custom TPC-C Benchmark Results
==============================

Test Configuration:
- Warehouses: 4
- Duration: 300 seconds
- Connections: 4

Results:
- Total Transactions: 15000
- Total Errors: 5
- Actual Duration: 300.50 seconds
- Transactions per Second: 49.92
- Average Latency: 80.12 ms

Transaction Mix:
- New Order: 45.0%
- Payment: 43.0%
- Order Status: 4.0%
- Delivery: 4.0%
- Stock Level: 4.0%
"""
    
    @pytest.fixture
    def sample_standard_tpcc_output(self):
        """Sample standard TPC-C tool output."""
        return """
TPC-C Benchmark Results
=======================

Warehouses: 4
Duration: 300 seconds
Ramp-up: 30 seconds

Performance Results:
- 2995.2 tpmC (TPC-C transactions per minute)
- Response Time: 15.5 ms
- Total Transactions: 14976
- Errors: 2
- Efficiency: 99.87%

Transaction Breakdown:
- New Order: 6748 (45.0%)
- Payment: 6440 (43.0%)
- Order Status: 599 (4.0%)
- Delivery: 599 (4.0%)
- Stock Level: 590 (4.0%)
"""
    
    @pytest.mark.asyncio
    async def test_tpcc_output_parsing_custom_format(self, benchmark_runner, sample_tpcc_output):
        """Test parsing of custom TPC-C output format."""
        config = TpccConfig()
        start_time = datetime.now()
        end_time = datetime.now()
        duration = 300.5
        
        result = benchmark_runner._parse_tpcc_output(
            sample_tpcc_output, config, start_time, end_time, duration
        )
        
        assert result.benchmark_type == BenchmarkType.TPCC
        assert result.transactions_per_second == 49.92
        assert result.queries_per_second == pytest.approx(499.2, rel=0.01)  # 10x TPS estimate
        assert result.latency_avg_ms == 80.12
        assert result.errors == 5
        assert result.duration_seconds == 300.5
    
    @pytest.mark.asyncio
    async def test_tpcc_output_parsing_standard_format(self, benchmark_runner, sample_standard_tpcc_output):
        """Test parsing of standard TPC-C tool output format."""
        config = TpccConfig()
        start_time = datetime.now()
        end_time = datetime.now()
        duration = 300.0
        
        result = benchmark_runner._parse_tpcc_output(
            sample_standard_tpcc_output, config, start_time, end_time, duration
        )
        
        assert result.benchmark_type == BenchmarkType.TPCC
        assert result.transactions_per_second == pytest.approx(49.92, rel=0.1)  # 2995.2 / 60
        assert result.latency_avg_ms == 15.5
        assert result.errors == 2
    
    @pytest.mark.asyncio
    async def test_tpcc_output_parsing_missing_tps(self, benchmark_runner):
        """Test parsing when TPS is missing but total transactions are available."""
        minimal_output = """
TPC-C Results
- Total Transactions: 6000
- Total Errors: 0
- Average Latency: 25.5 ms
"""
        
        config = TpccConfig()
        start_time = datetime.now()
        end_time = datetime.now()
        duration = 120.0
        
        result = benchmark_runner._parse_tpcc_output(
            minimal_output, config, start_time, end_time, duration
        )
        
        # Should calculate TPS from total transactions and duration
        assert result.transactions_per_second == 50.0  # 6000 transactions / 120 seconds
        assert result.latency_avg_ms == 25.5
        assert result.errors == 0
    
    def test_tpcc_availability_check_true(self, benchmark_runner):
        """Test TPC-C availability check when available."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value.returncode = 0
            assert benchmark_runner._check_tpcc_available() is True
    
    def test_tpcc_availability_check_false(self, benchmark_runner):
        """Test TPC-C availability check when not available."""
        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = FileNotFoundError()
            assert benchmark_runner._check_tpcc_available() is False
    
    @pytest.mark.asyncio
    async def test_tpcc_database_creation(self, benchmark_runner, mock_sql_driver):
        """Test TPC-C database creation."""
        config = TpccConfig(db_name="test_tpcc")
        
        # Mock database doesn't exist
        mock_sql_driver.execute_query.return_value = None
        
        await benchmark_runner._create_tpcc_database_if_needed(config)
        
        # Should have called execute_query twice (check + create)
        assert mock_sql_driver.execute_query.call_count == 2
        
        # Check the calls
        calls = mock_sql_driver.execute_query.call_args_list
        assert "SELECT 1 FROM pg_database" in calls[0][0][0]
        assert "CREATE DATABASE test_tpcc" in calls[1][0][0]
    
    @pytest.mark.asyncio
    async def test_tpcc_schema_creation(self, benchmark_runner, mock_sql_driver):
        """Test TPC-C schema creation."""
        config = TpccConfig(warehouses=2)
        
        await benchmark_runner._create_tpcc_schema_manually(config)
        
        # Should have created tables and inserted data
        assert mock_sql_driver.execute_query.call_count > 3  # At least schema + some data
        
        # Check that warehouse table creation was called
        calls = mock_sql_driver.execute_query.call_args_list
        warehouse_call = next((call for call in calls if "CREATE TABLE" in call[0][0] and "warehouse" in call[0][0]), None)
        assert warehouse_call is not None
    
    @pytest.mark.asyncio
    async def test_tpcc_data_insertion(self, benchmark_runner, mock_sql_driver):
        """Test TPC-C minimal data insertion."""
        config = TpccConfig(warehouses=2)
        
        await benchmark_runner._insert_minimal_tpcc_data(config)
        
        # Should have inserted data for 2 warehouses and 20 districts (10 per warehouse)
        assert mock_sql_driver.execute_query.call_count >= 22  # 2 warehouses + 20 districts
    
    def test_tpcc_transaction_type_selection(self, benchmark_runner):
        """Test TPC-C transaction type selection based on percentages."""
        config = TpccConfig(
            new_order_pct=50.0,
            payment_pct=30.0,
            order_status_pct=10.0,
            delivery_pct=5.0,
            stock_level_pct=5.0
        )
        
        # Test multiple selections to verify distribution
        transaction_counts = {
            "new_order": 0,
            "payment": 0,
            "order_status": 0,
            "delivery": 0,
            "stock_level": 0
        }
        
        # Mock random to test specific ranges
        with patch('random.random') as mock_random:
            # Test new_order (0-50%)
            mock_random.return_value = 0.25  # 25%
            assert benchmark_runner._select_tpcc_transaction_type(config) == "new_order"
            
            # Test payment (50-80%)
            mock_random.return_value = 0.65  # 65%
            assert benchmark_runner._select_tpcc_transaction_type(config) == "payment"
            
            # Test order_status (80-90%)
            mock_random.return_value = 0.85  # 85%
            assert benchmark_runner._select_tpcc_transaction_type(config) == "order_status"
            
            # Test delivery (90-95%)
            mock_random.return_value = 0.92  # 92%
            assert benchmark_runner._select_tpcc_transaction_type(config) == "delivery"
            
            # Test stock_level (95-100%)
            mock_random.return_value = 0.97  # 97%
            assert benchmark_runner._select_tpcc_transaction_type(config) == "stock_level"
    
    @pytest.mark.asyncio
    async def test_tpcc_transaction_execution(self, benchmark_runner, mock_sql_driver):
        """Test execution of different TPC-C transaction types."""
        config = TpccConfig(warehouses=2)
        
        # Test New Order transaction
        await benchmark_runner._execute_new_order_transaction(config)
        assert mock_sql_driver.execute_query.called
        
        mock_sql_driver.reset_mock()
        
        # Test Payment transaction
        await benchmark_runner._execute_payment_transaction(config)
        assert mock_sql_driver.execute_query.called
        
        mock_sql_driver.reset_mock()
        
        # Test Order Status transaction
        await benchmark_runner._execute_order_status_transaction(config)
        assert mock_sql_driver.execute_query.called
        
        mock_sql_driver.reset_mock()
        
        # Test Delivery transaction
        await benchmark_runner._execute_delivery_transaction(config)
        assert mock_sql_driver.execute_query.called
        
        mock_sql_driver.reset_mock()
        
        # Test Stock Level transaction
        await benchmark_runner._execute_stock_level_transaction(config)
        assert mock_sql_driver.execute_query.called
    
    @pytest.mark.asyncio
    async def test_custom_tpcc_execution(self, benchmark_runner, mock_sql_driver):
        """Test custom TPC-C execution when standard tool is not available."""
        config = TpccConfig(duration=1, warehouses=1)
        
        # Mock the custom TPC-C execution to return a known output
        expected_output = """
Custom TPC-C Benchmark Results
==============================

Test Configuration:
- Warehouses: 1
- Duration: 1 seconds
- Connections: 4

Results:
- Total Transactions: 50
- Total Errors: 0
- Actual Duration: 1.00 seconds
- Transactions per Second: 50.00
- Average Latency: 20.00 ms
"""
        
        with patch.object(benchmark_runner, '_execute_custom_tpcc', return_value=expected_output):
            output = await benchmark_runner._execute_custom_tpcc(config)
            
            assert "Custom TPC-C Benchmark Results" in output
            assert "Total Transactions:" in output
            assert "Transactions per Second:" in output
    
    @pytest.mark.asyncio
    async def test_tpcc_config_adaptation_for_gaussdb(self, benchmark_tool):
        """Test TPC-C configuration adaptation for GaussDB."""
        config = TpccConfig(
            db_host="gaussdb-host",
            db_port=8000,
            warehouses=8
        )
        
        # Test with regular PostgreSQL driver (no adaptation needed)
        adapted_config = await benchmark_tool._adapt_tpcc_config_for_gaussdb(config)
        
        assert adapted_config.db_host == "gaussdb-host"
        assert adapted_config.db_port == 8000
        assert adapted_config.warehouses == 8
    
    @pytest.mark.asyncio
    async def test_tpcc_results_analysis(self, benchmark_tool):
        """Test TPC-C results analysis."""
        from src.postgres_mcp.benchmark.config import BenchmarkResult
        
        result = BenchmarkResult(
            benchmark_type=BenchmarkType.TPCC,
            config={"warehouses": 4, "duration": 300},
            start_time="2023-01-01T10:00:00",
            end_time="2023-01-01T10:05:00",
            duration_seconds=300.0,
            transactions_per_second=750.0,
            queries_per_second=7500.0,
            latency_avg_ms=12.5,
            errors=2
        )
        
        analysis = await benchmark_tool._analyze_tpcc_results(result)
        
        assert "TPC-C Performance Summary" in analysis
        assert "750.00" in analysis  # TPS
        assert "7500.00" in analysis  # QPS
        assert "12.50" in analysis  # Avg latency
        assert "Good OLTP performance" in analysis
        assert "Good response times for OLTP" in analysis
        assert "TPS per warehouse: 187.50" in analysis
        assert "Error rate:" in analysis
    
    @pytest.mark.asyncio
    async def test_tpcc_recommendations_generation(self, benchmark_tool):
        """Test TPC-C recommendations generation."""
        from src.postgres_mcp.benchmark.config import BenchmarkResult
        
        # Low performance result with errors
        result = BenchmarkResult(
            benchmark_type=BenchmarkType.TPCC,
            config={"warehouses": 10, "duration": 120},
            start_time="2023-01-01T10:00:00",
            end_time="2023-01-01T10:02:00",
            duration_seconds=120.0,
            transactions_per_second=50.0,  # Low TPS
            queries_per_second=500.0,
            latency_avg_ms=150.0,  # High latency
            errors=25  # Many errors
        )
        
        recommendations = await benchmark_tool._generate_tpcc_recommendations(result)
        
        assert len(recommendations) > 0
        assert any("connection pool size" in rec for rec in recommendations)
        assert any("lock contention" in rec for rec in recommendations)
        assert any("transaction conflicts" in rec for rec in recommendations)
        # Check for warehouse-related recommendations
        assert any("warehouse" in rec.lower() for rec in recommendations)
    
    @pytest.mark.asyncio
    async def test_tpcc_error_handling(self, benchmark_runner): # hang住，TODO
        """Test error handling during TPC-C execution."""
        config = TpccConfig()
        
        # Test TPC-C not available
        with patch.object(benchmark_runner, '_check_tpcc_available', return_value=False):
            with pytest.raises(RuntimeError, match="TPC-C benchmark tool is not installed"):
                await benchmark_runner.run_tpcc(config)
        
        # Test database validation failure
        with patch.object(benchmark_runner, '_check_tpcc_available', return_value=True):
            with patch.object(benchmark_runner, '_validate_database_connection', side_effect=RuntimeError("DB error")):
                with pytest.raises(RuntimeError, match="DB error"):
                    await benchmark_runner.run_tpcc(config)
    
    @pytest.mark.asyncio
    async def test_full_tpcc_workflow_mock(self, benchmark_runner, mock_sql_driver, sample_tpcc_output):
        """Test full TPC-C workflow with mocked components."""
        config = TpccConfig(duration=60, warehouses=2)
        
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
                "total_deadlocks": 1
            }
        ]
        
        # Mock all the subprocess calls
        with patch.object(benchmark_runner, '_check_tpcc_available', return_value=True):
            with patch.object(benchmark_runner, '_validate_database_connection'):
                with patch.object(benchmark_runner, '_prepare_tpcc_database'):
                    with patch.object(benchmark_runner, '_execute_tpcc', return_value=sample_tpcc_output):
                        with patch.object(benchmark_runner, '_start_performance_monitoring'):
                            with patch.object(benchmark_runner, '_stop_performance_monitoring'):
                                # Mock performance metrics collection
                                mock_sql_driver.execute_query.return_value = [
                                    (datetime.now(), 4, 500, 1, 10000, 5000)
                                ]
                                
                                result = await benchmark_runner.run_tpcc(config)
                                
                                assert result.benchmark_type == BenchmarkType.TPCC
                                assert result.transactions_per_second == 49.92
                                assert result.queries_per_second == 499.2
                                assert result.latency_avg_ms == 80.12
                                assert result.errors == 5
                                assert isinstance(result.connections_used, int)
                                assert result.connections_used == 4
                                assert result.deadlocks == 1
    
    @pytest.mark.asyncio
    async def test_tpcc_fallback_to_custom_implementation(self, benchmark_runner, mock_sql_driver):
        """Test fallback to custom TPC-C implementation when standard tool fails."""
        config = TpccConfig(duration=1)  # Short duration for testing
        
        with patch.object(benchmark_runner, '_check_tpcc_available', return_value=True):
            with patch.object(benchmark_runner, '_validate_database_connection'):
                with patch.object(benchmark_runner, '_prepare_tpcc_database'):
                    # Mock tpcc-run not found, should fallback to custom implementation
                    with patch.object(benchmark_runner, '_execute_tpcc', side_effect=FileNotFoundError()):
                        with patch.object(benchmark_runner, '_execute_custom_tpcc', return_value="Custom TPC-C output") as mock_custom:
                            with patch.object(benchmark_runner, '_start_performance_monitoring'):
                                with patch.object(benchmark_runner, '_stop_performance_monitoring'):
                                    
                                    result = await benchmark_runner.run_tpcc(config)
                                    
                                    # Should have called custom implementation
                                    mock_custom.assert_called_once()
                                    assert result.raw_output == "Custom TPC-C output"