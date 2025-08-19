"""
GaussDB health check adapters.

This module provides GaussDB-specific adapters for all health check calculators,
handling differences in system views, query syntax, and feature availability
between PostgreSQL and GaussDB.
"""

import logging
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Union

from ..database_health.buffer_health_calc import BufferHealthCalc
from ..database_health.connection_health_calc import ConnectionHealthCalc
from ..database_health.constraint_health_calc import ConstraintHealthCalc
from ..database_health.constraint_health_calc import ConstraintMetrics
from ..database_health.index_health_calc import IndexHealthCalc
from ..database_health.replication_calc import ReplicationCalc
from ..database_health.replication_calc import ReplicationMetrics
from ..database_health.replication_calc import ReplicationSlot
from ..database_health.sequence_health_calc import SequenceHealthCalc
from ..database_health.sequence_health_calc import SequenceMetrics
from ..database_health.vacuum_health_calc import TransactionIdMetrics
from ..database_health.vacuum_health_calc import VacuumHealthCalc
from ..sql import SafeSqlDriver
from ..sql import SqlDriver
from .sql_driver_adapter import GaussDbSqlDriver

logger = logging.getLogger(__name__)


class GaussDbIndexHealthCalc(IndexHealthCalc):
    """
    GaussDB adapter for index health calculations.
    
    This class extends the base IndexHealthCalc to handle GaussDB-specific
    differences in system views and query syntax for index health checks.
    """

    def __init__(self, sql_driver: Union[SqlDriver, GaussDbSqlDriver]):
        """
        Initialize GaussDB index health calculator.
        
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

        logger.debug("GaussDbIndexHealthCalc initialized")

    async def invalid_index_check(self) -> str:
        """
        Check for invalid indexes with GaussDB compatibility.
        
        Returns:
            String describing any invalid indexes found
        """
        try:
            # Try GaussDB-specific approach first
            return await self._gaussdb_invalid_index_check()
        except Exception as e:
            logger.warning(f"GaussDB-specific invalid index check failed: {e}")
            # Fallback to PostgreSQL compatible approach
            return await super().invalid_index_check()

    async def _gaussdb_invalid_index_check(self) -> str:
        """GaussDB-specific invalid index check implementation."""
        # Use adapted query through GaussDB driver
        indexes = await self._gaussdb_indexes()

        # Check for invalid indexes
        invalid_indexes = [idx for idx in indexes if not idx["valid"]]
        if not invalid_indexes:
            return "No invalid indexes found."

        return "Invalid indexes found: " + "\n".join([
            f"{idx['name']} on {idx['table']} is invalid."
            for idx in invalid_indexes
        ])

    async def duplicate_index_check(self) -> str:
        """
        Check for duplicate indexes with GaussDB compatibility.
        
        Returns:
            String describing any duplicate indexes found
        """
        try:
            # Try GaussDB-specific approach first
            return await self._gaussdb_duplicate_index_check()
        except Exception as e:
            logger.warning(f"GaussDB-specific duplicate index check failed: {e}")
            # Fallback to PostgreSQL compatible approach
            return await super().duplicate_index_check()

    async def _gaussdb_duplicate_index_check(self) -> str:
        """GaussDB-specific duplicate index check implementation."""
        indexes = await self._gaussdb_indexes()
        dup_indexes = []

        # Group indexes by schema and table
        indexes_by_table = {}
        for idx in indexes:
            key = (idx["schema"], idx["table"])
            if key not in indexes_by_table:
                indexes_by_table[key] = []
            indexes_by_table[key].append(idx)

        # Check each valid non-primary/unique index for duplicates
        for index in [i for i in indexes if i["valid"] and not i["primary"] and not i["unique"]]:
            table_indexes = indexes_by_table[(index["schema"], index["table"])]

            # Find covering indexes
            for covering_idx in table_indexes:
                if (
                    covering_idx["valid"]
                    and covering_idx["name"] != index["name"]
                    and self._index_covers(covering_idx["columns"], index["columns"])
                    and covering_idx["using"] == index["using"]
                    and covering_idx["indexprs"] == index["indexprs"]
                    and covering_idx["indpred"] == index["indpred"]
                ):
                    # Add to duplicates if conditions are met
                    if (
                        covering_idx["columns"] != index["columns"]
                        or index["name"] > covering_idx["name"]
                        or covering_idx["primary"]
                        or covering_idx["unique"]
                    ):
                        dup_indexes.append({"unneeded_index": index, "covering_index": covering_idx})
                        break

        if not dup_indexes:
            return "No duplicate indexes found."

        # Sort by table and columns and format the output
        sorted_dups = sorted(
            dup_indexes,
            key=lambda x: (
                x["unneeded_index"]["table"],
                x["unneeded_index"]["columns"],
            ),
        )

        result = ["Duplicate indexes found:"]
        for dup in sorted_dups:
            result.append(
                f"Index '{dup['unneeded_index']['name']}' on table '{dup['unneeded_index']['table']}' "
                f"is covered by index '{dup['covering_index']['name']}'"
            )

        return "\n".join(result)

    async def index_bloat(self, min_size: int = 104857600) -> str:
        """
        Check for bloated indexes with GaussDB compatibility.
        
        Args:
            min_size: Minimum size in bytes to consider an index as bloated (default 100MB)
            
        Returns:
            String describing any bloated indexes found
        """
        try:
            # Try GaussDB-specific approach first
            return await self._gaussdb_index_bloat(min_size)
        except Exception as e:
            logger.warning(f"GaussDB-specific index bloat check failed: {e}")
            # Fallback to PostgreSQL compatible approach
            return await super().index_bloat(min_size)

    async def _gaussdb_index_bloat(self, min_size: int) -> str:
        """GaussDB-specific index bloat check implementation."""
        # Use the adapted query through GaussDB driver
        bloated_indexes = await SafeSqlDriver.execute_param_query(
            self.gaussdb_driver,
            """
            WITH btree_index_atts AS (
                SELECT
                    nspname, relname, reltuples, relpages, indrelid, relam,
                    regexp_split_to_table(indkey::text, ' ')::smallint AS attnum,
                    indexrelid as index_oid
                FROM
                    pg_index
                JOIN
                    pg_class ON pg_class.oid = pg_index.indexrelid
                JOIN
                    pg_namespace ON pg_namespace.oid = pg_class.relnamespace
                JOIN
                    pg_am ON pg_class.relam = pg_am.oid
                WHERE
                    pg_am.amname = 'btree'
            ),
            index_item_sizes AS (
                SELECT
                    i.nspname,
                    i.relname,
                    i.reltuples,
                    i.relpages,
                    i.relam,
                    (quote_ident(s.schemaname) || '.' || quote_ident(s.tablename))::regclass AS starelid,
                    a.attrelid AS table_oid, index_oid,
                    current_setting('block_size')::numeric AS bs,
                    CASE
                        WHEN version() ~ 'mingw32' OR version() ~ '64-bit' THEN 8
                        ELSE 4
                    END AS maxalign,
                    24 AS pagehdr,
                    CASE WHEN max(coalesce(s.null_frac,0)) = 0
                        THEN 2
                        ELSE 6
                    END AS index_tuple_hdr,
                    sum( (1-coalesce(s.null_frac, 0)) * coalesce(s.avg_width, 2048) ) AS nulldatawidth
                FROM
                    pg_attribute AS a
                JOIN
                    pg_stats AS s ON (quote_ident(s.schemaname) || '.' || quote_ident(s.tablename))::regclass=a.attrelid AND s.attname = a.attname
                JOIN
                    btree_index_atts AS i ON i.indrelid = a.attrelid AND a.attnum = i.attnum
                WHERE
                    a.attnum > 0
                GROUP BY
                    1, 2, 3, 4, 5, 6, 7, 8, 9
            ),
            index_aligned AS (
                SELECT
                    maxalign,
                    bs,
                    nspname,
                    relname AS index_name,
                    reltuples,
                    relpages,
                    relam,
                    table_oid,
                    index_oid,
                    ( 2 +
                        maxalign - CASE
                            WHEN index_tuple_hdr%maxalign = 0 THEN maxalign
                            ELSE index_tuple_hdr%maxalign
                        END
                    + nulldatawidth + maxalign - CASE
                            WHEN nulldatawidth::integer%maxalign = 0 THEN maxalign
                            ELSE nulldatawidth::integer%maxalign
                        END
                    )::numeric AS nulldatahdrwidth, pagehdr
                FROM
                    index_item_sizes AS s1
            ),
            otta_calc AS (
                SELECT
                    bs,
                    nspname,
                    table_oid,
                    index_oid,
                    index_name,
                    relpages,
                    coalesce(
                        ceil((reltuples*(4+nulldatahdrwidth))/(bs-pagehdr::float)) +
                        CASE WHEN am.amname IN ('hash','btree') THEN 1 ELSE 0 END , 0
                    ) AS otta
                FROM
                    index_aligned AS s2
                LEFT JOIN
                    pg_am am ON s2.relam = am.oid
            ),
            raw_bloat AS (
                SELECT
                    nspname,
                    c.relname AS table_name,
                    index_name,
                    bs*(sub.relpages)::bigint AS totalbytes,
                    CASE
                        WHEN sub.relpages <= otta THEN 0
                        ELSE bs*(sub.relpages-otta)::bigint END
                        AS wastedbytes,
                    CASE
                        WHEN sub.relpages <= otta
                        THEN 0 ELSE bs*(sub.relpages-otta)::bigint * 100 / (bs*(sub.relpages)::bigint) END
                        AS realbloat,
                    pg_relation_size(sub.table_oid) as table_bytes,
                    stat.idx_scan as index_scans,
                    stat.indexrelid
                FROM
                    otta_calc AS sub
                JOIN
                    pg_class AS c ON c.oid=sub.table_oid
                JOIN
                    pg_stat_user_indexes AS stat ON sub.index_oid = stat.indexrelid
            )
            SELECT
                nspname AS schema,
                table_name AS table,
                index_name AS index,
                wastedbytes AS bloat_bytes,
                totalbytes AS index_bytes,
                pg_get_indexdef(rb.indexrelid) AS definition,
                indisprimary AS primary
            FROM
                raw_bloat rb
            INNER JOIN
                pg_index i ON i.indexrelid = rb.indexrelid
            WHERE
                wastedbytes >= {}
            ORDER BY
                wastedbytes DESC,
                index_name
        """,
            [min_size],
        )

        if not bloated_indexes:
            return "No bloated indexes found."

        result = ["Bloated indexes found:"]
        # Convert RowResults to dicts first
        bloated_indexes_dicts = [dict(idx.cells) for idx in bloated_indexes]
        for idx in bloated_indexes_dicts:
            bloat_mb = int(idx["bloat_bytes"]) / (1024 * 1024)
            total_mb = int(idx["index_bytes"]) / (1024 * 1024)
            result.append(
                f"Index '{idx['index']}' on table '{idx['table']}' has {bloat_mb:.1f}MB bloat "
                f"out of {total_mb:.1f}MB total size"
            )

        return "\n".join(result)

    async def unused_indexes(self, max_scans: int = 50) -> str:
        """
        Check for unused or rarely used indexes with GaussDB compatibility.
        
        Args:
            max_scans: Maximum number of scans to consider an index as unused (default 50)
            
        Returns:
            String describing any unused indexes found
        """
        try:
            # Try GaussDB-specific approach first
            return await self._gaussdb_unused_indexes(max_scans)
        except Exception as e:
            logger.warning(f"GaussDB-specific unused indexes check failed: {e}")
            # Fallback to PostgreSQL compatible approach
            return await super().unused_indexes(max_scans)

    async def _gaussdb_unused_indexes(self, max_scans: int) -> str:
        """GaussDB-specific unused indexes check implementation."""
        unused = await SafeSqlDriver.execute_param_query(
            self.gaussdb_driver,
            """
            SELECT
                schemaname AS schema,
                relname AS table,
                indexrelname AS index,
                pg_relation_size(i.indexrelid) AS size_bytes,
                idx_scan as index_scans,
                pg_get_indexdef(i.indexrelid) AS definition,
                indisprimary AS primary
            FROM
                pg_stat_user_indexes ui
            INNER JOIN
                pg_index i ON ui.indexrelid = i.indexrelid
            WHERE
                NOT indisunique
                AND idx_scan <= {}
            ORDER BY
                pg_relation_size(i.indexrelid) DESC,
                relname ASC
        """,
            [max_scans],
        )

        if not unused:
            return "No unused indexes found."

        indexes = [dict(idx.cells) for idx in unused]

        result = ["Rarely used indexes found:"]
        for idx in indexes:
            if idx["primary"]:
                continue
            size_mb = int(idx["size_bytes"]) / (1024 * 1024)
            result.append(
                f"Index '{idx['index']}' on table '{idx['table']}' has only been scanned "
                f"{idx['index_scans']} times and uses {size_mb:.1f}MB of space"
            )

        return "\n".join(result)

    async def _gaussdb_indexes(self) -> List[Dict[str, Any]]:
        """
        Get index information using GaussDB-compatible queries.
        
        Returns:
            List of index dictionaries with GaussDB-specific adaptations
        """
        if self._cached_indexes:
            return self._cached_indexes

        # Get index information using adapted query
        results = await self.gaussdb_driver.execute_query("""
            SELECT
                schemaname AS schema,
                t.relname AS table,
                ix.relname AS name,
                regexp_replace(pg_get_indexdef(i.indexrelid), '^[^\\(]*\\((.*)\\).*', '\\1') AS columns,
                regexp_replace(pg_get_indexdef(i.indexrelid), '.* USING ([^ ]*) \\(.*', '\\1') AS using,
                indisunique AS unique,
                indisprimary AS primary,
                indisvalid AS valid,
                indexprs::text,
                indpred::text,
                pg_get_indexdef(i.indexrelid) AS definition
            FROM
                pg_index i
            INNER JOIN
                pg_class t ON t.oid = i.indrelid
            INNER JOIN
                pg_class ix ON ix.oid = i.indexrelid
            LEFT JOIN
                pg_stat_user_indexes ui ON ui.indexrelid = i.indexrelid
            WHERE
                schemaname IS NOT NULL
            ORDER BY
                1, 2
        """)

        if results is None:
            return []

        # Convert RowResults to dicts
        indexes = [dict(idx.cells) for idx in results]

        # Process columns
        for idx in indexes:
            cols = idx["columns"]
            cols = cols.replace(") WHERE (", " WHERE ").split(", ")
            # Unquote column names
            idx["columns"] = [col.strip('"') for col in cols]

        self._cached_indexes = indexes
        return indexes


class GaussDbConnectionHealthCalc(ConnectionHealthCalc):
    """
    GaussDB adapter for connection health calculations.
    
    This class extends the base ConnectionHealthCalc to handle GaussDB-specific
    differences in connection statistics views and query syntax.
    """

    def __init__(
        self,
        sql_driver: Union[SqlDriver, GaussDbSqlDriver],
        max_total_connections: int = 500,
        max_idle_connections: int = 100,
    ):
        """
        Initialize GaussDB connection health calculator.
        
        Args:
            sql_driver: SQL driver (can be regular SqlDriver or GaussDbSqlDriver)
            max_total_connections: Maximum healthy total connections
            max_idle_connections: Maximum healthy idle connections
        """
        # If we get a regular SqlDriver, wrap it with GaussDbSqlDriver
        if isinstance(sql_driver, GaussDbSqlDriver):
            super().__init__(sql_driver.base_driver, max_total_connections, max_idle_connections)
            self.gaussdb_driver = sql_driver
        else:
            super().__init__(sql_driver, max_total_connections, max_idle_connections)
            self.gaussdb_driver = GaussDbSqlDriver(sql_driver)

        logger.debug("GaussDbConnectionHealthCalc initialized")

    async def total_connections_check(self) -> str:
        """Check if total number of connections is within healthy limits."""
        try:
            # Try GaussDB-specific approach first
            total = await self._gaussdb_get_total_connections()
        except Exception as e:
            logger.warning(f"GaussDB-specific total connections check failed: {e}")
            # Fallback to PostgreSQL compatible approach
            total = await self._get_total_connections()

        if total <= self.max_total_connections:
            return f"Total connections healthy: {total}"
        return f"High number of connections: {total} (max: {self.max_total_connections})"

    async def idle_connections_check(self) -> str:
        """Check if number of idle connections is within healthy limits."""
        try:
            # Try GaussDB-specific approach first
            idle = await self._gaussdb_get_idle_connections()
        except Exception as e:
            logger.warning(f"GaussDB-specific idle connections check failed: {e}")
            # Fallback to PostgreSQL compatible approach
            idle = await self._get_idle_connections()

        if idle <= self.max_idle_connections:
            return f"Idle connections healthy: {idle}"
        return f"High number of idle connections: {idle} (max: {self.max_idle_connections})"

    async def connection_health_check(self) -> str:
        """Run all connection health checks and return combined results."""
        try:
            # Try GaussDB-specific approach first
            total = await self._gaussdb_get_total_connections()
            idle = await self._gaussdb_get_idle_connections()
        except Exception as e:
            logger.warning(f"GaussDB-specific connection health check failed: {e}")
            # Fallback to PostgreSQL compatible approach
            total = await self._get_total_connections()
            idle = await self._get_idle_connections()

        if total > self.max_total_connections:
            return f"High number of connections: {total}"
        elif idle > self.max_idle_connections:
            return f"High number of connections idle in transaction: {idle}"
        else:
            return f"Connections healthy: {total} total, {idle} idle"

    async def _gaussdb_get_total_connections(self) -> int:
        """Get the total number of database connections using GaussDB-compatible query."""
        result = await self.gaussdb_driver.execute_query("""
            SELECT COUNT(*) as count
            FROM pg_stat_activity
        """)
        result_list = [dict(x.cells) for x in result] if result else []
        return result_list[0]["count"] if result_list else 0

    async def _gaussdb_get_idle_connections(self) -> int:
        """Get the number of connections that are idle in transaction using GaussDB-compatible query."""
        result = await self.gaussdb_driver.execute_query("""
            SELECT COUNT(*) as count
            FROM pg_stat_activity
            WHERE state = 'idle in transaction'
        """)
        result_list = [dict(x.cells) for x in result] if result else []
        return result_list[0]["count"] if result_list else 0

    async def get_connection_details(self) -> Dict[str, Any]:
        """
        Get detailed connection information with GaussDB-specific fields.
        
        Returns:
            Dictionary with detailed connection statistics
        """
        try:
            # Try GaussDB-specific detailed query
            result = await self.gaussdb_driver.execute_query("""
                SELECT
                    state,
                    COUNT(*) as count,
                    application_name,
                    client_addr,
                    backend_start,
                    query_start,
                    state_change
                FROM pg_stat_activity
                WHERE state IS NOT NULL
                GROUP BY state, application_name, client_addr, backend_start, query_start, state_change
                ORDER BY count DESC
            """)

            if result:
                connections = [dict(row.cells) for row in result]
                return {
                    "total_connections": sum(conn["count"] for conn in connections),
                    "connections_by_state": connections,
                    "unique_applications": len(set(conn["application_name"] for conn in connections if conn["application_name"])),
                    "unique_clients": len(set(conn["client_addr"] for conn in connections if conn["client_addr"]))
                }
            else:
                return {"error": "No connection data available"}

        except Exception as e:
            logger.warning(f"GaussDB-specific connection details failed: {e}")
            # Fallback to basic connection counts
            total = await self._get_total_connections()
            idle = await self._get_idle_connections()
            return {
                "total_connections": total,
                "idle_connections": idle,
                "active_connections": total - idle
            }


class GaussDbBufferHealthCalc(BufferHealthCalc):
    """
    GaussDB adapter for buffer health calculations.
    
    This class extends the base BufferHealthCalc to handle GaussDB-specific
    differences in buffer statistics views and calculations.
    """

    def __init__(self, sql_driver: Union[SqlDriver, GaussDbSqlDriver]):
        """
        Initialize GaussDB buffer health calculator.
        
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

        logger.debug("GaussDbBufferHealthCalc initialized")

    async def index_hit_rate(self, threshold: float = 0.95) -> str:
        """
        Calculate the index cache hit rate with GaussDB compatibility.
        
        Args:
            threshold: Minimum acceptable hit rate (default 0.95)
            
        Returns:
            String describing the index cache hit rate
        """
        try:
            # Try GaussDB-specific approach first
            return await self._gaussdb_index_hit_rate(threshold)
        except Exception as e:
            logger.warning(f"GaussDB-specific index hit rate check failed: {e}")
            # Fallback to PostgreSQL compatible approach
            return await super().index_hit_rate(threshold)

    async def _gaussdb_index_hit_rate(self, threshold: float) -> str:
        """GaussDB-specific index hit rate calculation."""
        result = await self.gaussdb_driver.execute_query("""
            SELECT
                (sum(idx_blks_hit)) / nullif(sum(idx_blks_hit + idx_blks_read), 0) AS rate
            FROM
                pg_statio_user_indexes
        """)

        result_list = [dict(x.cells) for x in result] if result else []

        if not result_list or result_list[0]["rate"] is None:
            return "No index cache statistics available."

        hit_rate = float(result_list[0]["rate"]) * 100
        threshold_pct = threshold * 100

        if hit_rate >= threshold_pct:
            return f"Index cache hit rate: {hit_rate:.1f}% (above {threshold_pct:.1f}% threshold)"
        else:
            return f"Index cache hit rate: {hit_rate:.1f}% (below {threshold_pct:.1f}% threshold)"

    async def table_hit_rate(self, threshold: float = 0.95) -> str:
        """
        Calculate the table cache hit rate with GaussDB compatibility.
        
        Args:
            threshold: Minimum acceptable hit rate (default 0.95)
            
        Returns:
            String describing the table cache hit rate
        """
        try:
            # Try GaussDB-specific approach first
            return await self._gaussdb_table_hit_rate(threshold)
        except Exception as e:
            logger.warning(f"GaussDB-specific table hit rate check failed: {e}")
            # Fallback to PostgreSQL compatible approach
            return await super().table_hit_rate(threshold)

    async def _gaussdb_table_hit_rate(self, threshold: float) -> str:
        """GaussDB-specific table hit rate calculation."""
        result = await self.gaussdb_driver.execute_query("""
            SELECT
                sum(heap_blks_hit) / nullif(sum(heap_blks_hit + heap_blks_read), 0) AS rate
            FROM
                pg_statio_user_tables
        """)

        result_list = [dict(x.cells) for x in result] if result else []

        if not result_list or result_list[0]["rate"] is None:
            return "No table cache statistics available."

        hit_rate = float(result_list[0]["rate"]) * 100
        threshold_pct = threshold * 100

        if hit_rate >= threshold_pct:
            return f"Table cache hit rate: {hit_rate:.1f}% (above {threshold_pct:.1f}% threshold)"
        else:
            return f"Table cache hit rate: {hit_rate:.1f}% (below {threshold_pct:.1f}% threshold)"

    async def get_buffer_statistics(self) -> Dict[str, Any]:
        """
        Get comprehensive buffer statistics with GaussDB-specific metrics.
        
        Returns:
            Dictionary with buffer statistics
        """
        try:
            # Try to get GaussDB-specific buffer statistics
            result = await self.gaussdb_driver.execute_query("""
                SELECT
                    'shared_buffers' as setting_name,
                    setting as setting_value,
                    unit
                FROM pg_settings
                WHERE name = 'shared_buffers'
                UNION ALL
                SELECT
                    'effective_cache_size' as setting_name,
                    setting as setting_value,
                    unit
                FROM pg_settings
                WHERE name = 'effective_cache_size'
            """)

            if result:
                settings = [dict(row.cells) for row in result]
                buffer_stats = {setting["setting_name"]: setting["setting_value"] for setting in settings}

                # Add hit rates
                index_rate = await self._gaussdb_index_hit_rate(0.95)
                table_rate = await self._gaussdb_table_hit_rate(0.95)

                buffer_stats.update({
                    "index_hit_rate_status": index_rate,
                    "table_hit_rate_status": table_rate
                })

                return buffer_stats
            else:
                return {"error": "No buffer statistics available"}

        except Exception as e:
            logger.warning(f"GaussDB-specific buffer statistics failed: {e}")
            return {"error": f"Failed to get buffer statistics: {e}"}


