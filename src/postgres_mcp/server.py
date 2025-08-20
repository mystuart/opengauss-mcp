# ruff: noqa: B008
import argparse
import asyncio
import logging
import os
import signal
import sys
from enum import Enum
from typing import Any
from typing import List
from typing import Literal
from typing import Union

import mcp.types as types
from mcp.server.fastmcp import FastMCP
from pydantic import Field
from pydantic import validate_call

from postgres_mcp.index.dta_calc import DatabaseTuningAdvisor

from .artifacts import ErrorResult
from .artifacts import ExplainPlanArtifact
from .database_health import DatabaseHealthTool
from .database_health import HealthType
from .explain import ExplainPlanTool
from .gaussdb.explain_adapter import GaussDbExplainPlanTool
from .gaussdb.feature_checker import check_hypopg_installation_status as gaussdb_check_hypopg_installation_status
from .gaussdb.index_tuning_adapters import GaussDbDatabaseTuningAdvisor
from .gaussdb.index_tuning_adapters import GaussDbLLMOptimizerTool
from .gaussdb.sql_driver_adapter import GaussDbSqlDriver
from .index.index_opt_base import MAX_NUM_INDEX_TUNING_QUERIES
from .index.llm_opt import LLMOptimizerTool
from .index.presentation import TextPresentation
from .sql import DbConnPool
from .sql import SafeSqlDriver
from .sql import SqlDriver
from .sql import check_hypopg_installation_status
from .sql import obfuscate_password
from .sql.database_detection import DatabaseType
from .top_queries import TopQueriesCalc

# Initialize FastMCP with default settings
mcp = FastMCP("postgres-mcp")

# Constants
PG_STAT_STATEMENTS = "pg_stat_statements"
HYPOPG_EXTENSION = "hypopg"

ResponseType = List[types.TextContent | types.ImageContent | types.EmbeddedResource]

logger = logging.getLogger(__name__)


async def create_index_tuning_tool(sql_driver: SqlDriver, method: Literal["dta", "llm"]):
    """
    Create appropriate index tuning tool based on database type and method.
    
    Args:
        sql_driver: SQL driver instance
        method: Tuning method ("dta" or "llm")
        
    Returns:
        Index tuning tool instance (DatabaseTuningAdvisor or LLMOptimizerTool variant)
    """
    # Check if we're connected to GaussDB
    db_type = await sql_driver.get_database_type()

    if db_type == DatabaseType.GAUSSDB:
        logger.info(f"Using GaussDB-specific {method.upper()} index tuning tool")
        if method == "dta":
            return GaussDbDatabaseTuningAdvisor(sql_driver)
        else:
            return GaussDbLLMOptimizerTool(sql_driver)
    else:
        logger.info(f"Using PostgreSQL {method.upper()} index tuning tool")
        if method == "dta":
            return DatabaseTuningAdvisor(sql_driver)
        else:
            return LLMOptimizerTool(sql_driver)


class AccessMode(str, Enum):
    """SQL access modes for the server."""

    UNRESTRICTED = "unrestricted"  # Unrestricted access
    RESTRICTED = "restricted"  # Read-only with safety features


# Global variables
db_connection = DbConnPool()
current_access_mode = AccessMode.UNRESTRICTED
shutdown_in_progress = False

# Global database info cache to avoid repeated detection
_global_db_info_cache = {
    'initialized': False,
    'db_type': None,
    'db_version': None
}


