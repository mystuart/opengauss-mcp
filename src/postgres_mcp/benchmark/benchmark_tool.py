"""
High-level benchmark testing tool for PostgreSQL and GaussDB.
"""

import logging
from typing import Dict, List, Optional, Union, Any

from ..sql.sql_driver import SqlDriver
from ..gaussdb.sql_driver_adapter import GaussDbSqlDriver
from .benchmark_runner import BenchmarkRunner
from .config import BenchmarkType, BenchmarkResult, SysbenchConfig, TpccConfig

logger = logging.getLogger(__name__)


class BenchmarkTool:
    """
    High-level interface for running database benchmarks.
    
    Provides a unified interface for executing various benchmark tests
    and analyzing their results for performance optimization.
    """
    
    def __init__(self, sql_driver: Union[SqlDriver, GaussDbSqlDriver]):
        """
        Initialize benchmark tool.
        
        Args:
            sql_driver: Database connection driver
        """
        self.sql_driver = sql_driver
        self.benchmark_runner = BenchmarkRunner(sql_driver)
        self._is_gaussdb = isinstance(sql_driver, GaussDbSqlDriver)
    
    async def run_sysbench(
        self, 
        config: Optional[SysbenchConfig] = None,
        **kwargs
    ) -> BenchmarkResult:
        """
        Run Sysbench benchmark test.
        
        Args:
            config: Sysbench configuration. If None, uses default config.
            **kwargs: Additional configuration parameters to override
            
        Returns:
            BenchmarkResult with test results and performance analysis
            
        Raises:
            RuntimeError: If sysbench is not available or test fails
        """
        if config is None:
            config = SysbenchConfig()
        
        # Override config with any provided kwargs
        for key, value in kwargs.items():
            if hasattr(config, key):
                setattr(config, key, value)
        
        logger.info(f"Running Sysbench benchmark with {config.threads} threads for {config.time}s")
        
        # Adapt configuration for GaussDB if needed
        if self._is_gaussdb:
            config = await self._adapt_sysbench_config_for_gaussdb(config)
        
        # Run the benchmark
        result = await self.benchmark_runner.run_sysbench(config)
        
        # Add performance analysis
        result.performance_analysis = await self._analyze_sysbench_results(result)
        result.optimization_recommendations = await self._generate_sysbench_recommendations(result)
        
        return result
    
    async def run_tpcc(
        self, 
        config: Optional[TpccConfig] = None,
        **kwargs
    ) -> BenchmarkResult:
        """
        Run TPC-C benchmark test.
        
        Args:
            config: TPC-C configuration. If None, uses default config.
            **kwargs: Additional configuration parameters to override
            
        Returns:
            BenchmarkResult with test results and performance analysis
            
        Raises:
            RuntimeError: If TPC-C tool is not available or test fails
        """
        if config is None:
            config = TpccConfig()
        
        # Override config with any provided kwargs
        for key, value in kwargs.items():
            if hasattr(config, key):
                setattr(config, key, value)
        
        logger.info(f"Running TPC-C benchmark with {config.warehouses} warehouses for {config.duration}s")
        
        # Adapt configuration for GaussDB if needed
        if self._is_gaussdb:
            config = await self._adapt_tpcc_config_for_gaussdb(config)
        
        # Run the benchmark
        result = await self.benchmark_runner.run_tpcc(config)
        
        # Add performance analysis
        result.performance_analysis = await self._analyze_tpcc_results(result)
        result.optimization_recommendations = await self._generate_tpcc_recommendations(result)
        
        return result
    
    async def run_custom_benchmark(
        self, 
        benchmark_type: BenchmarkType,
        config: Dict[str, Any]
    ) -> BenchmarkResult:
        """
        Run a custom benchmark with specified configuration.
        
        Args:
            benchmark_type: Type of benchmark to run
            config: Configuration parameters
            
        Returns:
            BenchmarkResult with test results
        """
        if benchmark_type == BenchmarkType.SYSBENCH:
            sysbench_config = SysbenchConfig(**config)
            return await self.run_sysbench(sysbench_config)
        elif benchmark_type == BenchmarkType.TPCC:
            tpcc_config = TpccConfig(**config)
            return await self.run_tpcc(tpcc_config)
        else:
            raise ValueError(f"Unsupported benchmark type: {benchmark_type}")
    
    async def compare_benchmarks(
        self, 
        results: List[BenchmarkResult]
    ) -> Dict[str, Any]:
        """
        Compare multiple benchmark results and provide analysis.
        
        Args:
            results: List of benchmark results to compare
            
        Returns:
            Dictionary with comparison analysis
        """
        if not results:
            return {"error": "No results to compare"}
        
        if len(results) < 2:
            return {"error": "Need at least 2 results to compare"}
        
        # Group results by benchmark type
        grouped_results = {}
        for result in results:
            benchmark_type = result.benchmark_type
            if benchmark_type not in grouped_results:
                grouped_results[benchmark_type] = []
            grouped_results[benchmark_type].append(result)
        
        comparison = {
            "summary": {
                "total_results": len(results),
                "benchmark_types": list(grouped_results.keys()),
            },
            "comparisons": {}
        }
        
        # Compare results within each benchmark type
        for benchmark_type, type_results in grouped_results.items():
            if len(type_results) > 1:
                comparison["comparisons"][benchmark_type.value] = self._compare_same_type_results(type_results)
        
        return comparison
    
    async def _adapt_sysbench_config_for_gaussdb(self, config: SysbenchConfig) -> SysbenchConfig:
        """Adapt Sysbench configuration for GaussDB specifics."""
        # GaussDB might need specific driver or connection parameters
        if self._is_gaussdb:
            # Keep the same config for now, but could be extended
            # to handle GaussDB-specific optimizations
            logger.info("Adapting Sysbench config for GaussDB")
        
        return config
    
    async def _adapt_tpcc_config_for_gaussdb(self, config: TpccConfig) -> TpccConfig:
        """Adapt TPC-C configuration for GaussDB specifics."""
        if self._is_gaussdb:
            logger.info("Adapting TPC-C config for GaussDB")
        
        return config
    
    async def _analyze_sysbench_results(self, result: BenchmarkResult) -> str:
        """Analyze Sysbench results and provide performance insights."""
        analysis_parts = []
        
        # Performance summary
        analysis_parts.append(f"Sysbench Performance Summary:")
        analysis_parts.append(f"- Transactions per second: {result.transactions_per_second:.2f}")
        analysis_parts.append(f"- Queries per second: {result.queries_per_second:.2f}")
        analysis_parts.append(f"- Average latency: {result.latency_avg_ms:.2f}ms")
        
        if result.latency_95th_ms:
            analysis_parts.append(f"- 95th percentile latency: {result.latency_95th_ms:.2f}ms")
        
        if result.latency_99th_ms:
            analysis_parts.append(f"- 99th percentile latency: {result.latency_99th_ms:.2f}ms")
        
        # Performance assessment
        if result.transactions_per_second > 1000:
            analysis_parts.append("\nPerformance Assessment: Excellent throughput")
        elif result.transactions_per_second > 500:
            analysis_parts.append("\nPerformance Assessment: Good throughput")
        elif result.transactions_per_second > 100:
            analysis_parts.append("\nPerformance Assessment: Moderate throughput")
        else:
            analysis_parts.append("\nPerformance Assessment: Low throughput - optimization needed")
        
        # Latency assessment
        if result.latency_avg_ms < 10:
            analysis_parts.append("Latency Assessment: Excellent response times")
        elif result.latency_avg_ms < 50:
            analysis_parts.append("Latency Assessment: Good response times")
        elif result.latency_avg_ms < 100:
            analysis_parts.append("Latency Assessment: Moderate response times")
        else:
            analysis_parts.append("Latency Assessment: High latency - optimization needed")
        
        return "\n".join(analysis_parts)
    
    async def _generate_sysbench_recommendations(self, result: BenchmarkResult) -> List[str]:
        """Generate optimization recommendations based on Sysbench results."""
        recommendations = []
        
        # Low throughput recommendations
        if result.transactions_per_second < 500:
            recommendations.append("Consider increasing shared_buffers for better caching")
            recommendations.append("Review and optimize slow queries")
            recommendations.append("Consider adding appropriate indexes")
        
        # High latency recommendations
        if result.latency_avg_ms > 50:
            recommendations.append("Investigate I/O bottlenecks")
            recommendations.append("Consider increasing work_mem for complex queries")
            recommendations.append("Review connection pooling configuration")
        
        # GaussDB specific recommendations
        if self._is_gaussdb:
            recommendations.append("Review GaussDB-specific configuration parameters")
            recommendations.append("Consider GaussDB performance tuning best practices")
        
        # General recommendations
        recommendations.append("Monitor system resources during peak load")
        recommendations.append("Consider running VACUUM and ANALYZE regularly")
        
        return recommendations
    
    async def _analyze_tpcc_results(self, result: BenchmarkResult) -> str:
        """Analyze TPC-C results and provide performance insights."""
        analysis_parts = []
        
        analysis_parts.append(f"TPC-C Performance Summary:")
        analysis_parts.append(f"- Transactions per second: {result.transactions_per_second:.2f}")
        analysis_parts.append(f"- Queries per second: {result.queries_per_second:.2f}")
        analysis_parts.append(f"- Average latency: {result.latency_avg_ms:.2f}ms")
        analysis_parts.append(f"- Test duration: {result.duration_seconds:.1f} seconds")
        
        if result.errors and result.errors > 0:
            analysis_parts.append(f"- Errors encountered: {result.errors}")
            error_rate = (result.errors / (result.transactions_per_second * result.duration_seconds)) * 100
            analysis_parts.append(f"- Error rate: {error_rate:.2f}%")
        
        # Performance assessment based on TPC-C standards
        if result.transactions_per_second > 1000:
            analysis_parts.append("\nPerformance Assessment: Excellent OLTP performance")
        elif result.transactions_per_second > 500:
            analysis_parts.append("\nPerformance Assessment: Good OLTP performance")
        elif result.transactions_per_second > 100:
            analysis_parts.append("\nPerformance Assessment: Moderate OLTP performance")
        else:
            analysis_parts.append("\nPerformance Assessment: Low OLTP performance - optimization needed")
        
        # Latency assessment for OLTP workloads
        if result.latency_avg_ms < 5:
            analysis_parts.append("Latency Assessment: Excellent response times for OLTP")
        elif result.latency_avg_ms < 20:
            analysis_parts.append("Latency Assessment: Good response times for OLTP")
        elif result.latency_avg_ms < 50:
            analysis_parts.append("Latency Assessment: Acceptable response times for OLTP")
        else:
            analysis_parts.append("Latency Assessment: High latency for OLTP - optimization needed")
        
        # Calculate TPC-C specific metrics
        config = result.config
        if isinstance(config, dict) and 'warehouses' in config:
            warehouses = config['warehouses']
            tps_per_warehouse = result.transactions_per_second / warehouses if warehouses > 0 else 0
            analysis_parts.append(f"- TPS per warehouse: {tps_per_warehouse:.2f}")
        
        return "\n".join(analysis_parts)
    
    async def _generate_tpcc_recommendations(self, result: BenchmarkResult) -> List[str]:
        """Generate optimization recommendations based on TPC-C results."""
        recommendations = []
        
        # Performance-based recommendations
        if result.transactions_per_second < 500:
            recommendations.append("Consider increasing connection pool size for better concurrency")
            recommendations.append("Review and optimize hot tables (warehouse, district, customer)")
            recommendations.append("Consider table partitioning for large customer and order tables")
        
        # Latency-based recommendations
        if result.latency_avg_ms > 20:
            recommendations.append("Investigate lock contention in high-frequency transactions")
            recommendations.append("Consider optimizing New Order and Payment transaction paths")
            recommendations.append("Review index usage on frequently accessed columns")
        
        # Error-based recommendations
        if result.errors and result.errors > 0:
            recommendations.append("Investigate transaction conflicts and deadlocks")
            recommendations.append("Consider adjusting transaction isolation levels")
            recommendations.append("Review connection timeout and retry logic")
        
        # General TPC-C recommendations
        recommendations.append("Monitor lock contention on district.d_next_o_id updates")
        recommendations.append("Consider using prepared statements for better performance")
        recommendations.append("Implement proper connection pooling and load balancing")
        
        # Database-specific recommendations
        if self._is_gaussdb:
            recommendations.append("Leverage GaussDB distributed architecture for horizontal scaling")
            recommendations.append("Consider GaussDB-specific partitioning strategies")
            recommendations.append("Optimize for GaussDB's distributed transaction handling")
        else:
            recommendations.append("Consider PostgreSQL-specific optimizations (work_mem, shared_buffers)")
            recommendations.append("Review PostgreSQL connection and memory settings")
        
        # Workload-specific recommendations
        config = result.config
        if isinstance(config, dict):
            warehouses = config.get('warehouses', 1)
            if warehouses > 10:
                recommendations.append("For large warehouse counts, consider horizontal partitioning")
            
            duration = config.get('duration', 0)
            if duration < 300:
                recommendations.append("Consider longer test duration for more stable results")
        
        return recommendations
    
    def _compare_same_type_results(self, results: List[BenchmarkResult]) -> Dict[str, Any]:
        """Compare results of the same benchmark type."""
        if len(results) < 2:
            return {}
        
        # Sort by TPS for comparison
        sorted_results = sorted(results, key=lambda r: r.transactions_per_second, reverse=True)
        best = sorted_results[0]
        worst = sorted_results[-1]
        
        tps_improvement = ((best.transactions_per_second - worst.transactions_per_second) / worst.transactions_per_second) * 100
        latency_improvement = ((worst.latency_avg_ms - best.latency_avg_ms) / worst.latency_avg_ms) * 100
        
        return {
            "best_tps": best.transactions_per_second,
            "worst_tps": worst.transactions_per_second,
            "tps_improvement_pct": tps_improvement,
            "best_latency": best.latency_avg_ms,
            "worst_latency": worst.latency_avg_ms,
            "latency_improvement_pct": latency_improvement,
            "results_count": len(results)
        }