class GaussDbVacuumHealthCalc(VacuumHealthCalc):
    """
    GaussDB adapter for vacuum health calculations.
    
    This class extends the base VacuumHealthCalc to handle GaussDB-specific
    differences in vacuum statistics and transaction ID handling.
    """

    def __init__(
        self,
        sql_driver: Union[SqlDriver, GaussDbSqlDriver],
        threshold: int = 10000000,
        max_value: int = 2146483648,
    ):
        """
        Initialize GaussDB vacuum health calculator.
        
        Args:
            sql_driver: SQL driver (can be regular SqlDriver or GaussDbSqlDriver)
            threshold: Transaction ID threshold for warnings
            max_value: Maximum transaction ID value
        """
        # If we get a regular SqlDriver, wrap it with GaussDbSqlDriver
        if isinstance(sql_driver, GaussDbSqlDriver):
            super().__init__(sql_driver.base_driver, threshold, max_value)
            self.gaussdb_driver = sql_driver
        else:
            super().__init__(sql_driver, threshold, max_value)
            self.gaussdb_driver = GaussDbSqlDriver(sql_driver)

        logger.debug("GaussDbVacuumHealthCalc initialized")

    async def transaction_id_danger_check(self) -> str:
        """Check if any tables are approaching transaction ID wraparound."""
        try:
            # Try GaussDB-specific approach first
            return await self._gaussdb_transaction_id_danger_check()
        except Exception as e:
            logger.warning(f"GaussDB-specific transaction ID check failed: {e}")
            # Fallback to PostgreSQL compatible approach
            return await super().transaction_id_danger_check()

    async def _gaussdb_transaction_id_danger_check(self) -> str:
        """GaussDB-specific transaction ID danger check."""
        metrics = await self._gaussdb_get_transaction_id_metrics()

        if not metrics:
            return "No tables found with transaction ID wraparound danger."

        # Sort by transactions left ascending to show most critical first
        metrics.sort(key=lambda x: x.transactions_left)

        unhealthy = [m for m in metrics if not m.is_healthy]
        if not unhealthy:
            return "All tables have healthy transaction ID age."

        result = ["Tables approaching transaction ID wraparound:"]
        for metric in unhealthy:
            result.append(
                f"Table '{metric.schema}.{metric.table}' has {metric.transactions_left:,} transactions "
                f"remaining before wraparound (threshold: {self.threshold:,})"
            )
        return "\n".join(result)

    async def _gaussdb_get_transaction_id_metrics(self) -> List[TransactionIdMetrics]:
        """Get transaction ID metrics for all tables using GaussDB-compatible query."""
        results = await SafeSqlDriver.execute_param_query(
            self.gaussdb_driver,
            """
            SELECT
                n.nspname AS schema,
                c.relname AS table,
                {} - GREATEST(AGE(c.relfrozenxid), AGE(t.relfrozenxid)) AS transactions_left
            FROM
                pg_class c
            INNER JOIN
                pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            LEFT JOIN
                pg_class t ON c.reltoastrelid = t.oid
            WHERE
                c.relkind = 'r'
                AND ({} - GREATEST(AGE(c.relfrozenxid), AGE(t.relfrozenxid))) < {}
            ORDER BY
                3, 1, 2
        """,
            [self.max_value, self.max_value, self.threshold],
        )

        if not results:
            return []

        result_list = [dict(x.cells) for x in results]

        return [
            TransactionIdMetrics(
                schema=row["schema"],
                table=row["table"],
                transactions_left=row["transactions_left"],
                is_healthy=row["transactions_left"] >= self.threshold,
            )
            for row in result_list
        ]

    async def get_vacuum_statistics(self) -> Dict[str, Any]:
        """
        Get comprehensive vacuum statistics with GaussDB-specific information.
        
        Returns:
            Dictionary with vacuum statistics
        """
        try:
            # Get vacuum stats using GaussDB-compatible query
            result = await self.gaussdb_driver.execute_query("""
                SELECT
                    schemaname,
                    relname,
                    last_vacuum,
                    last_autovacuum,
                    vacuum_count,
                    autovacuum_count,
                    n_tup_ins,
                    n_tup_upd,
                    n_tup_del,
                    n_dead_tup
                FROM pg_stat_user_tables
                ORDER BY n_dead_tup DESC
            """)

            if result:
                tables = [dict(row.cells) for row in result]
                return {
                    "total_tables": len(tables),
                    "tables_with_dead_tuples": len([t for t in tables if t["n_dead_tup"] > 0]),
                    "tables_needing_vacuum": len([t for t in tables if t["n_dead_tup"] > 1000]),
                    "table_details": tables[:10]  # Top 10 tables by dead tuples
                }
            else:
                return {"error": "No vacuum statistics available"}

        except Exception as e:
            logger.warning(f"GaussDB-specific vacuum statistics failed: {e}")
            return {"error": f"Failed to get vacuum statistics: {e}"}


