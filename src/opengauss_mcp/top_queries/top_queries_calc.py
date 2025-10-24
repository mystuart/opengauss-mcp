import logging
from typing import Literal
from typing import LiteralString
from typing import Union
from typing import cast

from ..sql import SafeSqlDriver
from ..sql import SqlDriver
from ..sql.extension_utils import check_dbe_perf_availability
from ..sql.extension_utils import get_database_type
from ..sql.extension_utils import get_database_version

logger = logging.getLogger(__name__)

DBE_PERF_STATEMENT = "dbe_perf.statement"

dbe_perf_unavailable_message = (
    "The dbe_perf.statement view is required to "
    "report slow queries, but it is not available.\n\n"
    "Please ensure you are using openGauss database with "
    "necessary permissions to access dbe_perf views.\n\n"
    "**What does it do?** The dbe_perf.statement view provides statistics (like "
    "execution time, number of calls, rows returned) for "
    "every query executed against the database.\n\n"
    "**Is it safe?** Accessing dbe_perf views is generally safe and a standard practice for performance "
    "monitoring in openGauss."
)


class TopQueriesCalc:
    """Tool for retrieving the slowest SQL queries."""

    def __init__(self, sql_driver: Union[SqlDriver, SafeSqlDriver]):
        self.sql_driver = sql_driver

    async def get_top_queries_by_time(self, limit: int = 10, sort_by: Literal["total", "mean"] = "mean") -> str:
        """Reports the slowest SQL queries based on execution time.

        Args:
            limit: Number of slow queries to return
            sort_by: Sort criteria - 'total' for total execution time or
                'mean' for mean execution time per call (default)

        Returns:
            A string with the top queries or installation instructions
        """
        try:
            logger.debug(f"Getting top queries by time. limit={limit}, sort_by={sort_by}")
            
            # Check database type and dbe_perf availability
            db_type = await get_database_type(self.sql_driver)
            logger.debug(f"Database type: {db_type}")
            
            if db_type != "opengauss":
                logger.warning(f"Unsupported database type: {db_type}")
                return dbe_perf_unavailable_message
            
            dbe_perf_available, dbe_perf_message = await check_dbe_perf_availability(
                self.sql_driver, message_type="plain"
            )
            
            if not dbe_perf_available:
                logger.warning("dbe_perf.statement view is not available")
                return dbe_perf_message

            # Determine which column to sort by based on sort_by parameter
            if sort_by == "total":
                order_by_column = "total_elapse_time"
            else:
                order_by_column = "total_elapse_time / NULLIF(n_calls, 0)"

            query = f"""
                SELECT
                    query,
                    n_calls as calls,
                    total_elapse_time,
                    total_elapse_time / NULLIF(n_calls, 0) as mean_exec_time,
                    n_returned_rows as rows
                FROM {DBE_PERF_STATEMENT}
                WHERE n_calls > 0
                ORDER BY {order_by_column} DESC
                LIMIT {{}};
            """
            logger.debug(f"Executing query: {query}")
            slow_query_rows = await SafeSqlDriver.execute_param_query(
                self.sql_driver,
                query,
                [limit],
            )
            slow_queries = [row.cells for row in slow_query_rows] if slow_query_rows else []
            logger.info(f"Found {len(slow_queries)} slow queries")

            # Format results
            result_text = [f"Top {len(slow_queries)} slowest queries by {sort_by} execution time:"]
            
            for query in slow_queries:
                result_text.append(f"\nQuery: {query['query'][:100]}...")
                result_text.append(f"  Calls: {query['calls']}")
                result_text.append(f"  Total Time: {query['total_elapse_time']} ms")
                result_text.append(f"  Mean Time: {query['mean_exec_time']} ms")
                result_text.append(f"  Rows Returned: {query['rows']}")
            
            return "\n".join(result_text)
        except Exception as e:
            logger.error(f"Error getting slow queries: {e}", exc_info=True)
            return f"Error getting slow queries: {e}"

    async def get_top_resource_queries(self, frac_threshold: float = 0.05) -> str:
        """Reports the most resource-consuming queries based on execution time, CPU time, and I/O operations.

        Args:
            frac_threshold: Fraction threshold for filtering queries (default: 0.05)

        Returns:
            A string with the resource-heavy queries or error message
        """

        try:
            logger.debug(f"Getting top resource queries with threshold {frac_threshold}")
            
            # Check database type and dbe_perf availability
            db_type = await get_database_type(self.sql_driver)
            logger.debug(f"Database type: {db_type}")
            
            if db_type != "opengauss":
                logger.warning(f"Unsupported database type: {db_type}")
                return dbe_perf_unavailable_message
            
            dbe_perf_available, dbe_perf_message = await check_dbe_perf_availability(
                self.sql_driver, message_type="plain"
            )
            
            if not dbe_perf_available:
                logger.warning("dbe_perf.statement view is not available")
                return dbe_perf_message

            # Query with only existing fields from dbe_perf.statement
            query = cast(
                LiteralString,
                f"""
                WITH resource_fractions AS (
                    SELECT
                        query,
                        n_calls as calls,
                        n_returned_rows as rows,
                        total_elapse_time,
                        total_elapse_time / NULLIF(n_calls, 0) as mean_exec_time,
                        n_blocks_hit,
                        n_blocks_fetched,
                        cpu_time,
                        data_io_time,
                        sort_time,
                        hash_time,
                        lock_wait_time,
                        -- Calculate resource usage fractions
                        total_elapse_time / SUM(total_elapse_time) OVER () AS total_exec_time_frac,
                        n_blocks_fetched / NULLIF(SUM(n_blocks_fetched) OVER (), 0) AS blocks_read_frac,
                        cpu_time / NULLIF(SUM(cpu_time) OVER (), 0) AS cpu_time_frac,
                        data_io_time / NULLIF(SUM(data_io_time) OVER (), 0) AS data_io_time_frac,
                        -- Calculate cache hit ratio
                        CASE
                            WHEN (n_blocks_hit + n_blocks_fetched) > 0
                            THEN n_blocks_hit::float / (n_blocks_hit + n_blocks_fetched)
                            ELSE 1
                        END as cache_hit_ratio,
                        -- Calculate resource score based on available metrics
                        (total_elapse_time * 0.4 +
                         n_blocks_fetched * 0.2 +
                         cpu_time * 0.2 +
                         (sort_time + hash_time) * 0.1 +
                         lock_wait_time * 0.1) as resource_score
                    FROM {DBE_PERF_STATEMENT}
                    WHERE n_calls > 0
                )
                SELECT
                    query,
                    calls,
                    rows,
                    total_elapse_time,
                    mean_exec_time,
                    n_blocks_hit,
                    n_blocks_fetched,
                    cpu_time,
                    data_io_time,
                    sort_time,
                    hash_time,
                    lock_wait_time,
                    total_exec_time_frac,
                    blocks_read_frac,
                    cpu_time_frac,
                    data_io_time_frac,
                    cache_hit_ratio,
                    resource_score
                FROM resource_fractions
                WHERE
                    total_exec_time_frac > {frac_threshold}
                    OR blocks_read_frac > {frac_threshold}
                    OR cpu_time_frac > {frac_threshold}
                    OR data_io_time_frac > {frac_threshold}
                ORDER BY resource_score DESC, total_elapse_time DESC
                LIMIT 20
            """,
            )

            logger.debug(f"Executing resource query: {query}")
            resource_query_rows = await SafeSqlDriver.execute_param_query(
                self.sql_driver,
                query,
            )
            resource_queries = [row.cells for row in resource_query_rows] if resource_query_rows else []
            logger.info(f"Found {len(resource_queries)} resource-intensive queries")

            # Format results
            if resource_queries:
                result = ["Top resource-intensive queries:"]
                for i, query in enumerate(resource_queries, 1):
                    result.append(f"\n{i}. Query: {query['query'][:100]}...")
                    result.append(f"   Calls: {query['calls']}, Rows: {query['rows']}")
                    result.append(f"   Total Time: {query['total_elapse_time']:.2f}ms, Avg Time: {query['mean_exec_time']:.2f}ms")
                    result.append(f"   CPU Time: {query.get('cpu_time', 0):.2f}ms")
                    result.append(f"   Data I/O Time: {query.get('data_io_time', 0):.2f}ms")
                    result.append(f"   Sort Time: {query.get('sort_time', 0):.2f}ms")
                    result.append(f"   Hash Time: {query.get('hash_time', 0):.2f}ms")
                    result.append(f"   Lock Wait Time: {query.get('lock_wait_time', 0):.2f}ms")
                    result.append(f"   Blocks Read: {query['n_blocks_fetched']}")
                    result.append(f"   Cache Hit Ratio: {query['cache_hit_ratio']:.2%}")
                    result.append(f"   Resource Score: {query.get('resource_score', 0):.2f}")
                
                return "\n".join(result)
            else:
                return "No resource-intensive queries found."
        except Exception as e:
            logger.error(f"Error getting resource-intensive queries: {e}", exc_info=True)
            return f"Error getting resource-intensive queries: {e}"

    async def get_io_intensive_queries(self, io_threshold: float = 0.05) -> str:
        """Reports queries with high I/O usage based on block read metrics and cache hit ratio.

        Args:
            io_threshold: Fraction threshold for filtering queries (default: 0.05)

        Returns:
            A string with the I/O-intensive queries or error message
        """

        try:
            logger.debug(f"Getting I/O intensive queries with threshold {io_threshold}")
            
            # Check database type and dbe_perf availability
            db_type = await get_database_type(self.sql_driver)
            logger.debug(f"Database type: {db_type}")
            
            if db_type != "opengauss":
                logger.warning(f"Unsupported database type: {db_type}")
                return dbe_perf_unavailable_message
            
            dbe_perf_available, dbe_perf_message = await check_dbe_perf_availability(
                self.sql_driver, message_type="plain"
            )
            
            if not dbe_perf_available:
                logger.warning("dbe_perf.statement view is not available")
                return dbe_perf_message

            # I/O intensive queries analysis with only existing fields
            query = cast(
                LiteralString,
                f"""
                WITH io_metrics AS (
                    SELECT
                        query,
                        n_calls as calls,
                        n_returned_rows as rows,
                        total_elapse_time,
                        total_elapse_time / NULLIF(n_calls, 0) as mean_exec_time,
                        n_blocks_hit,
                        n_blocks_fetched,
                        data_io_time,
                        -- Calculate cache hit ratio
                        CASE
                            WHEN (n_blocks_hit + n_blocks_fetched) > 0
                            THEN n_blocks_hit::float / (n_blocks_hit + n_blocks_fetched)
                            ELSE 1
                        END as cache_hit_ratio,
                        -- Calculate I/O fractions
                        n_blocks_fetched / NULLIF(SUM(n_blocks_fetched) OVER (), 0) AS total_read_frac,
                        data_io_time / NULLIF(SUM(data_io_time) OVER (), 0) AS data_io_time_frac,
                        -- Calculate I/O score based on available metrics
                        (n_blocks_fetched * 0.5 +
                         data_io_time * 0.3 +
                         CASE
                             WHEN (n_blocks_hit + n_blocks_fetched) > 0
                             THEN 1 - n_blocks_hit::float / (n_blocks_hit + n_blocks_fetched)
                             ELSE 0
                         END * 0.2) as io_score
                    FROM {DBE_PERF_STATEMENT}
                    WHERE n_calls > 0
                )
                SELECT
                    query,
                    calls,
                    rows,
                    total_elapse_time,
                    mean_exec_time,
                    n_blocks_hit,
                    n_blocks_fetched,
                    data_io_time,
                    cache_hit_ratio,
                    total_read_frac,
                    data_io_time_frac,
                    io_score
                FROM io_metrics
                WHERE
                    total_read_frac > {io_threshold}
                    OR data_io_time_frac > {io_threshold}
                    OR cache_hit_ratio < 0.8  -- Low cache hit ratio
                ORDER BY io_score DESC, n_blocks_fetched DESC
                LIMIT 15
            """,
            )

            logger.debug(f"Executing I/O intensive query: {query}")
            io_query_rows = await SafeSqlDriver.execute_param_query(
                self.sql_driver,
                query,
            )
            io_queries = [row.cells for row in io_query_rows] if io_query_rows else []
            logger.info(f"Found {len(io_queries)} I/O-intensive queries")

            # Format results with I/O metrics
            if io_queries:
                result = ["Top I/O-intensive queries:"]
                for i, query in enumerate(io_queries, 1):
                    result.append(f"\n{i}. Query: {query['query'][:100]}...")
                    result.append(f"   Calls: {query['calls']}, Rows: {query['rows']}")
                    result.append(f"   Total Time: {query['total_elapse_time']:.2f}ms, Avg Time: {query['mean_exec_time']:.2f}ms")
                    result.append(f"   Blocks Read: {query['n_blocks_fetched']}")
                    result.append(f"   Blocks Hit: {query['n_blocks_hit']}")
                    result.append(f"   Cache Hit Ratio: {query['cache_hit_ratio']:.2%}")
                    result.append(f"   Data I/O Time: {query.get('data_io_time', 0):.2f}ms")
                    result.append(f"   I/O Score: {query.get('io_score', 0):.2f}")
                
                return "\n".join(result)
            else:
                return "No I/O-intensive queries found."
        except Exception as e:
            logger.error(f"Error getting I/O-intensive queries: {e}", exc_info=True)
            return f"Error getting I/O-intensive queries: {e}"

    
    async def get_queries_with_resource_metrics(
        self,
        limit: int = 20
    ) -> str:
        """Get queries with detailed resource consumption metrics.

        Args:
            limit: Maximum number of queries to return

        Returns:
            Formatted string with queries and their resource metrics
        """
        try:
            # Check database type and dbe_perf availability
            db_type = await get_database_type(self.sql_driver)
            logger.debug(f"Database type: {db_type}")
            
            if db_type != "opengauss":
                logger.warning(f"Unsupported database type: {db_type}")
                return dbe_perf_unavailable_message
            
            dbe_perf_available, dbe_perf_message = await check_dbe_perf_availability(
                self.sql_driver, message_type="plain"
            )
            
            if not dbe_perf_available:
                logger.warning("dbe_perf.statement view is not available")
                return dbe_perf_message
            
            # Query with only existing fields from dbe_perf.statement
            query = cast(
                LiteralString,
                f"""
                SELECT
                    query,
                    n_calls as calls,
                    total_elapse_time as total_exec_time,
                    total_elapse_time / NULLIF(n_calls, 0) as mean_exec_time,
                    min_elapse_time as min_exec_time,
                    max_elapse_time as max_exec_time,
                    cpu_time,
                    -- data_io_time, -- 实际无此字段
                    lock_wait_time,
                    n_blocks_hit,
                    n_blocks_fetched,
                    n_returned_rows as rows_returned,
                    n_tuples_fetched as rows_fetched,
                    n_tuples_inserted as rows_inserted,
                    n_tuples_updated as rows_updated,
                    n_tuples_deleted as rows_deleted,
                    sort_time,
                    hash_time,
                    sort_mem_used,
                    sort_spill_count,
                    sort_spill_size,
                    hash_mem_used,
                    hash_spill_count,
                    hash_spill_size
                FROM {DBE_PERF_STATEMENT}
                WHERE n_calls > 0
                ORDER BY total_elapse_time DESC
                LIMIT {limit}
                """
            )
            
            logger.debug(f"Executing resource metrics query: {query}")
            result = await self.sql_driver.execute_query(query)
            
            if not result:
                return "No queries found with resource consumption metrics."
            
            # Format results
            result_text = [f"Top {limit} queries by total execution time with resource metrics:"]
            
            for row in result:
                query_data = row.cells
                query_text = query_data["query"]
                # Truncate long queries for readability
                if len(query_text) > 100:
                    query_text = query_text[:100] + "..."
                
                result_text.append(f"\nQuery: {query_text}")
                result_text.append(f"  Calls: {query_data['calls']}")
                result_text.append(f"  Total Exec Time: {query_data['total_exec_time']} ms")
                result_text.append(f"  Mean Exec Time: {query_data['mean_exec_time']} ms")
                result_text.append(f"  Min Exec Time: {query_data['min_exec_time']} ms")
                result_text.append(f"  Max Exec Time: {query_data['max_exec_time']} ms")
                
                # Add openGauss specific resource metrics
                result_text.append(f"  CPU Time: {query_data['cpu_time']} ms")
                result_text.append(f"  Data I/O Time: {query_data['data_io_time']} ms")
                result_text.append(f"  Lock Wait Time: {query_data['lock_wait_time']} ms")
                result_text.append(f"  Blocks Hit: {query_data['n_blocks_hit']}")
                result_text.append(f"  Blocks Fetched: {query_data['n_blocks_fetched']}")
                
                # Add sort and hash metrics
                result_text.append(f"  Sort Time: {query_data['sort_time']} ms")
                result_text.append(f"  Sort Memory Used: {query_data['sort_mem_used']} KB")
                result_text.append(f"  Sort Spill Count: {query_data['sort_spill_count']}")
                result_text.append(f"  Sort Spill Size: {query_data['sort_spill_size']} KB")
                result_text.append(f"  Hash Time: {query_data['hash_time']} ms")
                result_text.append(f"  Hash Memory Used: {query_data['hash_mem_used']} KB")
                result_text.append(f"  Hash Spill Count: {query_data['hash_spill_count']}")
                result_text.append(f"  Hash Spill Size: {query_data['hash_spill_size']} KB")
                
                # Add memory metrics
                result_text.append(f"  Total Used Memory: {query_data['total_used_memory']} MB")
                result_text.append(f"  Max Used Memory: {query_data['max_used_memory']} MB")
                result_text.append(f"  Min Used Memory: {query_data['min_used_memory']} MB")
                
                # Add row metrics
                result_text.append(f"  Rows Returned: {query_data['rows_returned']}")
                result_text.append(f"  Rows Fetched: {query_data['rows_fetched']}")
                result_text.append(f"  Rows Inserted: {query_data['rows_inserted']}")
                result_text.append(f"  Rows Updated: {query_data['rows_updated']}")
                result_text.append(f"  Rows Deleted: {query_data['rows_deleted']}")
            
            return "\n".join(result_text)
        except Exception as e:
            logger.error(f"Error getting queries with resource metrics: {e}", exc_info=True)
            return f"Error getting queries with resource metrics: {e}"
    
    async def get_queries_by_resource_efficiency(
        self,
        limit: int = 20
    ) -> str:
        """Get queries ranked by resource efficiency (rows returned per resource unit).

        Args:
            limit: Maximum number of queries to return

        Returns:
            Formatted string with queries ranked by resource efficiency
        """
        try:
            # Check database type and dbe_perf availability
            db_type = await get_database_type(self.sql_driver)
            logger.debug(f"Database type: {db_type}")
            
            if db_type != "opengauss":
                logger.warning(f"Unsupported database type: {db_type}")
                return dbe_perf_unavailable_message
            
            dbe_perf_available, dbe_perf_message = await check_dbe_perf_availability(
                self.sql_driver, message_type="plain"
            )
            
            if not dbe_perf_available:
                logger.warning("dbe_perf.statement view is not available")
                return dbe_perf_message
            
            # Query with only existing fields from dbe_perf.statement
            query = cast(
                LiteralString,
                f"""
                SELECT
                    query,
                    n_calls as calls,
                    total_elapse_time as total_exec_time,
                    total_elapse_time / NULLIF(n_calls, 0) as mean_exec_time,
                    cpu_time,
                    data_io_time,
                    n_returned_rows as rows_returned,
                    n_tuples_fetched as rows_fetched,
                    n_blocks_hit,
                    n_blocks_fetched,
                    -- Calculate efficiency metrics
                    CASE
                        WHEN total_elapse_time > 0
                        THEN n_returned_rows::float / total_elapse_time
                        ELSE 0
                    END as rows_per_ms_time,
                    CASE
                        WHEN cpu_time > 0
                        THEN n_returned_rows::float / cpu_time
                        ELSE 0
                    END as rows_per_ms_cpu,
                    CASE
                        WHEN data_io_time > 0
                        THEN n_returned_rows::float / data_io_time
                        ELSE 0
                    END as rows_per_ms_io,
                    CASE
                        WHEN n_blocks_fetched > 0
                        THEN n_returned_rows::float / n_blocks_fetched
                        ELSE 0
                    END as rows_per_block_read,
                    CASE
                        WHEN n_blocks_hit > 0
                        THEN n_returned_rows::float / n_blocks_hit
                        ELSE 0
                    END as rows_per_block_hit,
                    -- Calculate cache hit ratio
                    CASE
                        WHEN (n_blocks_hit + n_blocks_fetched) > 0
                        THEN n_blocks_hit::float / (n_blocks_hit + n_blocks_fetched)
                        ELSE 1
                    END as cache_hit_ratio
                FROM {DBE_PERF_STATEMENT}
                WHERE n_calls > 0 AND n_returned_rows > 0
                ORDER BY rows_per_ms_time DESC
                LIMIT {limit}
                """
            )
            
            logger.debug(f"Executing resource efficiency query: {query}")
            result = await self.sql_driver.execute_query(query)
            
            if not result:
                return "No queries found with resource efficiency metrics."
            
            # Format results
            result_text = [f"Top {limit} queries by resource efficiency (rows per time unit):"]
            
            for row in result:
                query_data = row.cells
                query_text = query_data["query"]
                # Truncate long queries for readability
                if len(query_text) > 100:
                    query_text = query_text[:100] + "..."
                
                result_text.append(f"\nQuery: {query_text}")
                result_text.append(f"  Calls: {query_data['calls']}")
                result_text.append(f"  Total Exec Time: {query_data['total_exec_time']} ms")
                result_text.append(f"  Mean Exec Time: {query_data['mean_exec_time']} ms")
                result_text.append(f"  Rows Returned: {query_data['rows_returned']}")
                result_text.append(f"  Rows Fetched: {query_data['rows_fetched']}")
                result_text.append(f"  Rows per ms Time: {query_data['rows_per_ms_time']:.2f}")
                result_text.append(f"  Rows per ms CPU: {query_data['rows_per_ms_cpu']:.2f}")
                result_text.append(f"  Rows per ms I/O: {query_data['rows_per_ms_io']:.2f}")
                result_text.append(f"  Rows per Block Read: {query_data['rows_per_block_read']:.2f}")
                result_text.append(f"  Rows per Block Hit: {query_data['rows_per_block_hit']:.2f}")
                result_text.append(f"  Cache Hit Ratio: {query_data['cache_hit_ratio']:.2%}")
                result_text.append(f"  CPU Time: {query_data['cpu_time']} ms")
                result_text.append(f"  Data I/O Time: {query_data['data_io_time']} ms")
                result_text.append(f"  Blocks Hit: {query_data['n_blocks_hit']}")
                result_text.append(f"  Blocks Fetched: {query_data['n_blocks_fetched']}")
            
            return "\n".join(result_text)
        except Exception as e:
            logger.error(f"Error getting queries by resource efficiency: {e}", exc_info=True)
            return f"Error getting queries by resource efficiency: {e}"
