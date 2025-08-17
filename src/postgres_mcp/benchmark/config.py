"""
Configuration data models for benchmark testing.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from enum import Enum


class BenchmarkType(str, Enum):
    """Supported benchmark types."""
    SYSBENCH = "sysbench"
    TPCC = "tpcc"


@dataclass
class SysbenchConfig:
    """Configuration for Sysbench benchmark tests."""
    
    # Test parameters
    test_type: str = "oltp_read_write"  # oltp_read_write, oltp_read_only, oltp_write_only
    table_size: int = 100000  # Number of rows per table
    tables: int = 4  # Number of tables
    threads: int = 4  # Number of threads
    time: int = 60  # Test duration in seconds
    
    # Database connection
    db_driver: str = "pgsql"
    db_host: str = "localhost"
    db_port: int = 5432
    db_user: str = "postgres"
    db_password: str = ""
    db_name: str = "test"
    
    # Advanced options
    report_interval: int = 10  # Report interval in seconds
    warmup_time: int = 10  # Warmup time in seconds
    rate: Optional[int] = None  # Target rate (events per second)
    
    # Custom options
    extra_args: List[str] = field(default_factory=list)
    
    def to_command_args(self) -> List[str]:
        """Convert config to sysbench command arguments."""
        args = [
            f"--db-driver={self.db_driver}",
            f"--pgsql-host={self.db_host}",
            f"--pgsql-port={self.db_port}",
            f"--pgsql-user={self.db_user}",
            f"--pgsql-db={self.db_name}",
            f"--table_size={self.table_size}",
            f"--tables={self.tables}",
            f"--threads={self.threads}",
            f"--time={self.time}",
            f"--report-interval={self.report_interval}",
            f"--warmup-time={self.warmup_time}",
        ]
        
        if self.db_password:
            args.append(f"--pgsql-password={self.db_password}")
        
        if self.rate:
            args.append(f"--rate={self.rate}")
            
        args.extend(self.extra_args)
        return args


@dataclass
class TpccConfig:
    """Configuration for TPC-C benchmark tests."""
    
    # Test parameters
    warehouses: int = 4  # Number of warehouses
    duration: int = 300  # Test duration in seconds
    connections: int = 4  # Number of connections
    ramp_up_time: int = 30  # Ramp-up time in seconds
    
    # Database connection
    db_host: str = "localhost"
    db_port: int = 5432
    db_user: str = "postgres"
    db_password: str = ""
    db_name: str = "tpcc"
    
    # Transaction mix (percentages)
    new_order_pct: float = 45.0
    payment_pct: float = 43.0
    order_status_pct: float = 4.0
    delivery_pct: float = 4.0
    stock_level_pct: float = 4.0
    
    # Performance options
    vacuum_between_runs: bool = True
    analyze_between_runs: bool = True
    
    # Custom options
    extra_args: List[str] = field(default_factory=list)
    
    def to_command_args(self) -> List[str]:
        """Convert config to TPC-C command arguments."""
        args = [
            f"--host={self.db_host}",
            f"--port={self.db_port}",
            f"--user={self.db_user}",
            f"--dbname={self.db_name}",
            f"--warehouses={self.warehouses}",
            f"--duration={self.duration}",
            f"--connections={self.connections}",
            f"--ramp-up={self.ramp_up_time}",
        ]
        
        if self.db_password:
            args.append(f"--password={self.db_password}")
            
        args.extend(self.extra_args)
        return args


@dataclass
class BenchmarkResult:
    """Results from a benchmark test run."""
    
    benchmark_type: BenchmarkType
    config: Dict[str, Any]
    
    # Execution info
    start_time: str
    end_time: str
    duration_seconds: float
    
    # Performance metrics
    transactions_per_second: float
    queries_per_second: float
    latency_avg_ms: float
    latency_95th_ms: Optional[float] = None
    latency_99th_ms: Optional[float] = None
    
    # Resource utilization
    cpu_usage_pct: Optional[float] = None
    memory_usage_mb: Optional[float] = None
    io_read_mb: Optional[float] = None
    io_write_mb: Optional[float] = None
    
    # Database metrics
    connections_used: Optional[int] = None
    deadlocks: Optional[int] = None
    errors: Optional[int] = None
    
    # Raw output
    raw_output: str = ""
    
    # Analysis and recommendations
    performance_analysis: Optional[str] = None
    optimization_recommendations: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary for serialization."""
        return {
            "benchmark_type": self.benchmark_type.value,
            "config": self.config,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_seconds": self.duration_seconds,
            "transactions_per_second": self.transactions_per_second,
            "queries_per_second": self.queries_per_second,
            "latency_avg_ms": self.latency_avg_ms,
            "latency_95th_ms": self.latency_95th_ms,
            "latency_99th_ms": self.latency_99th_ms,
            "cpu_usage_pct": self.cpu_usage_pct,
            "memory_usage_mb": self.memory_usage_mb,
            "io_read_mb": self.io_read_mb,
            "io_write_mb": self.io_write_mb,
            "connections_used": self.connections_used,
            "deadlocks": self.deadlocks,
            "errors": self.errors,
            "raw_output": self.raw_output,
            "performance_analysis": self.performance_analysis,
            "optimization_recommendations": self.optimization_recommendations,
        }