class GaussDbSequenceHealthCalc(SequenceHealthCalc):
    """
    GaussDB adapter for sequence health calculations.
    
    This class extends the base SequenceHealthCalc to handle GaussDB-specific
    differences in sequence statistics and management.
    """

    def __init__(self, sql_driver: Union[SqlDriver, GaussDbSqlDriver], threshold: float = 0.9):
        """
        Initialize GaussDB sequence health calculator.
        
        Args:
            sql_driver: SQL driver (can be regular SqlDriver or GaussDbSqlDriver)
            threshold: Percentage threshold for sequence usage warnings
        """
        # If we get a regular SqlDriver, wrap it with GaussDbSqlDriver
        if isinstance(sql_driver, GaussDbSqlDriver):
            super().__init__(sql_driver.base_driver, threshold)
            self.gaussdb_driver = sql_driver
        else:
            super().__init__(sql_driver, threshold)
            self.gaussdb_driver = GaussDbSqlDriver(sql_driver)

        logger.debug("GaussDbSequenceHealthCalc initialized")

    async def sequence_danger_check(self) -> str:
        """Check if any sequences are approaching their maximum values."""
        try:
            # Try GaussDB-specific approach first
            return await self._gaussdb_sequence_danger_check()
        except Exception as e:
            logger.warning(f"GaussDB-specific sequence danger check failed: {e}")
            # Fallback to PostgreSQL compatible approach
            return await super().sequence_danger_check()

    async def _gaussdb_sequence_danger_check(self) -> str:
        """GaussDB-specific sequence danger check."""
        metrics = await self._gaussdb_get_sequence_metrics()

        if not metrics:
            return "No sequences found in the database."

        # Sort by remaining values ascending to show most critical first
        metrics.sort(key=lambda x: x.max_value - x.last_value)

        unhealthy = [m for m in metrics if not m.is_healthy]
        if not unhealthy:
            return "All sequences have healthy usage levels."

        result = ["Sequences approaching maximum value:"]
        for metric in unhealthy:
            remaining = metric.max_value - metric.last_value
            result.append(
                f"Sequence '{metric.schema}.{metric.sequence}' used for {metric.table}.{metric.column} "
                f"has used {metric.percent_used:.1f}% of available values "
                f"({metric.last_value:,} of {metric.max_value:,}, {remaining:,} remaining)"
            )
        return "\n".join(result)

    async def _gaussdb_get_sequence_metrics(self) -> List[SequenceMetrics]:
        """Get metrics for sequences in the database using GaussDB-compatible queries."""
        # First get all sequences used as default values
        sequences = await self.gaussdb_driver.execute_query("""
            SELECT
                n.nspname AS table_schema,
                c.relname AS table,
                attname AS column,
                format_type(a.atttypid, a.atttypmod) AS column_type,
                pg_get_expr(d.adbin, d.adrelid) AS default_value
            FROM
                pg_catalog.pg_attribute a
            INNER JOIN
                pg_catalog.pg_class c ON c.oid = a.attrelid
            INNER JOIN
                pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            INNER JOIN
                pg_catalog.pg_attrdef d ON (a.attrelid, a.attnum) = (d.adrelid, d.adnum)
            WHERE
                NOT a.attisdropped
                AND a.attnum > 0
                AND pg_get_expr(d.adbin, d.adrelid) LIKE 'nextval%'
                AND n.nspname NOT LIKE 'pg\\_temp\\_%'
        """)

        if not sequences:
            return []

        result_list = [dict(x.cells) for x in sequences]

        # Process each sequence
        sequence_metrics = []
        for seq in result_list:
            # Parse the sequence name from default value
            schema, sequence = self._parse_sequence_name(seq["default_value"])
            if not sequence:
                continue

            # Determine max value based on column type
            max_value = 2147483647 if seq["column_type"] == "integer" else 9223372036854775807

            # Get sequence attributes using GaussDB-compatible query
            try:
                attrs = await self.gaussdb_driver.execute_query(f"""
                    SELECT
                        has_sequence_privilege('{schema}.{sequence}', 'SELECT') AS readable,
                        last_value
                    FROM {schema}.{sequence}
                """)

                if not attrs:
                    continue

                result_list_attrs = [dict(x.cells) for x in attrs]
                attr = result_list_attrs[0]

                sequence_metrics.append(
                    SequenceMetrics(
                        schema=schema,
                        table=seq["table"],
                        column=seq["column"],
                        sequence=sequence,
                        column_type=seq["column_type"],
                        last_value=attr["last_value"],
                        max_value=max_value,
                        readable=attr["readable"],
                        is_healthy=attr["last_value"] / max_value <= self.threshold,
                    )
                )
            except Exception as e:
                logger.warning(f"Failed to get sequence attributes for {schema}.{sequence}: {e}")
                continue

        return sequence_metrics