async def get_sql_driver() -> Union[SqlDriver, SafeSqlDriver, GaussDbSqlDriver]:
    """Get the appropriate SQL driver based on the current access mode and database type."""
    # Check if database connection is valid
    if not db_connection.is_valid:
        error_msg = db_connection.last_error or "Database connection not established"
        raise ValueError(f"Database connection error: {error_msg}")

    base_driver = SqlDriver(conn=db_connection)

    # Initialize global database info cache if not already done
    if not _global_db_info_cache['initialized']:
        await _initialize_global_db_info(base_driver)

    # Set cached info to avoid repeated detection
    if _global_db_info_cache['initialized']:
        base_driver.db_type = _global_db_info_cache['db_type']
        base_driver.db_version = _global_db_info_cache['db_version']
        base_driver._db_info_initialized = True

    # Check if this is a GaussDB database
    is_gaussdb = (_global_db_info_cache.get('db_type') == DatabaseType.GAUSSDB)

    if current_access_mode == AccessMode.RESTRICTED:
        logger.debug("Using SafeSqlDriver with restrictions (RESTRICTED mode)")
        safe_driver = SafeSqlDriver(sql_driver=base_driver, timeout=30)  # 30 second timeout

        # Wrap with GaussDB adapter if needed
        if is_gaussdb:
            logger.debug("Wrapping SafeSqlDriver with GaussDB adapter")
            return GaussDbSqlDriver(safe_driver)
        else:
            return safe_driver
    else:
        logger.debug("Using unrestricted SqlDriver (UNRESTRICTED mode)")

        # Wrap with GaussDB adapter if needed
        if is_gaussdb:
            logger.debug("Wrapping SqlDriver with GaussDB adapter")
            return GaussDbSqlDriver(base_driver)
        else:
            return base_driver


async def _initialize_global_db_info(sql_driver: SqlDriver):
    """Initialize global database info cache."""
    try:
        from .sql.database_detection import detect_database_type
        from .sql.database_detection import get_database_version

        db_type = await detect_database_type(sql_driver)
        _, db_version = await get_database_version(sql_driver)

        _global_db_info_cache.update({
            'initialized': True,
            'db_type': db_type,
            'db_version': db_version
        })

        logger.info(f"Database detected: {db_type.value} version {db_version}")

    except Exception as e:
        logger.error(f"Failed to initialize global database info: {e}")
        # Set defaults
        from .sql.database_detection import DatabaseType
        _global_db_info_cache.update({
            'initialized': True,
            'db_type': DatabaseType.POSTGRESQL,
            'db_version': 'unknown'
        })


def format_text_response(text: Any) -> ResponseType:
    """Format a text response."""
    return [types.TextContent(type="text", text=str(text))]


def format_error_response(error: str) -> ResponseType:
    """Format an error response."""
    return format_text_response(f"Error: {error}")


@mcp.tool(description="List all schemas in the database")
async def list_schemas() -> ResponseType:
    """List all schemas in the database."""
    try:
        sql_driver = await get_sql_driver()
        rows = await sql_driver.execute_query(
            """
            SELECT
                schema_name,
                schema_owner,
                CASE
                    WHEN schema_name LIKE 'pg_%' THEN 'System Schema'
                    WHEN schema_name = 'information_schema' THEN 'System Information Schema'
                    ELSE 'User Schema'
                END as schema_type
            FROM information_schema.schemata
            ORDER BY schema_type, schema_name
            """
        )
        schemas = [row.cells for row in rows] if rows else []
        return format_text_response(schemas)
    except Exception as e:
        logger.error(f"Error listing schemas: {e}")
        return format_error_response(str(e))


@mcp.tool(description="List objects in a schema")
async def list_objects(
    schema_name: str = Field(description="Schema name"),
    object_type: str = Field(description="Object type: 'table', 'view', 'sequence', or 'extension'", default="table"),
) -> ResponseType:
    """List objects of a given type in a schema."""
    try:
        sql_driver = await get_sql_driver()

        if object_type in ("table", "view"):
            table_type = "BASE TABLE" if object_type == "table" else "VIEW"
            rows = await SafeSqlDriver.execute_param_query(
                sql_driver,
                """
                SELECT table_schema, table_name, table_type
                FROM information_schema.tables
                WHERE table_schema = {} AND table_type = {}
                ORDER BY table_name
                """,
                [schema_name, table_type],
            )
            objects = (
                [{"schema": row.cells["table_schema"], "name": row.cells["table_name"], "type": row.cells["table_type"]} for row in rows]
                if rows
                else []
            )

        elif object_type == "sequence":
            rows = await SafeSqlDriver.execute_param_query(
                sql_driver,
                """
                SELECT sequence_schema, sequence_name, data_type
                FROM information_schema.sequences
                WHERE sequence_schema = {}
                ORDER BY sequence_name
                """,
                [schema_name],
            )
            objects = (
                [{"schema": row.cells["sequence_schema"], "name": row.cells["sequence_name"], "data_type": row.cells["data_type"]} for row in rows]
                if rows
                else []
            )

        elif object_type == "extension":
            # Extensions are not schema-specific
            rows = await sql_driver.execute_query(
                """
                SELECT extname, extversion, extrelocatable
                FROM pg_extension
                ORDER BY extname
                """
            )
            objects = (
                [{"name": row.cells["extname"], "version": row.cells["extversion"], "relocatable": row.cells["extrelocatable"]} for row in rows]
                if rows
                else []
            )

        else:
            return format_error_response(f"Unsupported object type: {object_type}")

        return format_text_response(objects)
    except Exception as e:
        logger.error(f"Error listing objects: {e}")
        return format_error_response(str(e))


