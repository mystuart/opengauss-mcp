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
from .feature_checker import FeatureAvailabilityChecker
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

        self.feature_checker = FeatureAvailabilityChecker(self.gaussdb_driver)
        logger.debug("GaussDbTopQueriesCalc initialized")

    async def get_top_queries_by_time(self, limit: int = 10, sort_by: Literal["total", "mean"] = "mean") -> str:
        """
        Reports the slowest SQL queries based on execution time with GaussDB compatibility.

        Args:
            limit: Number of slow queries to return
            sort_by: Sort criteria - 'total' for total execution time or
                'mean' for mean execution time per call (default)

        Returns:
            A string with the top queries or installation instructions
        """
        try:
            # Check if GaussDB supports pg_stat_statements equivalent
            supports_stat_statements, status_message, guidance = await self.feature_checker.check_pg_stat_statements_support()

            if not supports_stat_statements:
                logger.warning("GaussDB pg_stat_statements equivalent not available")
                # Return GaussDB-specific guidance
                return self._get_gaussdb_stat_statements_message(status_message, guidance)

            # Try GaussDB-specific approach first
            return await self._gaussdb_get_top_queries_by_time(limit, sort_by)

        except Exception as e:
            logger.warning(f"GaussDB-specific top queries by time failed: {e}")
            # Fallback to PostgreSQL compatible approach
            return await super().get_top_queries_by_time(limit, sort_by)

    async def _gaussdb_get_top_queries_by_time(self, limit: int, sort_by: Literal["total", "mean"]) -> str:
        """GaussDB-specific implementation for getting top queries by time."""
        logger.debug(f"Getting GaussDB top queries by time. limit={limit}, sort_by={sort_by}")

        # Get GaussDB version to determine column names
        db_version = await self.gaussdb_driver.get_database_version()
        logger.debug(f"GaussDB version: {db_version}")

        # GaussDB might use different column names than PostgreSQL
        total_time_col, mean_time_col = self._get_gaussdb_time_columns(db_version)

        # Determine which column to sort by
        order_by_column = total_time_col if sort_by == "total" else mean_time_col

        # Use GaussDB-adapted query
        query = f"""
            SELECT
                query,
                calls,
                {total_time_col},
                {mean_time_col},
                rows
            FROM pg_stat_statements
            ORDER BY {order_by_column} DESC
            LIMIT {{}};
        """

        logger.debug(f"Executing GaussDB query: {query}")
        slow_query_rows = await SafeSqlDriver.execute_param_query(
            self.gaussdb_driver,
            query,
            [limit],
        )
        slow_queries = [row.cells for row in slow_query_rows] if slow_query_rows else []
        logger.info(f"Found {len(slow_queries)} slow queries in GaussDB")

        # Create result description based on sort criteria
        criteria = "total execution time" if sort_by == "total" else "mean execution time per call"

        result = f"Top {len(slow_queries)} slowest queries by {criteria} (GaussDB):\n"
        result += str(slow_queries)
        return result

    async def get_top_resource_queries(self, frac_threshold: float = 0.05) -> str:
        """
        Reports the most time consuming queries based on a resource blend with GaussDB compatibility.

        Args:
            frac_threshold: Fraction threshold for filtering queries (default: 0.05)

        Returns:
            A string with the resource-heavy queries or error message
        """
        try:
            # Check if GaussDB supports pg_stat_statements equivalent
            supports_stat_statements, status_message, guidance = await self.feature_checker.check_pg_stat_statements_support()

            if not supports_stat_statements:
                logger.warning("GaussDB pg_stat_statements equivalent not available")
                # Return GaussDB-specific guidance
                return self._get_gaussdb_stat_statements_message(status_message, guidance)

            # Try GaussDB-specific approach first
            return await self._gaussdb_get_top_resource_queries(frac_threshold)

        except Exception as e:
            logger.warning(f"GaussDB-specific top resource queries failed: {e}")
            # Fallback to PostgreSQL compatible approach
            return await super().get_top_resource_queries(frac_threshold)

    async def _gaussdb_get_top_resource_queries(self, frac_threshold: float) -> str:
        """GaussDB-specific implementation for getting top resource queries."""
        logger.debug(f"Getting GaussDB top resource queries with threshold {frac_threshold}")

        # Get GaussDB version to determine column names
        db_version = await self.gaussdb_driver.get_database_version()
        total_time_col, mean_time_col = self._get_gaussdb_time_columns(db_version)

        # Use GaussDB-adapted resource query
        query = f"""
            WITH resource_fractions AS (
                SELECT
                    query,
                    calls,
                    rows,
                    {total_time_col} as total_exec_time,
                    {mean_time_col} as mean_exec_time,
                    COALESCE(stddev_exec_time, 0) as stddev_exec_time,
                    COALESCE(shared_blks_hit, 0) as shared_blks_hit,
                    COALESCE(shared_blks_read, 0) as shared_blks_read,
                    COALESCE(shared_blks_dirtied, 0) as shared_blks_dirtied,
                    COALESCE(wal_bytes, 0) as wal_bytes,
                    {total_time_col} / NULLIF(SUM({total_time_col}) OVER (), 0) AS total_exec_time_frac,
                    (COALESCE(shared_blks_hit, 0) + COALESCE(shared_blks_read, 0)) / 
                        NULLIF(SUM(COALESCE(shared_blks_hit, 0) + COALESCE(shared_blks_read, 0)) OVER (), 0) AS shared_blks_accessed_frac,
                    COALESCE(shared_blks_read, 0) / NULLIF(SUM(COALESCE(shared_blks_read, 0)) OVER (), 0) AS shared_blks_read_frac,
                    COALESCE(shared_blks_dirtied, 0) / NULLIF(SUM(COALESCE(shared_blks_dirtied, 0)) OVER (), 0) AS shared_blks_dirtied_frac,
                    COALESCE(wal_bytes, 0) / NULLIF(SUM(COALESCE(wal_bytes, 0)) OVER (), 0) AS total_wal_bytes_frac
                FROM pg_stat_statements
            )
            SELECT
                query,
                calls,
                rows,
                total_exec_time,
                mean_exec_time,
                stddev_exec_time,
                COALESCE(total_exec_time_frac, 0) as total_exec_time_frac,
                COALESCE(shared_blks_accessed_frac, 0) as shared_blks_accessed_frac,
                COALESCE(shared_blks_read_frac, 0) as shared_blks_read_frac,
                COALESCE(shared_blks_dirtied_frac, 0) as shared_blks_dirtied_frac,
                COALESCE(total_wal_bytes_frac, 0) as total_wal_bytes_frac,
                shared_blks_hit,
                shared_blks_read,
                shared_blks_dirtied,
                wal_bytes
            FROM resource_fractions
            WHERE
                COALESCE(total_exec_time_frac, 0) > {frac_threshold}
                OR COALESCE(shared_blks_accessed_frac, 0) > {frac_threshold}
                OR COALESCE(shared_blks_read_frac, 0) > {frac_threshold}
                OR COALESCE(shared_blks_dirtied_frac, 0) > {frac_threshold}
                OR COALESCE(total_wal_bytes_frac, 0) > {frac_threshold}
            ORDER BY total_exec_time DESC
        """

        logger.debug(f"Executing GaussDB resource query: {query}")
        slow_query_rows = await SafeSqlDriver.execute_param_query(
            self.gaussdb_driver,
            query,
        )
        resource_queries = [row.cells for row in slow_query_rows] if slow_query_rows else []
        logger.info(f"Found {len(resource_queries)} resource-intensive queries in GaussDB")

        result = f"Resource-intensive queries (GaussDB):\n{resource_queries!s}"
        return result

    def _get_gaussdb_time_columns(self, db_version: str) -> tuple[str, str]:
        """
        Get the appropriate time column names for GaussDB version.
        
        Args:
            db_version: GaussDB version string
            
        Returns:
            Tuple of (total_time_column, mean_time_column)
        """
        # GaussDB might use different column naming conventions
        # This is a simplified approach - in practice, you'd need to check
        # the actual GaussDB version and its pg_stat_statements equivalent

        try:
            # Extract major version number
            version_parts = db_version.split('.')
            if len(version_parts) >= 1:
                major_version = int(version_parts[0])

                # GaussDB versioning might be different from PostgreSQL
                # Adjust based on actual GaussDB documentation
                if major_version >= 8:  # Assuming GaussDB 8.x uses newer column names
                    return "total_exec_time", "mean_exec_time"
                else:
                    return "total_time", "mean_time"
        except (ValueError, IndexError):
            logger.warning(f"Could not parse GaussDB version: {db_version}")

        # Default to newer column names
        return "total_exec_time", "mean_exec_time"

    def _get_gaussdb_stat_statements_message(self, status_message: str, guidance: str) -> str:
        """
        Get GaussDB-specific message for pg_stat_statements equivalent.
        
        Args:
            status_message: Status message from feature checker
            guidance: Guidance message from feature checker
            
        Returns:
            Formatted message for user
        """
        message_parts = [
            "Query statistics extension is required to report slow queries in GaussDB.",
            "",
            f"Status: {status_message}",
        ]

        if guidance:
            message_parts.extend([
                "",
                "GaussDB Guidance:",
                guidance,
            ])
        else:
            message_parts.extend([
                "",
                "GaussDB may use a different extension or system view for query statistics.",
                "Please check your GaussDB documentation for the equivalent of pg_stat_statements.",
                "",
                "Common alternatives in GaussDB:",
                "- Check if pg_stat_statements is available: SELECT * FROM pg_available_extensions WHERE name = 'pg_stat_statements';",
                "- Look for GaussDB-specific query monitoring views in the system catalog",
                "- Consult GaussDB documentation for performance monitoring features",
            ])

        return "\n".join(message_parts)

    async def get_gaussdb_query_statistics_info(self) -> dict:
        """
        Get information about query statistics availability in GaussDB.
        
        Returns:
            Dictionary with query statistics information
        """
        try:
            supports_stat_statements, status_message, guidance = await self.feature_checker.check_pg_stat_statements_support()

            info = {
                "database_type": "gaussdb",
                "pg_stat_statements_supported": supports_stat_statements,
                "status_message": status_message,
                "guidance": guidance,
            }

            if supports_stat_statements:
                # Get additional statistics about the extension
                try:
                    result = await self.gaussdb_driver.execute_query("""
                        SELECT 
                            COUNT(*) as total_queries,
                            SUM(calls) as total_calls,
                            MAX(calls) as max_calls
                        FROM pg_stat_statements
                    """)

                    if result and result[0].cells:
                        stats = dict(result[0].cells)
                        info.update({
                            "total_tracked_queries": stats.get("total_queries", 0),
                            "total_query_calls": stats.get("total_calls", 0),
                            "max_query_calls": stats.get("max_calls", 0),
                        })
                except Exception as e:
                    logger.warning(f"Could not get pg_stat_statements statistics: {e}")
                    info["statistics_error"] = str(e)

            return info

        except Exception as e:
            logger.error(f"Error getting GaussDB query statistics info: {e}")
            return {
                "database_type": "gaussdb",
                "error": str(e),
                "pg_stat_statements_supported": False,
            }