class GaussDbReplicationCalc(ReplicationCalc):
    """
    GaussDB adapter for replication health calculations.
    
    This class extends the base ReplicationCalc to handle GaussDB-specific
    differences in replication statistics and monitoring.
    """

    def __init__(self, sql_driver: Union[SqlDriver, GaussDbSqlDriver]):
        """
        Initialize GaussDB replication health calculator.
        
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

        logger.debug("GaussDbReplicationCalc initialized")

    async def replication_health_check(self) -> str:
        """Check replication health including lag and slots with GaussDB compatibility."""
        try:
            # Try GaussDB-specific approach first
            return await self._gaussdb_replication_health_check()
        except Exception as e:
            logger.warning(f"GaussDB-specific replication health check failed: {e}")
            # Fallback to PostgreSQL compatible approach
            return await super().replication_health_check()

    async def _gaussdb_replication_health_check(self) -> str:
        """GaussDB-specific replication health check."""
        metrics = await self._gaussdb_get_replication_metrics()
        result = []

        if metrics.is_replica:
            result.append("This is a replica database.")
            # Check replication status
            if not metrics.is_replicating:
                result.append("WARNING: Replica is not actively replicating from primary!")
            else:
                result.append("Replica is actively replicating from primary.")

            # Check replication lag
            if metrics.replication_lag_seconds is not None:
                if metrics.replication_lag_seconds == 0:
                    result.append("No replication lag detected.")
                else:
                    result.append(f"Replication lag: {metrics.replication_lag_seconds:.1f} seconds")
        else:
            result.append("This is a primary database.")
            if metrics.is_replicating:
                result.append("Has active replicas connected.")
            else:
                result.append("No active replicas connected.")

        # Check replication slots for both primary and replica
        if metrics.replication_slots:
            active_slots = [s for s in metrics.replication_slots if s.active]
            inactive_slots = [s for s in metrics.replication_slots if not s.active]

            if active_slots:
                result.append("\nActive replication slots:")
                for slot in active_slots:
                    result.append(f"- {slot.slot_name} (database: {slot.database})")

            if inactive_slots:
                result.append("\nInactive replication slots:")
                for slot in inactive_slots:
                    result.append(f"- {slot.slot_name} (database: {slot.database})")
        else:
            result.append("\nNo replication slots found.")

        return "\n".join(result)

    async def _gaussdb_get_replication_metrics(self) -> ReplicationMetrics:
        """Get comprehensive replication metrics using GaussDB-compatible queries."""
        return ReplicationMetrics(
            is_replica=await self._gaussdb_is_replica(),
            replication_lag_seconds=await self._gaussdb_get_replication_lag(),
            is_replicating=await self._gaussdb_is_replicating(),
            replication_slots=await self._gaussdb_get_replication_slots(),
        )

    async def _gaussdb_is_replica(self) -> bool:
        """Check if this database is a replica using GaussDB-compatible query."""
        result = await self.gaussdb_driver.execute_query("SELECT pg_is_in_recovery()")
        result_list = [dict(x.cells) for x in result] if result is not None else []
        return bool(result_list[0]["pg_is_in_recovery"]) if result_list else False

    async def _gaussdb_get_replication_lag(self) -> Optional[float]:
        """Get replication lag in seconds using GaussDB-compatible queries."""
        try:
            # Check if replication lag features are supported
            if not await self.gaussdb_driver.test_feature_support("replication_stats"):
                return None

            # Use appropriate functions based on database version
            server_version = await self._get_server_version()
            if server_version >= 100000:
                lag_condition = "pg_last_wal_receive_lsn() = pg_last_wal_replay_lsn()"
            else:
                lag_condition = "pg_last_xlog_receive_location() = pg_last_xlog_replay_location()"

            result = await self.gaussdb_driver.execute_query(f"""
                SELECT
                    CASE
                        WHEN NOT pg_is_in_recovery() OR {lag_condition} THEN 0
                        ELSE EXTRACT (EPOCH FROM NOW() - pg_last_xact_replay_timestamp())
                    END
                AS replication_lag
            """)
            result_list = [dict(x.cells) for x in result] if result is not None else []
            return float(result_list[0]["replication_lag"]) if result_list else None
        except Exception as e:
            logger.warning(f"Failed to get replication lag: {e}")
            return None

    async def _gaussdb_get_replication_slots(self) -> List[ReplicationSlot]:
        """Get information about replication slots using GaussDB-compatible queries."""
        try:
            # Check if replication slots are supported
            server_version = await self._get_server_version()
            if server_version < 90400:
                return []

            result = await self.gaussdb_driver.execute_query("""
                SELECT
                    slot_name,
                    database,
                    active
                FROM pg_replication_slots
            """)
            if result is None:
                return []
            result_list = [dict(x.cells) for x in result]
            return [
                ReplicationSlot(
                    slot_name=row["slot_name"],
                    database=row["database"],
                    active=row["active"],
                )
                for row in result_list
            ]
        except Exception as e:
            logger.warning(f"Failed to get replication slots: {e}")
            return []

    async def _gaussdb_is_replicating(self) -> bool:
        """Check if replication is active using GaussDB-compatible query."""
        try:
            result = await self.gaussdb_driver.execute_query("SELECT state FROM pg_stat_replication")
            result_list = [dict(x.cells) for x in result] if result is not None else []
            return bool(result_list and len(result_list) > 0)
        except Exception as e:
            logger.warning(f"Failed to check replication status: {e}")
            return False


class GaussDbConstraintHealthCalc(ConstraintHealthCalc):
    """
    GaussDB adapter for constraint health calculations.
    
    This class extends the base ConstraintHealthCalc to handle GaussDB-specific
    differences in constraint statistics and validation.
    """

    def __init__(self, sql_driver: Union[SqlDriver, GaussDbSqlDriver]):
        """
        Initialize GaussDB constraint health calculator.
        
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

        logger.debug("GaussDbConstraintHealthCalc initialized")

    async def invalid_constraints_check(self) -> str:
        """
        Check for any invalid constraints in the database with GaussDB compatibility.
        
        Returns:
            String describing any invalid constraints found
        """
        try:
            # Try GaussDB-specific approach first
            return await self._gaussdb_invalid_constraints_check()
        except Exception as e:
            logger.warning(f"GaussDB-specific invalid constraints check failed: {e}")
            # Fallback to PostgreSQL compatible approach
            return await super().invalid_constraints_check()

    async def _gaussdb_invalid_constraints_check(self) -> str:
        """GaussDB-specific invalid constraints check."""
        metrics = await self._gaussdb_get_invalid_constraints()

        if not metrics:
            return "No invalid constraints found."

        result = ["Invalid constraints found:"]
        for metric in metrics:
            if metric.referenced_table:
                result.append(
                    f"Constraint '{metric.name}' on table '{metric.schema}.{metric.table}' "
                    f"referencing '{metric.referenced_schema}.{metric.referenced_table}' is invalid"
                )
            else:
                result.append(f"Constraint '{metric.name}' on table '{metric.schema}.{metric.table}' is invalid")
        return "\n".join(result)

    async def _gaussdb_get_invalid_constraints(self) -> List[ConstraintMetrics]:
        """Get all invalid constraints in the database using GaussDB-compatible query."""
        results = await self.gaussdb_driver.execute_query("""
            SELECT
                nsp.nspname AS schema,
                rel.relname AS table,
                con.conname AS name,
                fnsp.nspname AS referenced_schema,
                frel.relname AS referenced_table
            FROM
                pg_catalog.pg_constraint con
            INNER JOIN
                pg_catalog.pg_class rel ON rel.oid = con.conrelid
            LEFT JOIN
                pg_catalog.pg_class frel ON frel.oid = con.confrelid
            LEFT JOIN
                pg_catalog.pg_namespace nsp ON nsp.oid = con.connamespace
            LEFT JOIN
                pg_catalog.pg_namespace fnsp ON fnsp.oid = frel.relnamespace
            WHERE
                con.convalidated = 'f'
        """)

        if not results:
            return []

        result_list = [dict(x.cells) for x in results]

        return [
            ConstraintMetrics(
                schema=row["schema"],
                table=row["table"],
                name=row["name"],
                referenced_schema=row["referenced_schema"],
                referenced_table=row["referenced_table"],
            )
            for row in result_list
        ]

    async def get_constraint_statistics(self) -> Dict[str, Any]:
        """
        Get comprehensive constraint statistics with GaussDB-specific information.
        
        Returns:
            Dictionary with constraint statistics
        """
        try:
            # Get constraint statistics using GaussDB-compatible queries
            total_result = await self.gaussdb_driver.execute_query("""
                SELECT COUNT(*) as count
                FROM information_schema.table_constraints
            """)

            active_result = await self.gaussdb_driver.execute_query("""
                SELECT COUNT(*) as count
                FROM information_schema.table_constraints
                WHERE is_deferrable = 'NO'
            """)

            invalid_result = await self.gaussdb_driver.execute_query("""
                SELECT COUNT(*) as count
                FROM pg_catalog.pg_constraint
                WHERE convalidated = 'f'
            """)

            total_count = dict(total_result[0].cells)["count"] if total_result else 0
            active_count = dict(active_result[0].cells)["count"] if active_result else 0
            invalid_count = dict(invalid_result[0].cells)["count"] if invalid_result else 0

            return {
                "total_constraints": total_count,
                "active_constraints": active_count,
                "invalid_constraints": invalid_count,
                "valid_constraints": total_count - invalid_count,
                "health_status": "healthy" if invalid_count == 0 else "needs_attention"
            }

        except Exception as e:
            logger.warning(f"GaussDB-specific constraint statistics failed: {e}")
            return {"error": f"Failed to get constraint statistics: {e}"}