@mcp.tool(description="Show detailed information about a database object")
async def get_object_details(
    schema_name: str = Field(description="Schema name"),
    object_name: str = Field(description="Object name"),
    object_type: str = Field(description="Object type: 'table', 'view', 'sequence', or 'extension'", default="table"),
) -> ResponseType:
    """Get detailed information about a database object."""
    try:
        sql_driver = await get_sql_driver()

        if object_type in ("table", "view"):
            # Get columns
            col_rows = await SafeSqlDriver.execute_param_query(
                sql_driver,
                """
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_schema = {} AND table_name = {}
                ORDER BY ordinal_position
                """,
                [schema_name, object_name],
            )
            columns = (
                [
                    {
                        "column": r.cells["column_name"],
                        "data_type": r.cells["data_type"],
                        "is_nullable": r.cells["is_nullable"],
                        "default": r.cells["column_default"],
                    }
                    for r in col_rows
                ]
                if col_rows
                else []
            )

            # Get constraints
            con_rows = await SafeSqlDriver.execute_param_query(
                sql_driver,
                """
                SELECT tc.constraint_name, tc.constraint_type, kcu.column_name
                FROM information_schema.table_constraints AS tc
                LEFT JOIN information_schema.key_column_usage AS kcu
                  ON tc.constraint_name = kcu.constraint_name
                 AND tc.table_schema = kcu.table_schema
                WHERE tc.table_schema = {} AND tc.table_name = {}
                """,
                [schema_name, object_name],
            )

            constraints = {}
            if con_rows:
                for row in con_rows:
                    cname = row.cells["constraint_name"]
                    ctype = row.cells["constraint_type"]
                    col = row.cells["column_name"]

                    if cname not in constraints:
                        constraints[cname] = {"type": ctype, "columns": []}
                    if col:
                        constraints[cname]["columns"].append(col)

            constraints_list = [{"name": name, **data} for name, data in constraints.items()]

            # Get indexes
            idx_rows = await SafeSqlDriver.execute_param_query(
                sql_driver,
                """
                SELECT indexname, indexdef
                FROM pg_indexes
                WHERE schemaname = {} AND tablename = {}
                """,
                [schema_name, object_name],
            )

            indexes = [{"name": r.cells["indexname"], "definition": r.cells["indexdef"]} for r in idx_rows] if idx_rows else []

            result = {
                "basic": {"schema": schema_name, "name": object_name, "type": object_type},
                "columns": columns,
                "constraints": constraints_list,
                "indexes": indexes,
            }

        elif object_type == "sequence":
            rows = await SafeSqlDriver.execute_param_query(
                sql_driver,
                """
                SELECT sequence_schema, sequence_name, data_type, start_value, increment
                FROM information_schema.sequences
                WHERE sequence_schema = {} AND sequence_name = {}
                """,
                [schema_name, object_name],
            )

            if rows and rows[0]:
                row = rows[0]
                result = {
                    "schema": row.cells["sequence_schema"],
                    "name": row.cells["sequence_name"],
                    "data_type": row.cells["data_type"],
                    "start_value": row.cells["start_value"],
                    "increment": row.cells["increment"],
                }
            else:
                result = {}

        elif object_type == "extension":
            rows = await SafeSqlDriver.execute_param_query(
                sql_driver,
                """
                SELECT extname, extversion, extrelocatable
                FROM pg_extension
                WHERE extname = {}
                """,
                [object_name],
            )

            if rows and rows[0]:
                row = rows[0]
                result = {"name": row.cells["extname"], "version": row.cells["extversion"], "relocatable": row.cells["extrelocatable"]}
            else:
                result = {}

        else:
            return format_error_response(f"Unsupported object type: {object_type}")

        return format_text_response(result)
    except Exception as e:
        logger.error(f"Error getting object details: {e}")
        return format_error_response(str(e))


