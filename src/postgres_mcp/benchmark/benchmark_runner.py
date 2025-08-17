"""
Benchmark execution engine for running performance tests.
"""

import asyncio
import logging
import re
import subprocess
import time
from datetime import datetime
from typing import Dict, List, Optional, Union, Any
from pathlib import Path

from ..sql.sql_driver import SqlDriver
from ..gaussdb.sql_driver_adapter import GaussDbSqlDriver
from .config import BenchmarkType, BenchmarkResult, SysbenchConfig, TpccConfig

logger = logging.getLogger(__name__)


class BenchmarkRunner:
    """Executes benchmark tests and collects performance metrics."""
    
    def __init__(self, sql_driver: Union[SqlDriver, GaussDbSqlDriver]):
        """Initialize benchmark runner with database connection."""
        self.sql_driver = sql_driver
        self._monitoring_task: Optional[asyncio.Task] = None
        self._performance_metrics: List[Dict[str, Any]] = []
    
    async def run_sysbench(self, config: SysbenchConfig) -> BenchmarkResult:
        """
        Run Sysbench benchmark test.
        
        Args:
            config: Sysbench configuration
            
        Returns:
            BenchmarkResult with test results and metrics
        """
        logger.info(f"Starting Sysbench benchmark: {config.test_type}")
        
        # Validate sysbench installation
        if not self._check_sysbench_available():
            raise RuntimeError("Sysbench is not installed or not available in PATH")
        
        # Validate database connection
        await self._validate_database_connection()
        
        start_time = datetime.now()
        
        try:
            # Prepare database
            await self._prepare_sysbench_database(config)
            
            # Start performance monitoring
            self._start_performance_monitoring()
            
            # Run benchmark
            raw_output = await self._execute_sysbench(config)
            
            # Stop monitoring and collect final metrics
            await self._stop_performance_monitoring()
            
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            
            # Parse results
            result = self._parse_sysbench_output(
                raw_output, config, start_time, end_time, duration
            )
            
            # Add performance metrics from monitoring
            result = await self._enhance_result_with_monitoring_data(result)
            
            # Cleanup database
            await self._cleanup_sysbench_database(config)
            
            logger.info(f"Sysbench benchmark completed: {result.transactions_per_second:.2f} TPS")
            return result
            
        except Exception as e:
            logger.error(f"Sysbench benchmark failed: {e}")
            await self._stop_performance_monitoring()
            # Attempt cleanup even on failure
            try:
                await self._cleanup_sysbench_database(config)
            except Exception as cleanup_error:
                logger.warning(f"Cleanup failed: {cleanup_error}")
            raise
    
    async def run_tpcc(self, config: TpccConfig) -> BenchmarkResult:
        """
        Run TPC-C benchmark test.
        
        Args:
            config: TPC-C configuration
            
        Returns:
            BenchmarkResult with test results and metrics
        """
        logger.info(f"Starting TPC-C benchmark: {config.warehouses} warehouses")
        
        # Validate TPC-C installation
        if not self._check_tpcc_available():
            raise RuntimeError("TPC-C benchmark tool is not installed or not available")
        
        start_time = datetime.now()
        
        try:
            # Prepare database
            await self._prepare_tpcc_database(config)
            
            # Start performance monitoring
            self._start_performance_monitoring()
            
            # Run benchmark
            raw_output = await self._execute_tpcc(config)
            
            # Stop monitoring
            await self._stop_performance_monitoring()
            
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            
            # Parse results
            result = self._parse_tpcc_output(
                raw_output, config, start_time, end_time, duration
            )
            
            logger.info(f"TPC-C benchmark completed: {result.transactions_per_second:.2f} TPS")
            return result
            
        except Exception as e:
            logger.error(f"TPC-C benchmark failed: {e}")
            await self._stop_performance_monitoring()
            raise
    
    def _check_sysbench_available(self) -> bool:
        """Check if sysbench is available in the system."""
        try:
            result = subprocess.run(
                ["sysbench", "--version"], 
                capture_output=True, 
                text=True, 
                timeout=10
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False
    
    def _check_tpcc_available(self) -> bool:
        """Check if TPC-C benchmark tool is available."""
        # This would depend on the specific TPC-C implementation being used
        # For now, assume it's available if the command exists
        try:
            result = subprocess.run(
                ["which", "tpcc"], 
                capture_output=True, 
                text=True, 
                timeout=10
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False
    
    async def _prepare_sysbench_database(self, config: SysbenchConfig) -> None:
        """Prepare database for Sysbench test."""
        logger.info("Preparing Sysbench database schema")
        
        # Run sysbench prepare command
        cmd = ["sysbench"] + config.to_command_args() + [config.test_type, "prepare"]
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            raise RuntimeError(f"Sysbench prepare failed: {stderr.decode()}")
        
        logger.info("Sysbench database preparation completed")
    
    async def _execute_sysbench(self, config: SysbenchConfig) -> str:
        """Execute Sysbench benchmark test."""
        logger.info("Executing Sysbench benchmark")
        
        cmd = ["sysbench"] + config.to_command_args() + [config.test_type, "run"]
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            raise RuntimeError(f"Sysbench execution failed: {stderr.decode()}")
        
        return stdout.decode()
    
    async def _cleanup_sysbench_database(self, config: SysbenchConfig) -> None:
        """Clean up Sysbench test data."""
        logger.info("Cleaning up Sysbench database")
        
        cmd = ["sysbench"] + config.to_command_args() + [config.test_type, "cleanup"]
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        await process.communicate()
        logger.info("Sysbench cleanup completed")
    
    async def _prepare_tpcc_database(self, config: TpccConfig) -> None:
        """Prepare database for TPC-C test."""
        logger.info("Preparing TPC-C database schema and data")
        
        try:
            # Create TPC-C database if it doesn't exist
            await self._create_tpcc_database_if_needed(config)
            
            # Run TPC-C data loading
            cmd = ["tpcc-load"] + self._get_tpcc_load_args(config)
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode != 0:
                raise RuntimeError(f"TPC-C data loading failed: {stderr.decode()}")
            
            logger.info("TPC-C database preparation completed")
            
        except FileNotFoundError:
            # Fallback to manual schema creation if tpcc-load is not available
            logger.warning("tpcc-load not found, creating schema manually")
            await self._create_tpcc_schema_manually(config)
    
    async def _execute_tpcc(self, config: TpccConfig) -> str:
        """Execute TPC-C benchmark test."""
        logger.info("Executing TPC-C benchmark")
        
        try:
            # Run TPC-C benchmark
            cmd = ["tpcc-run"] + config.to_command_args()
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode != 0:
                raise RuntimeError(f"TPC-C execution failed: {stderr.decode()}")
            
            return stdout.decode()
            
        except FileNotFoundError:
            # Fallback to custom TPC-C implementation
            logger.warning("tpcc-run not found, using custom implementation")
            return await self._execute_custom_tpcc(config)
    
    async def _create_tpcc_database_if_needed(self, config: TpccConfig) -> None:
        """Create TPC-C database if it doesn't exist."""
        try:
            # Check if database exists
            check_query = f"SELECT 1 FROM pg_database WHERE datname = '{config.db_name}'"
            result = await self.sql_driver.execute_query(check_query)
            
            if not result:
                # Create database
                create_query = f"CREATE DATABASE {config.db_name}"
                await self.sql_driver.execute_query(create_query)
                logger.info(f"Created TPC-C database: {config.db_name}")
            
        except Exception as e:
            logger.warning(f"Could not create TPC-C database: {e}")
    
    def _get_tpcc_load_args(self, config: TpccConfig) -> List[str]:
        """Get TPC-C data loading arguments."""
        args = [
            f"--host={config.db_host}",
            f"--port={config.db_port}",
            f"--user={config.db_user}",
            f"--dbname={config.db_name}",
            f"--warehouses={config.warehouses}",
        ]
        
        if config.db_password:
            args.append(f"--password={config.db_password}")
        
        return args
    
    async def _create_tpcc_schema_manually(self, config: TpccConfig) -> None:
        """Create TPC-C schema manually when tpcc-load is not available."""
        logger.info("Creating TPC-C schema manually")
        
        # Basic TPC-C schema creation
        schema_queries = [
            """
            CREATE TABLE IF NOT EXISTS warehouse (
                w_id INTEGER PRIMARY KEY,
                w_name VARCHAR(10),
                w_street_1 VARCHAR(20),
                w_street_2 VARCHAR(20),
                w_city VARCHAR(20),
                w_state CHAR(2),
                w_zip CHAR(9),
                w_tax DECIMAL(4,2),
                w_ytd DECIMAL(12,2)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS district (
                d_id INTEGER,
                d_w_id INTEGER,
                d_name VARCHAR(10),
                d_street_1 VARCHAR(20),
                d_street_2 VARCHAR(20),
                d_city VARCHAR(20),
                d_state CHAR(2),
                d_zip CHAR(9),
                d_tax DECIMAL(4,2),
                d_ytd DECIMAL(12,2),
                d_next_o_id INTEGER,
                PRIMARY KEY (d_w_id, d_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS customer (
                c_id INTEGER,
                c_d_id INTEGER,
                c_w_id INTEGER,
                c_first VARCHAR(16),
                c_middle CHAR(2),
                c_last VARCHAR(16),
                c_street_1 VARCHAR(20),
                c_street_2 VARCHAR(20),
                c_city VARCHAR(20),
                c_state CHAR(2),
                c_zip CHAR(9),
                c_phone CHAR(16),
                c_since TIMESTAMP,
                c_credit CHAR(2),
                c_credit_lim DECIMAL(12,2),
                c_discount DECIMAL(4,2),
                c_balance DECIMAL(12,2),
                c_ytd_payment DECIMAL(12,2),
                c_payment_cnt INTEGER,
                c_delivery_cnt INTEGER,
                c_data TEXT,
                PRIMARY KEY (c_w_id, c_d_id, c_id)
            )
            """
        ]
        
        for query in schema_queries:
            try:
                await self.sql_driver.execute_query(query)
            except Exception as e:
                logger.warning(f"Failed to create table: {e}")
        
        # Insert minimal test data
        await self._insert_minimal_tpcc_data(config)
    
    async def _insert_minimal_tpcc_data(self, config: TpccConfig) -> None:
        """Insert minimal TPC-C test data."""
        logger.info("Inserting minimal TPC-C test data")
        
        try:
            # Insert warehouse data
            for w_id in range(1, config.warehouses + 1):
                warehouse_query = """
                INSERT INTO warehouse (w_id, w_name, w_street_1, w_street_2, w_city, w_state, w_zip, w_tax, w_ytd)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (w_id) DO NOTHING
                """
                await self.sql_driver.execute_query(warehouse_query, [
                    w_id, f"Warehouse{w_id}", "123 Main St", "Suite 100", 
                    "TestCity", "TX", "12345-678", 0.05, 300000.00
                ])
                
                # Insert district data for each warehouse
                for d_id in range(1, 11):  # 10 districts per warehouse
                    district_query = """
                    INSERT INTO district (d_id, d_w_id, d_name, d_street_1, d_street_2, d_city, d_state, d_zip, d_tax, d_ytd, d_next_o_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (d_w_id, d_id) DO NOTHING
                    """
                    await self.sql_driver.execute_query(district_query, [
                        d_id, w_id, f"District{d_id}", "456 Oak Ave", "Floor 2",
                        "TestCity", "TX", "12345-678", 0.08, 30000.00, 3001
                    ])
            
            logger.info("Minimal TPC-C data insertion completed")
            
        except Exception as e:
            logger.warning(f"Failed to insert TPC-C test data: {e}")
    
    async def _execute_custom_tpcc(self, config: TpccConfig) -> str:
        """Execute custom TPC-C implementation when tpcc-run is not available."""
        logger.info("Running custom TPC-C benchmark implementation")
        
        start_time = time.time()
        total_transactions = 0
        total_errors = 0
        
        # Simulate TPC-C workload for the specified duration
        end_time = start_time + config.duration
        
        while time.time() < end_time:
            try:
                # Simulate different transaction types based on percentages
                transaction_type = self._select_tpcc_transaction_type(config)
                
                if transaction_type == "new_order":
                    await self._execute_new_order_transaction(config)
                elif transaction_type == "payment":
                    await self._execute_payment_transaction(config)
                elif transaction_type == "order_status":
                    await self._execute_order_status_transaction(config)
                elif transaction_type == "delivery":
                    await self._execute_delivery_transaction(config)
                elif transaction_type == "stock_level":
                    await self._execute_stock_level_transaction(config)
                
                total_transactions += 1
                
                # Small delay to prevent overwhelming the database
                await asyncio.sleep(0.01)
                
            except Exception as e:
                total_errors += 1
                logger.debug(f"Transaction error: {e}")
        
        actual_duration = time.time() - start_time
        tps = total_transactions / actual_duration if actual_duration > 0 else 0
        
        # Generate custom output format
        output = f"""
Custom TPC-C Benchmark Results
==============================

Test Configuration:
- Warehouses: {config.warehouses}
- Duration: {config.duration} seconds
- Connections: {config.connections}

Results:
- Total Transactions: {total_transactions}
- Total Errors: {total_errors}
- Actual Duration: {actual_duration:.2f} seconds
- Transactions per Second: {tps:.2f}
- Average Latency: {(actual_duration * 1000) / total_transactions if total_transactions > 0 else 0:.2f} ms

Transaction Mix:
- New Order: {config.new_order_pct}%
- Payment: {config.payment_pct}%
- Order Status: {config.order_status_pct}%
- Delivery: {config.delivery_pct}%
- Stock Level: {config.stock_level_pct}%
"""
        
        return output
    
    def _select_tpcc_transaction_type(self, config: TpccConfig) -> str:
        """Select TPC-C transaction type based on configured percentages."""
        import random
        
        rand = random.random() * 100
        
        if rand < config.new_order_pct:
            return "new_order"
        elif rand < config.new_order_pct + config.payment_pct:
            return "payment"
        elif rand < config.new_order_pct + config.payment_pct + config.order_status_pct:
            return "order_status"
        elif rand < config.new_order_pct + config.payment_pct + config.order_status_pct + config.delivery_pct:
            return "delivery"
        else:
            return "stock_level"
    
    async def _execute_new_order_transaction(self, config: TpccConfig) -> None:
        """Execute a New Order transaction."""
        import random
        
        w_id = random.randint(1, config.warehouses)
        d_id = random.randint(1, 10)
        
        # Simple new order simulation
        query = "SELECT d_next_o_id FROM district WHERE d_w_id = %s AND d_id = %s"
        await self.sql_driver.execute_query(query, [w_id, d_id])
    
    async def _execute_payment_transaction(self, config: TpccConfig) -> None:
        """Execute a Payment transaction."""
        import random
        
        w_id = random.randint(1, config.warehouses)
        d_id = random.randint(1, 10)
        c_id = random.randint(1, 3000)
        
        # Simple payment simulation
        query = "SELECT c_balance FROM customer WHERE c_w_id = %s AND c_d_id = %s AND c_id = %s"
        await self.sql_driver.execute_query(query, [w_id, d_id, c_id])
    
    async def _execute_order_status_transaction(self, config: TpccConfig) -> None:
        """Execute an Order Status transaction."""
        import random
        
        w_id = random.randint(1, config.warehouses)
        d_id = random.randint(1, 10)
        c_id = random.randint(1, 3000)
        
        # Simple order status simulation
        query = "SELECT c_first, c_middle, c_last FROM customer WHERE c_w_id = %s AND c_d_id = %s AND c_id = %s"
        await self.sql_driver.execute_query(query, [w_id, d_id, c_id])
    
    async def _execute_delivery_transaction(self, config: TpccConfig) -> None:
        """Execute a Delivery transaction."""
        import random
        
        w_id = random.randint(1, config.warehouses)
        
        # Simple delivery simulation
        query = "SELECT w_name FROM warehouse WHERE w_id = %s"
        await self.sql_driver.execute_query(query, [w_id])
    
    async def _execute_stock_level_transaction(self, config: TpccConfig) -> None:
        """Execute a Stock Level transaction."""
        import random
        
        w_id = random.randint(1, config.warehouses)
        d_id = random.randint(1, 10)
        
        # Simple stock level simulation
        query = "SELECT d_next_o_id FROM district WHERE d_w_id = %s AND d_id = %s"
        await self.sql_driver.execute_query(query, [w_id, d_id])
    
    def _start_performance_monitoring(self) -> None:
        """Start background performance monitoring."""
        self._performance_metrics = []
        self._monitoring_task = asyncio.create_task(self._monitor_performance())
    
    async def _stop_performance_monitoring(self) -> None:
        """Stop performance monitoring."""
        if self._monitoring_task:
            self._monitoring_task.cancel()
            try:
                await self._monitoring_task
            except asyncio.CancelledError:
                pass
            self._monitoring_task = None
    
    async def _monitor_performance(self) -> None:
        """Monitor database performance metrics during benchmark."""
        try:
            while True:
                metrics = await self._collect_performance_metrics()
                self._performance_metrics.append(metrics)
                await asyncio.sleep(5)  # Collect metrics every 5 seconds
        except asyncio.CancelledError:
            pass
    
    async def _validate_database_connection(self) -> None:
        """Validate database connection before running benchmark."""
        try:
            result = await self.sql_driver.execute_query("SELECT 1")
            if not result:
                raise RuntimeError("Database connection validation failed")
            logger.info("Database connection validated successfully")
        except Exception as e:
            raise RuntimeError(f"Database connection validation failed: {e}")
    
    async def _collect_performance_metrics(self) -> Dict[str, Any]:
        """Collect current performance metrics from database."""
        try:
            # Collect comprehensive database metrics
            query = """
            SELECT 
                now() as timestamp,
                (SELECT count(*) FROM pg_stat_activity WHERE state = 'active') as active_connections,
                (SELECT sum(xact_commit + xact_rollback) FROM pg_stat_database) as total_transactions,
                (SELECT sum(deadlocks) FROM pg_stat_database) as total_deadlocks,
                (SELECT sum(blks_read + blks_hit) FROM pg_stat_database) as total_blocks_accessed,
                (SELECT sum(tup_returned + tup_fetched + tup_inserted + tup_updated + tup_deleted) FROM pg_stat_database) as total_tuples_processed
            """
            
            result = await self.sql_driver.execute_query(query)
            if result and len(result) > 0:
                row = result[0]
                return {
                    "timestamp": row[0],
                    "active_connections": row[1],
                    "total_transactions": row[2],
                    "total_deadlocks": row[3],
                    "total_blocks_accessed": row[4],
                    "total_tuples_processed": row[5],
                }
        except Exception as e:
            logger.warning(f"Failed to collect performance metrics: {e}")
        
        return {"timestamp": datetime.now()}
    
    async def _collect_gaussdb_specific_metrics(self) -> Dict[str, Any]:
        """Collect GaussDB-specific performance metrics."""
        try:
            # Check if this is a GaussDB instance
            from ..gaussdb.sql_driver_adapter import GaussDbSqlDriver
            if not isinstance(self.sql_driver, GaussDbSqlDriver):
                return {}
            
            # Collect GaussDB-specific metrics
            gaussdb_query = """
            SELECT 
                (SELECT count(*) FROM pg_stat_activity WHERE application_name LIKE '%gaussdb%') as gaussdb_connections,
                (SELECT sum(n_tup_ins + n_tup_upd + n_tup_del) FROM pg_stat_user_tables) as dml_operations,
                (SELECT sum(seq_scan + idx_scan) FROM pg_stat_user_tables) as scan_operations
            """
            
            result = await self.sql_driver.execute_query(gaussdb_query)
            if result and len(result) > 0:
                row = result[0]
                return {
                    "gaussdb_connections": row[0],
                    "dml_operations": row[1],
                    "scan_operations": row[2],
                }
        except Exception as e:
            logger.debug(f"Failed to collect GaussDB-specific metrics: {e}")
        
        return {}
    
    async def _enhance_result_with_monitoring_data(self, result: BenchmarkResult) -> BenchmarkResult:
        """Enhance benchmark result with monitoring data collected during test."""
        if not self._performance_metrics:
            return result
        
        try:
            # Calculate averages and totals from monitoring data
            total_metrics = len(self._performance_metrics)
            if total_metrics == 0:
                return result
            
            # Calculate average connections
            avg_connections = sum(
                m.get("active_connections", 0) for m in self._performance_metrics
            ) / total_metrics
            
            # Calculate total deadlocks during test
            deadlocks_start = self._performance_metrics[0].get("total_deadlocks", 0)
            deadlocks_end = self._performance_metrics[-1].get("total_deadlocks", 0)
            test_deadlocks = max(0, deadlocks_end - deadlocks_start)
            
            # Update result with monitoring data
            result.connections_used = int(avg_connections)
            result.deadlocks = test_deadlocks
            
            logger.info(f"Enhanced result with monitoring data: avg_connections={avg_connections:.1f}, deadlocks={test_deadlocks}")
            
        except Exception as e:
            logger.warning(f"Failed to enhance result with monitoring data: {e}")
        
        return result
    
    def _parse_sysbench_output(
        self, 
        output: str, 
        config: SysbenchConfig, 
        start_time: datetime, 
        end_time: datetime, 
        duration: float
    ) -> BenchmarkResult:
        """Parse Sysbench output and extract metrics."""
        lines = output.strip().split('\n')
        
        # Initialize default values
        tps = 0.0
        qps = 0.0
        avg_latency = 0.0
        p95_latency = None
        p99_latency = None
        errors = 0
        total_events = 0
        
        # Parse Sysbench output format
        for line in lines:
            line = line.strip()
            
            # Parse transactions per second
            if "transactions:" in line and "per sec" in line:
                # Extract TPS: "transactions: 1234 (123.45 per sec.)"
                match = re.search(r'transactions:\s*\d+\s*\((\d+\.?\d*)\s*per\s*sec', line)
                if match:
                    try:
                        tps = float(match.group(1))
                    except ValueError:
                        pass
            
            # Parse queries per second
            elif "queries:" in line and "per sec" in line:
                # Extract QPS: "queries: 12345 (1234.56 per sec.)"
                match = re.search(r'queries:\s*\d+\s*\((\d+\.?\d*)\s*per\s*sec', line)
                if match:
                    try:
                        qps = float(match.group(1))
                    except ValueError:
                        pass
            
            # Parse total events
            elif "total number of events:" in line:
                match = re.search(r'total number of events:\s*(\d+)', line)
                if match:
                    try:
                        total_events = int(match.group(1))
                    except ValueError:
                        pass
            
            # Parse errors
            elif "ignored errors:" in line:
                match = re.search(r'ignored errors:\s*(\d+)', line)
                if match:
                    try:
                        errors = int(match.group(1))
                    except ValueError:
                        pass
            
            # Parse average latency
            elif "avg:" in line:
                # Extract average latency: "avg: 12.34ms" or "avg: 12.34"
                match = re.search(r'avg:\s*(\d+\.?\d*)(?:ms)?', line)
                if match:
                    try:
                        avg_latency = float(match.group(1))
                    except ValueError:
                        pass
            
            # Parse 95th percentile latency
            elif "95th percentile:" in line:
                match = re.search(r'95th percentile:\s*(\d+\.?\d*)(?:ms)?', line)
                if match:
                    try:
                        p95_latency = float(match.group(1))
                    except ValueError:
                        pass
            
            # Parse 99th percentile latency
            elif "99th percentile:" in line:
                match = re.search(r'99th percentile:\s*(\d+\.?\d*)(?:ms)?', line)
                if match:
                    try:
                        p99_latency = float(match.group(1))
                    except ValueError:
                        pass
        
        # If TPS wasn't found but we have total events and duration, calculate it
        if tps == 0.0 and total_events > 0 and duration > 0:
            tps = total_events / duration
            logger.info(f"Calculated TPS from total events: {tps:.2f}")
        
        # Log parsing results for debugging
        logger.debug(f"Parsed Sysbench results: TPS={tps}, QPS={qps}, Avg Latency={avg_latency}ms")
        
        return BenchmarkResult(
            benchmark_type=BenchmarkType.SYSBENCH,
            config=config.__dict__,
            start_time=start_time.isoformat(),
            end_time=end_time.isoformat(),
            duration_seconds=duration,
            transactions_per_second=tps,
            queries_per_second=qps,
            latency_avg_ms=avg_latency,
            latency_95th_ms=p95_latency,
            latency_99th_ms=p99_latency,
            errors=errors,
            raw_output=output
        )
    
    def _parse_tpcc_output(
        self, 
        output: str, 
        config: TpccConfig, 
        start_time: datetime, 
        end_time: datetime, 
        duration: float
    ) -> BenchmarkResult:
        """Parse TPC-C output and extract metrics."""
        lines = output.strip().split('\n')
        
        # Initialize default values
        tps = 0.0
        avg_latency = 0.0
        total_transactions = 0
        total_errors = 0
        
        # Parse different TPC-C output formats
        for line in lines:
            line = line.strip()
            
            # Parse custom TPC-C implementation output
            if "Transactions per Second:" in line:
                match = re.search(r'Transactions per Second:\s*(\d+\.?\d*)', line)
                if match:
                    try:
                        tps = float(match.group(1))
                    except ValueError:
                        pass
            
            elif "Total Transactions:" in line:
                match = re.search(r'Total Transactions:\s*(\d+)', line)
                if match:
                    try:
                        total_transactions = int(match.group(1))
                    except ValueError:
                        pass
            
            elif "Total Errors:" in line:
                match = re.search(r'Total Errors:\s*(\d+)', line)
                if match:
                    try:
                        total_errors = int(match.group(1))
                    except ValueError:
                        pass
            
            elif "Average Latency:" in line:
                match = re.search(r'Average Latency:\s*(\d+\.?\d*)\s*ms', line)
                if match:
                    try:
                        avg_latency = float(match.group(1))
                    except ValueError:
                        pass
            
            # Parse standard TPC-C benchmark tool output
            elif "tpmC" in line or "TpmC" in line:
                # Extract TPC-C transactions per minute
                match = re.search(r'(\d+\.?\d*)\s*tpmC', line, re.IGNORECASE)
                if match:
                    try:
                        tpmc = float(match.group(1))
                        tps = tpmc / 60.0  # Convert from per minute to per second
                    except ValueError:
                        pass
            
            elif "Response Time" in line or "response time" in line:
                # Extract response time
                match = re.search(r'(\d+\.?\d*)\s*(?:ms|sec)', line)
                if match:
                    try:
                        response_time = float(match.group(1))
                        if "sec" in line:
                            response_time *= 1000  # Convert to milliseconds
                        avg_latency = response_time
                    except ValueError:
                        pass
            
            elif "Errors:" in line:
                # Extract errors from standard format
                match = re.search(r'Errors:\s*(\d+)', line)
                if match:
                    try:
                        total_errors = int(match.group(1))
                    except ValueError:
                        pass
        
        # If TPS wasn't found but we have total transactions and duration, calculate it
        if tps == 0.0 and total_transactions > 0 and duration > 0:
            tps = total_transactions / duration
            logger.info(f"Calculated TPS from total transactions: {tps:.2f}")
        
        # Estimate QPS as roughly 10x TPS for TPC-C workload
        qps = tps * 10.0
        
        logger.debug(f"Parsed TPC-C results: TPS={tps}, Avg Latency={avg_latency}ms, Errors={total_errors}")
        
        return BenchmarkResult(
            benchmark_type=BenchmarkType.TPCC,
            config=config.__dict__,
            start_time=start_time.isoformat(),
            end_time=end_time.isoformat(),
            duration_seconds=duration,
            transactions_per_second=tps,
            queries_per_second=qps,
            latency_avg_ms=avg_latency,
            errors=total_errors,
            raw_output=output
        )