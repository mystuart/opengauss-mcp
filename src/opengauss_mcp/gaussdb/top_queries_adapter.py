"""
GaussDB top queries adapter.

This module provides the GaussDbTopQueriesCalc class that adapts PostgreSQL
top queries functionality to work with GaussDB databases, handling differences
in pg_stat_statements equivalent and query statistics collection.
"""

import logging
from typing import Literal
from typing import Union

from ..sql import SafeSqlDriver
from ..sql import SqlDriver
from ..top_queries.top_queries_calc import TopQueriesCalc
from .sql_driver_adapter import GaussDbSqlDriver

logger = logging.getLogger(__name__)


class GaussDbTopQueriesCalc(TopQueriesCalc):
    """
    GaussDB adapter for top queries calculations.
    
    This class extends the base TopQueriesCalc to handle GaussDB-specific
    differences in query statistics collection and pg_stat_statements equivalent.
    """

    def __init__(self, sql_driver: Union[SqlDriver, GaussDbSqlDriver]):
        """
        Initialize GaussDB top queries calculator.
        
        Args:
            sql_driver: SQL driver (can be regular SqlDriver or GaussDbSqlDriver)
        """
        # If we get a regular SqlDriver, wrap it with GaussDbSqlDriver
        if isinstance(sql_driver, GaussDbSqlDriver):
            super().__init__(sql_driver.base_driver)
            self.gaussdb_driver = sql_driver
        else:
            super().__init__(sql_driver)
            self.gaussdb_driver = GaussDbSqlDriver(sql_driver)

        logger.debug("GaussDbTopQueriesCalc initialized")

    async def get_top_queries_by_time(self, limit: int = 10, sort_by: Literal["total", "mean"] = "mean") -> str:
        """
        Reports the slowest SQL queries based on execution time with GaussDB compatibility.

        Args:
            limit: Number of slow queries to return
            sort_by: Sort criteria - 'total' for total execution time or
                'mean' for mean execution time per call (default)

        Returns:
            A string with the top queries or alternative monitoring suggestions
        """
        try:
            # GaussDB doesn't support pg_stat_statements, use alternative approaches
            return await self._get_alternative_top_queries_by_time(limit, sort_by)
        except Exception as e:
            logger.warning(f"GaussDB top queries by time failed: {e}")
            # Return guidance if all approaches fail
            return await self._get_gaussdb_query_monitoring_guidance()

    
    async def get_top_resource_queries(self, frac_threshold: float = 0.05) -> str:
        """
        Reports the most time consuming queries based on a resource blend with GaussDB compatibility.

        Args:
            frac_threshold: Fraction threshold for filtering queries (default: 0.05)

        Returns:
            A string with the resource-heavy queries or alternative monitoring suggestions
        """
        try:
            # GaussDB doesn't support pg_stat_statements, use alternative approaches
            return await self._get_alternative_top_resource_queries(frac_threshold)
        except Exception as e:
            logger.warning(f"GaussDB top resource queries failed: {e}")
            # Return guidance if all approaches fail
            return await self._get_gaussdb_query_monitoring_guidance()

    async def _get_alternative_top_queries_by_time(self, limit: int, sort_by: Literal["total", "mean"]) -> str:
        """
        Alternative approach for getting top queries when pg_stat_statements is not available.
        
        This method tries multiple alternative approaches to get query performance information.
        """
        logger.info("Using alternative approaches for GaussDB top queries analysis")
        
        # Try different approaches in order of preference
        approaches = [
            ("dbe_perf.statement", self._get_queries_from_dbe_perf),
            ("session-level monitoring", self._get_queries_from_session_monitoring),
        ]
        
        for approach_name, approach_method in approaches:
            try:
                logger.debug(f"Trying approach: {approach_name}")
                result = await approach_method(limit, sort_by)
                if result and "No data available" not in result:
                    return result
            except Exception as e:
                logger.debug(f"Approach {approach_name} failed: {e}")
                continue
        
        # If all approaches fail, return guidance
        return await self._get_gaussdb_query_monitoring_guidance()

    async def _get_alternative_top_resource_queries(self, frac_threshold: float) -> str:
        """
        Alternative approach for getting top resource queries when pg_stat_statements is not available.
        """
        logger.info("Using alternative approaches for GaussDB top resource queries analysis")
        
        # Try different approaches in order of preference
        approaches = [
            ("dbe_perf.statement", self._get_resource_queries_from_dbe_perf),
            ("session-level monitoring", self._get_resource_queries_from_session_monitoring),
        ]
        
        for approach_name, approach_method in approaches:
            try:
                logger.debug(f"Trying approach: {approach_name}")
                result = await approach_method(frac_threshold)
                if result and "No data available" not in result:
                    return result
            except Exception as e:
                logger.debug(f"Approach {approach_name} failed: {e}")
                continue
        
        # If all approaches fail, return guidance
        return await self._get_gaussdb_query_monitoring_guidance()

    async def _get_queries_from_dbe_perf(self, limit: int, sort_by: Literal["total", "mean"]) -> str:
        """
        Try to get query statistics from GaussDB's dbe_perf.statement view.
        
        This is the preferred alternative when available in GaussDB.
        """
        try:
            # Check if dbe_perf.statement is available
            check_query = "SELECT COUNT(*) FROM dbe_perf.statement LIMIT 1"
            result = await self.gaussdb_driver.execute_query(check_query)
            
            if not result or not result[0].cells:
                return "No data available from dbe_perf.statement"
            
            # dbe_perf.statement is available, use it
            logger.info("Using dbe_perf.statement for query analysis")
            
            # Determine time columns based on available columns
            time_col_query = """
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'statement' 
                AND table_schema = 'dbe_perf'
                AND column_name LIKE '%time%'
                ORDER BY column_name
            """
            
            time_columns_result = await self.gaussdb_driver.execute_query(time_col_query)
            time_columns = [row.cells['column_name'] for row in time_columns_result] if time_columns_result else []
            
            # Look for common time column patterns
            total_time_col = None
            mean_time_col = None
            
            for col in time_columns:
                col_lower = col.lower()
                if 'total' in col_lower and 'exec' in col_lower:
                    total_time_col = col
                elif 'mean' in col_lower and 'exec' in col_lower:
                    mean_time_col = col
                elif 'avg' in col_lower and 'exec' in col_lower:
                    mean_time_col = col
            
            if not total_time_col:
                total_time_col = "total_exec_time"  # Default column name
            if not mean_time_col:
                mean_time_col = "mean_exec_time"   # Default column name
            
            # Build the query
            order_by_column = total_time_col if sort_by == "total" else mean_time_col
            
            query = f"""
                SELECT 
                    query,
                    calls,
                    rows,
                    {total_time_col},
                    {mean_time_col}
                FROM dbe_perf.statement
                ORDER BY {order_by_column} DESC
                LIMIT {{}};
            """
            
            query_rows = await SafeSqlDriver.execute_param_query(
                self.gaussdb_driver,
                query, # type: ignore
                [limit],
            )
            
            queries = [row.cells for row in query_rows] if query_rows else []
            
            if not queries:
                return "No data available from dbe_perf.statement"
            
            criteria = "total execution time" if sort_by == "total" else "mean execution time per call"
            result = f"Top {len(queries)} slowest queries by {criteria} (GaussDB dbe_perf.statement):\n"
            result += str(queries)
            return result
            
        except Exception as e:
            logger.debug(f"dbe_perf.statement approach failed: {e}")
            return "No data available from dbe_perf.statement"

    async def _get_resource_queries_from_dbe_perf(self, frac_threshold: float) -> str:
        """
        Try to get resource queries from GaussDB's dbe_perf.statement view.
        """
        try:
            # Check if dbe_perf.statement is available
            check_query = "SELECT COUNT(*) FROM dbe_perf.statement LIMIT 1"
            result = await self.gaussdb_driver.execute_query(check_query)
            
            if not result or not result[0].cells:
                return "No data available from dbe_perf.statement"
            
            # Get available columns
            time_col_query = """
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'statement' 
                AND table_schema = 'dbe_perf'
                AND column_name LIKE '%time%'
                ORDER BY column_name
            """
            
            time_columns_result = await self.gaussdb_driver.execute_query(time_col_query)
            time_columns = [row.cells['column_name'] for row in time_columns_result] if time_columns_result else []
            
            # Look for common time column patterns
            total_time_col = None
            mean_time_col = None
            
            for col in time_columns:
                col_lower = col.lower()
                if 'total' in col_lower and 'exec' in col_lower:
                    total_time_col = col
                elif 'mean' in col_lower and 'exec' in col_lower:
                    mean_time_col = col
                elif 'avg' in col_lower and 'exec' in col_lower:
                    mean_time_col = col
            
            if not total_time_col:
                total_time_col = "total_exec_time"  # Default column name
            if not mean_time_col:
                mean_time_col = "mean_exec_time"   # Default column name
            
            # Build the resource query
            query = f"""
                WITH resource_fractions AS (
                    SELECT
                        query,
                        calls,
                        rows,
                        {total_time_col} as total_exec_time,
                        {mean_time_col} as mean_exec_time,
                        {total_time_col} / NULLIF(SUM({total_time_col}) OVER (), 0) AS total_exec_time_frac,
                        ROW_NUMBER() OVER (ORDER BY {total_time_col} DESC) as rn
                    FROM dbe_perf.statement
                )
                SELECT
                    query,
                    calls,
                    rows,
                    total_exec_time,
                    mean_exec_time,
                    total_exec_time_frac
                FROM resource_fractions
                WHERE total_exec_time_frac > {frac_threshold}
                ORDER BY total_exec_time DESC
            """
            
            query_rows = await self.gaussdb_driver.execute_query(query) # type: ignore
            queries = [row.cells for row in query_rows] if query_rows else []
            
            if not queries:
                return "No resource-intensive queries found in dbe_perf.statement"
            
            result = f"Resource-intensive queries (GaussDB dbe_perf.statement):\n{queries!s}"
            return result
            
        except Exception as e:
            logger.debug(f"dbe_perf.statement resource approach failed: {e}")
            return "No data available from dbe_perf.statement"

    async def _get_queries_from_session_monitoring(self, limit: int, sort_by: Literal["total", "mean"]) -> str:
        """
        Try to get query information from session-level monitoring.
        """
        try:
            # Check pg_stat_activity for currently running queries
            query = """
                SELECT 
                    query,
                    state,
                    now() - query_start as duration,
                    now() - backend_start as session_duration,
                    application_name,
                    client_addr
                FROM pg_stat_activity 
                WHERE state = 'active' 
                AND query IS NOT NULL 
                AND query != ''
                ORDER BY now() - query_start DESC
                LIMIT {{}};
            """
            
            query_rows = await SafeSqlDriver.execute_param_query(
                self.gaussdb_driver,
                query,
                [limit],
            )
            
            queries = [row.cells for row in query_rows] if query_rows else []
            
            if not queries:
                return "No active queries found in session monitoring"
            
            criteria = "duration"  # Session monitoring only has duration
            result = f"Top {len(queries)} active queries by {criteria} (GaussDB session monitoring):\n"
            result += str(queries)
            return result
            
        except Exception as e:
            logger.debug(f"Session monitoring approach failed: {e}")
            return "No data available from session monitoring"

    async def _get_resource_queries_from_session_monitoring(self, frac_threshold: float) -> str:
        """
        Try to get resource queries from session-level monitoring.
        """
        try:
            # Check pg_stat_activity for currently running queries with resource usage
            query = """
                SELECT 
                    query,
                    state,
                    now() - query_start as duration,
                    now() - backend_start as session_duration,
                    application_name,
                    client_addr,
                    COUNT(*) OVER () as total_sessions
                FROM pg_stat_activity 
                WHERE state = 'active' 
                AND query IS NOT NULL 
                AND query != ''
                ORDER BY now() - query_start DESC
            """
            
            query_rows = await self.gaussdb_driver.execute_query(query)
            queries = [row.cells for row in query_rows] if query_rows else []
            
            if not queries:
                return "No active queries found in session monitoring"
            
            # Calculate duration fractions
            total_sessions = queries[0].get('total_sessions', 1)
            result = f"Active resource queries (GaussDB session monitoring):\n"
            
            for query_data in queries:
                duration = query_data.get('duration', 0)
                duration_frac = duration / total_sessions if total_sessions > 0 else 0
                
                if duration_frac > frac_threshold:
                    result += f"Query: {query_data['query'][:100]}...\n"
                    result += f"  Duration: {duration}, Fraction: {duration_frac:.3f}\n"
            
            return result
            
        except Exception as e:
            logger.debug(f"Session resource monitoring approach failed: {e}")
            return "No data available from session monitoring"

    async def _get_gaussdb_query_monitoring_guidance(self) -> str:
        """
        Provide guidance for GaussDB query monitoring when standard approaches are not available.
        """
        guidance_parts = [
            "Query statistics monitoring is not available in this GaussDB instance.",
            "",
            "Alternative approaches for query performance monitoring:",
            "",
            "1. Enable GaussDB Performance Monitoring:",
            "   - Check if dbe_perf.statement view is available: SELECT * FROM dbe_perf.statement LIMIT 1",
            "   - Enable query statistics in GaussDB configuration parameters",
            "   - Use GaussDB Manager or other monitoring tools",
            "",
            "2. Use Session Monitoring:",
            "   - Monitor active queries: SELECT * FROM pg_stat_activity WHERE state = 'active'",
            "   - Track long-running queries in real-time",
            "   - Set up alerts for long-running transactions",
            "",
            "3. External Monitoring Tools:",
            "   - GaussDB Manager for enterprise monitoring",
            "   - Prometheus + Grafana with custom exporters",
            "   - Database Activity Monitoring (DAM) tools",
            "",
            "4. Manual Query Analysis:",
            "   - Identify high-traffic tables using pg_stat_user_tables",
            "   - Analyze query patterns during peak usage periods",
            "   - Use database-specific monitoring views",
            "",
            "To enable query statistics in GaussDB, consider:",
            "- Checking GaussDB documentation for query monitoring features",
            "- Enabling appropriate configuration parameters",
            "- Installing GaussDB-specific extensions if available",
            "- Using GaussDB Manager or other enterprise monitoring solutions",
        ]
        
        return "\n".join(guidance_parts)