@mcp.tool(description="Explains the execution plan for a SQL query, showing how the database will execute it and provides detailed cost estimates.")
async def explain_query(
    sql: str = Field(description="SQL query to explain"),
    analyze: bool = Field(
        description="When True, actually runs the query to show real execution statistics instead of estimates. "
        "Takes longer but provides more accurate information.",
        default=False,
    ),
    hypothetical_indexes: list[dict[str, Any]] = Field(
        description="""A list of hypothetical indexes to simulate. Each index must be a dictionary with these keys:
    - 'table': The table name to add the index to (e.g., 'users')
    - 'columns': List of column names to include in the index (e.g., ['email'] or ['last_name', 'first_name'])
    - 'using': Optional index method (default: 'btree', other options include 'hash', 'gist', etc.)

Examples: [
    {"table": "users", "columns": ["email"], "using": "btree"},
    {"table": "orders", "columns": ["user_id", "created_at"]}
]
If there is no hypothetical index, you can pass an empty list.""",
        default=[],
    ),
) -> ResponseType:
    """
    Explains the execution plan for a SQL query.

    Args:
        sql: The SQL query to explain
        analyze: When True, actually runs the query for real statistics
        hypothetical_indexes: Optional list of indexes to simulate
    """
    try:
        sql_driver = await get_sql_driver()

        # Use appropriate explain tool based on database type
        if isinstance(sql_driver, GaussDbSqlDriver):
            explain_tool = GaussDbExplainPlanTool(sql_driver=sql_driver)
        else:
            # For regular SqlDriver or SafeSqlDriver, use the standard tool
            base_driver = sql_driver.sql_driver if isinstance(sql_driver, SafeSqlDriver) else sql_driver
            explain_tool = ExplainPlanTool(sql_driver=base_driver)

        result: ExplainPlanArtifact | ErrorResult | None = None

        # If hypothetical indexes are specified, check for HypoPG extension
        if hypothetical_indexes and len(hypothetical_indexes) > 0:
            if analyze:
                return format_error_response("Cannot use analyze and hypothetical indexes together")
            try:
                # Use appropriate hypopg check based on database type
                if isinstance(sql_driver, GaussDbSqlDriver):
                    hypopg_status = await gaussdb_check_hypopg_installation_status(sql_driver)
                    is_hypopg_installed = hypopg_status.get("installed", False)
                    hypopg_message = hypopg_status.get("status", "hypopg not available")

                    # Add GaussDB-specific guidance if available
                    if not is_hypopg_installed and "gaussdb_guidance" in hypopg_status:
                        hypopg_message += f"\n\n{hypopg_status['gaussdb_guidance']}"
                else:
                    # Use the common utility function for PostgreSQL
                    (
                        is_hypopg_installed,
                        hypopg_message,
                    ) = await check_hypopg_installation_status(sql_driver)

                # If hypopg is not installed, return the message
                if not is_hypopg_installed:
                    return format_text_response(hypopg_message)

                # HypoPG is installed, proceed with explaining with hypothetical indexes
                result = await explain_tool.explain_with_hypothetical_indexes(sql, hypothetical_indexes)
            except Exception:
                raise  # Re-raise the original exception
        elif analyze:
            try:
                # Use EXPLAIN ANALYZE
                result = await explain_tool.explain_analyze(sql)
            except Exception:
                raise  # Re-raise the original exception
        else:
            try:
                # Use basic EXPLAIN
                result = await explain_tool.explain(sql)
            except Exception:
                raise  # Re-raise the original exception

        if result and isinstance(result, ExplainPlanArtifact):
            return format_text_response(result.to_text())
        else:
            error_message = "Error processing explain plan"
            if isinstance(result, ErrorResult):
                error_message = result.to_text()
            return format_error_response(error_message)
    except Exception as e:
        logger.error(f"Error explaining query: {e}")
        return format_error_response(str(e))


# Query function declaration without the decorator - we'll add it dynamically based on access mode
async def execute_sql(
    sql: str = Field(description="SQL to run"),
) -> ResponseType:
    """Executes a SQL query against the database."""
    try:
        sql_driver = await get_sql_driver()
        rows = await sql_driver.execute_query(sql)  # type: ignore
        if rows is None:
            return format_text_response("No results")
        return format_text_response(list([r.cells for r in rows]))
    except Exception as e:
        logger.error(f"Error executing query: {e}")
        return format_error_response(str(e))


@mcp.tool(description="Analyze frequently executed queries in the database and recommend optimal indexes")
@validate_call
async def analyze_workload_indexes(
    max_index_size_mb: int = Field(description="Max index size in MB", default=10000),
    method: Literal["dta", "llm"] = Field(description="Method to use for analysis", default="dta"),
) -> ResponseType:
    """Analyze frequently executed queries in the database and recommend optimal indexes."""
    try:
        sql_driver = await get_sql_driver()
        index_tuning = await create_index_tuning_tool(sql_driver, method)
        dta_tool = TextPresentation(sql_driver, index_tuning)
        result = await dta_tool.analyze_workload(max_index_size_mb=max_index_size_mb)
        return format_text_response(result)
    except Exception as e:
        logger.error(f"Error analyzing workload: {e}")
        return format_error_response(str(e))


@mcp.tool(description="Analyze a list of (up to 10) SQL queries and recommend optimal indexes")
@validate_call
async def analyze_query_indexes(
    queries: list[str] = Field(description="List of Query strings to analyze"),
    max_index_size_mb: int = Field(description="Max index size in MB", default=10000),
    method: Literal["dta", "llm"] = Field(description="Method to use for analysis", default="dta"),
) -> ResponseType:
    """Analyze a list of SQL queries and recommend optimal indexes."""
    if len(queries) == 0:
        return format_error_response("Please provide a non-empty list of queries to analyze.")
    if len(queries) > MAX_NUM_INDEX_TUNING_QUERIES:
        return format_error_response(f"Please provide a list of up to {MAX_NUM_INDEX_TUNING_QUERIES} queries to analyze.")

    try:
        sql_driver = await get_sql_driver()
        index_tuning = await create_index_tuning_tool(sql_driver, method)
        dta_tool = TextPresentation(sql_driver, index_tuning)
        result = await dta_tool.analyze_queries(queries=queries, max_index_size_mb=max_index_size_mb)
        return format_text_response(result)
    except Exception as e:
        logger.error(f"Error analyzing queries: {e}")
        return format_error_response(str(e))


@mcp.tool(
    description="Analyzes database health. Here are the available health checks:\n"
    "- index - checks for invalid, duplicate, and bloated indexes\n"
    "- connection - checks the number of connection and their utilization\n"
    "- vacuum - checks vacuum health for transaction id wraparound\n"
    "- sequence - checks sequences at risk of exceeding their maximum value\n"
    "- replication - checks replication health including lag and slots\n"
    "- buffer - checks for buffer cache hit rates for indexes and tables\n"
    "- constraint - checks for invalid constraints\n"
    "- all - runs all checks\n"
    "You can optionally specify a single health check or a comma-separated list of health checks. The default is 'all' checks.\n"
    "Automatically adapts to GaussDB when connected to a GaussDB database."
)
async def analyze_db_health(
    health_type: str = Field(
        description=f"Optional. Valid values are: {', '.join(sorted([t.value for t in HealthType]))}.",
        default="all",
    ),
) -> ResponseType:
    """Analyze database health for specified components.

    Args:
        health_type: Comma-separated list of health check types to perform.
                    Valid values: index, connection, vacuum, sequence, replication, buffer, constraint, all
    """
    sql_driver = await get_sql_driver()

    # Use standard health tool - it will automatically use GaussDB adapters when needed
    health_tool = DatabaseHealthTool(sql_driver)

    result = await health_tool.health(health_type=health_type)
    return format_text_response(result)


@mcp.tool(
    name="get_top_queries",
    description=f"Reports the slowest or most resource-intensive queries using data from the '{PG_STAT_STATEMENTS}' extension or GaussDB equivalent.",
)
async def get_top_queries(
    sort_by: str = Field(
        description="Ranking criteria: 'total_time' for total execution time or 'mean_time' for mean execution time per call, or 'resources' "
        "for resource-intensive queries",
        default="resources",
    ),
    limit: int = Field(description="Number of queries to return when ranking based on mean_time or total_time", default=10),
) -> ResponseType:
    try:
        sql_driver = await get_sql_driver()

        # Use GaussDB-aware top queries tool if connected to GaussDB
        if isinstance(sql_driver, GaussDbSqlDriver):
            # Create GaussDB-adapted top queries tool
            from .gaussdb.top_queries_adapter import GaussDbTopQueriesCalc
            top_queries_tool = GaussDbTopQueriesCalc(sql_driver=sql_driver)
        else:
            # Use standard PostgreSQL top queries tool
            top_queries_tool = TopQueriesCalc(sql_driver=sql_driver)

        if sort_by == "resources":
            result = await top_queries_tool.get_top_resource_queries()
            return format_text_response(result)
        elif sort_by == "mean_time" or sort_by == "total_time":
            # Map the sort_by values to what get_top_queries_by_time expects
            result = await top_queries_tool.get_top_queries_by_time(limit=limit, sort_by="mean" if sort_by == "mean_time" else "total")
        else:
            return format_error_response("Invalid sort criteria. Please use 'resources' or 'mean_time' or 'total_time'.")
        return format_text_response(result)
    except Exception as e:
        logger.error(f"Error getting slow queries: {e}")
        return format_error_response(str(e))


@mcp.tool(description="Run benchmark tests on GaussDB database to evaluate performance")
@validate_call
async def gaussdb_benchmark(
    benchmark_type: str = Field(
        description="Type of benchmark to run: 'sysbench' or 'tpcc'",
        default="sysbench",
    ),
    duration: int = Field(description="Duration of benchmark in seconds (minimum 10, maximum 3600)", default=60),
    threads: int = Field(description="Number of threads to use (minimum 1, maximum 64)", default=4),
    table_size: int = Field(description="Number of rows per table for sysbench (minimum 1000, maximum 10000000)", default=10000),
    warehouses: int = Field(description="Number of warehouses for TPC-C (minimum 1, maximum 100)", default=4),
) -> ResponseType:
    """
    Run benchmark tests on GaussDB database.
    
    Args:
        benchmark_type: Type of benchmark ('sysbench' or 'tpcc')
        duration: Duration in seconds (10-3600)
        threads: Number of threads (1-64)
        table_size: Number of rows per table for sysbench (1000-10000000)
        warehouses: Number of warehouses for TPC-C (1-100)
    """
    try:
        # Parameter validation
        if benchmark_type.lower() not in ["sysbench", "tpcc"]:
            return format_error_response(f"Invalid benchmark type: {benchmark_type}. Use 'sysbench' or 'tpcc'")

        if not (10 <= duration <= 3600):
            return format_error_response(f"Duration must be between 10 and 3600 seconds, got {duration}")

        if not (1 <= threads <= 64):
            return format_error_response(f"Threads must be between 1 and 64, got {threads}")

        if benchmark_type.lower() == "sysbench" and not (1000 <= table_size <= 10000000):
            return format_error_response(f"Table size must be between 1000 and 10000000, got {table_size}")

        if benchmark_type.lower() == "tpcc" and not (1 <= warehouses <= 100):
            return format_error_response(f"Warehouses must be between 1 and 100, got {warehouses}")

        sql_driver = await get_sql_driver()

        # Check if connected to GaussDB
        if not isinstance(sql_driver, GaussDbSqlDriver):
            return format_error_response("This tool is only available when connected to a GaussDB database")

        # Validate GaussDB connection
        is_valid, validation_error = await sql_driver.validate_connection()
        if not is_valid:
            return format_error_response(f"GaussDB connection validation failed: {validation_error}")

        # Import benchmark tool
        from .benchmark.benchmark_tool import BenchmarkTool
        benchmark_tool = BenchmarkTool(sql_driver)

        if benchmark_type.lower() == "sysbench":
            from .benchmark.config import SysbenchConfig
            config = SysbenchConfig(
                time=duration,  # Note: SysbenchConfig uses 'time' not 'duration'
                threads=threads,
                table_size=table_size
            )
            logger.info(f"Running Sysbench benchmark: {threads} threads, {duration}s duration, {table_size} table size")
            result = await benchmark_tool.run_sysbench(config)
        else:  # tpcc
            from .benchmark.config import TpccConfig
            config = TpccConfig(
                duration=duration,
                connections=threads,  # Note: TpccConfig uses 'connections' not 'threads'
                warehouses=warehouses
            )
            logger.info(f"Running TPC-C benchmark: {threads} connections, {duration}s duration, {warehouses} warehouses")
            result = await benchmark_tool.run_tpcc(config)

        return format_text_response(result.to_text())

    except Exception as e:
        logger.error(f"Error running GaussDB benchmark: {e}")
        return format_error_response(f"Benchmark execution failed: {e!s}")


@mcp.tool(description="Check GaussDB compatibility and feature support")
@validate_call
async def gaussdb_compatibility_check(
    include_detailed_features: bool = Field(
        description="Include detailed feature availability checks",
        default=True,
    ),
    include_error_stats: bool = Field(
        description="Include error handling statistics",
        default=True,
    ),
) -> ResponseType:
    """
    Check GaussDB compatibility and feature support.
    
    Args:
        include_detailed_features: Include detailed feature availability checks
        include_error_stats: Include error handling statistics
    
    Returns information about GaussDB version, supported features,
    and compatibility status with the MCP server.
    """
    try:
        sql_driver = await get_sql_driver()

        # Check if connected to GaussDB
        if not isinstance(sql_driver, GaussDbSqlDriver):
            return format_error_response("This tool is only available when connected to a GaussDB database")

        # Get comprehensive compatibility information
        compatibility_info = await sql_driver.get_feature_support_info()

        # Get connection validation status
        is_valid, validation_error = await sql_driver.validate_connection()
        compatibility_info["connection_valid"] = is_valid
        if validation_error:
            compatibility_info["connection_error"] = validation_error

        # Get error handling statistics if requested
        if include_error_stats:
            error_stats = sql_driver.get_error_statistics()
            compatibility_info["error_handling"] = error_stats

        # Check specific feature availability if requested
        if include_detailed_features:
            from .gaussdb.feature_checker import FeatureAvailabilityChecker
            feature_checker = FeatureAvailabilityChecker(sql_driver)

            # Check key features
            hypopg_support, hypopg_status, hypopg_guidance = await feature_checker.check_hypopg_support()
            stat_statements_support, stat_status, stat_guidance = await feature_checker.check_pg_stat_statements_support()

            compatibility_info["feature_checks"] = {
                "hypopg": {
                    "supported": hypopg_support,
                    "status": hypopg_status,
                    "guidance": hypopg_guidance
                },
                "pg_stat_statements": {
                    "supported": stat_statements_support,
                    "status": stat_status,
                    "guidance": stat_guidance
                }
            }

        # Format the response
        result_lines = [
            "GaussDB Compatibility Check Results:",
            "=" * 40,
            f"Database Type: {compatibility_info.get('database_type', 'Unknown')}",
            f"Version: {compatibility_info.get('version', 'Unknown')}",
            f"Connection Valid: {compatibility_info.get('connection_valid', False)}",
        ]

        if compatibility_info.get('connection_error'):
            result_lines.append(f"Connection Error: {compatibility_info['connection_error']}")

        result_lines.extend([
            "",
            "Feature Support:",
            "-" * 20,
        ])

        features = compatibility_info.get('features', {})
        for feature, supported in features.items():
            status = "✓" if supported else "✗"
            result_lines.append(f"{status} {feature}: {supported}")

        result_lines.extend([
            "",
            "System Views and Adaptations:",
            "-" * 30,
            f"System Views Count: {compatibility_info.get('system_views_count', 0)}",
            f"Query Adaptations Count: {compatibility_info.get('query_adaptations_count', 0)}",
            f"Error Mappings Count: {compatibility_info.get('error_mappings_count', 0)}",
        ])

        # Add feature check details if requested
        if include_detailed_features:
            feature_checks = compatibility_info.get('feature_checks', {})
            if feature_checks:
                result_lines.extend([
                    "",
                    "Detailed Feature Checks:",
                    "-" * 25,
                ])

                for feature_name, feature_info in feature_checks.items():
                    status = "✓" if feature_info.get('supported') else "✗"
                    result_lines.append(f"{status} {feature_name}: {feature_info.get('status', 'Unknown')}")
                    if feature_info.get('guidance'):
                        result_lines.append(f"  Guidance: {feature_info['guidance']}")

        # Add error handling statistics if requested
        if include_error_stats:
            error_handling = compatibility_info.get('error_handling', {})
            if error_handling:
                result_lines.extend([
                    "",
                    "Error Handling Status:",
                    "-" * 22,
                    f"Fallback Mode: {error_handling.get('fallback_mode', False)}",
                    f"Max Retries: {error_handling.get('max_retries', 0)}",
                ])

                cache_stats = error_handling.get('cache_stats', {})
                if cache_stats:
                    result_lines.append(f"Query Cache Size: {cache_stats.get('cache_size', 0)}/{cache_stats.get('max_size', 0)}")

        return format_text_response("\n".join(result_lines))

    except Exception as e:
        logger.error(f"Error checking GaussDB compatibility: {e}")
        return format_error_response(str(e))


async def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="PostgreSQL MCP Server")
    parser.add_argument("database_url", help="Database connection URL", nargs="?")
    parser.add_argument(
        "--access-mode",
        type=str,
        choices=[mode.value for mode in AccessMode],
        default=AccessMode.UNRESTRICTED.value,
        help="Set SQL access mode: unrestricted (unrestricted) or restricted (read-only with protections)",
    )
    parser.add_argument(
        "--transport",
        type=str,
        choices=["stdio", "sse"],
        default="stdio",
        help="Select MCP transport: stdio (default) or sse",
    )
    parser.add_argument(
        "--sse-host",
        type=str,
        default="localhost",
        help="Host to bind SSE server to (default: localhost)",
    )
    parser.add_argument(
        "--sse-port",
        type=int,
        default=8000,
        help="Port for SSE server (default: 8000)",
    )

    args = parser.parse_args()

    # Store the access mode in the global variable
    global current_access_mode
    current_access_mode = AccessMode(args.access_mode)

    # Add the query tool with a description appropriate to the access mode
    if current_access_mode == AccessMode.UNRESTRICTED:
        mcp.add_tool(execute_sql, description="Execute any SQL query")
    else:
        mcp.add_tool(execute_sql, description="Execute a read-only SQL query")

    logger.info(f"Starting PostgreSQL MCP Server in {current_access_mode.upper()} mode")

    # Get database URL from environment variable or command line
    database_url = os.environ.get("DATABASE_URI", args.database_url)

    if not database_url:
        raise ValueError(
            "Error: No database URL provided. Please specify via 'DATABASE_URI' environment variable or command-line argument.",
        )

    # Initialize database connection pool
    try:
        await db_connection.pool_connect(database_url)
        logger.info("Successfully connected to database and initialized connection pool")
    except Exception as e:
        logger.warning(
            f"Could not connect to database: {obfuscate_password(str(e))}",
        )
        logger.warning(
            "The MCP server will start but database operations will fail until a valid connection is established.",
        )

    # Set up proper shutdown handling
    try:
        loop = asyncio.get_running_loop()
        signals = (signal.SIGTERM, signal.SIGINT)
        for s in signals:
            loop.add_signal_handler(s, lambda s=s: asyncio.create_task(shutdown(s)))
    except NotImplementedError:
        # Windows doesn't support signals properly
        logger.warning("Signal handling not supported on Windows")
        pass

    # Run the server with the selected transport (always async)
    if args.transport == "stdio":
        await mcp.run_stdio_async()
    else:
        # Update FastMCP settings based on command line arguments
        mcp.settings.host = args.sse_host
        mcp.settings.port = args.sse_port
        await mcp.run_sse_async()


async def shutdown(sig=None):
    """Clean shutdown of the server."""
    global shutdown_in_progress

    if shutdown_in_progress:
        logger.warning("Forcing immediate exit")
        # Use sys.exit instead of os._exit to allow for proper cleanup
        sys.exit(1)

    shutdown_in_progress = True

    if sig:
        logger.info(f"Received exit signal {sig.name}")

    # Close database connections
    try:
        await db_connection.close()
        logger.info("Closed database connections")
    except Exception as e:
        logger.error(f"Error closing database connections: {e}")

    # Exit with appropriate status code
    sys.exit(128 + sig if sig is not None else 0)
