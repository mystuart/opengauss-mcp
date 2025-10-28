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
from typing import LiteralString
from typing import Union
from typing import cast

import mcp.types as types
from mcp.server.fastmcp import FastMCP
from pydantic import Field
from pydantic import validate_call

from opengauss_mcp.index.dta_calc import DatabaseTuningAdvisor

from .artifacts import ErrorResult
from .artifacts import ExplainPlanArtifact
from .database_health import ConnectionHealthCalc
from .database_health import DbePerfHealthMonitor
from .database_health import DatabaseHealthTool
from .database_health import HealthType
from .explain import ExplainPlanTool
from .index.index_opt_base import MAX_NUM_INDEX_TUNING_QUERIES
from .index.llm_opt import LLMOptimizerTool
from .index.presentation import TextPresentation
from .sql import DbConnPool
from .sql import SafeSqlDriver
from .sql import SqlDriver
from .sql import check_virtual_index_support
from .sql import obfuscate_password
from .top_queries import TopQueriesCalc
from .utils import (
    ErrorContext,
    ConnectionError as DBConnectionError,
    DatabaseError,
    FeatureNotSupportedError,
    QueryError,
    format_error_message,
    handle_database_errors,
    log_function_call,
    setup_logging,
)

# Initialize FastMCP with default settings
mcp = FastMCP("opengauss-mcp")

# Constants
DBE_PERF_STATEMENT = "dbe_perf.statement"
VIRTUAL_INDEX = "virtual_index"

ResponseType = List[types.TextContent | types.ImageContent | types.EmbeddedResource]

logger = logging.getLogger(__name__)


class AccessMode(str, Enum):
    """SQL access modes for the server."""

    UNRESTRICTED = "unrestricted"  # Unrestricted access
    RESTRICTED = "restricted"  # Read-only with safety features


# Global variables
db_connection = DbConnPool()
current_access_mode = AccessMode.UNRESTRICTED
shutdown_in_progress = False


async def get_sql_driver() -> Union[SqlDriver, SafeSqlDriver]:
    """Get the appropriate SQL driver based on the current access mode."""
    base_driver = SqlDriver(conn=db_connection)

    if current_access_mode == AccessMode.RESTRICTED:
        logger.debug("Using SafeSqlDriver with restrictions (RESTRICTED mode)")
        return SafeSqlDriver(sql_driver=base_driver, timeout=30)  # 30 second timeout
    else:
        logger.debug("Using unrestricted SqlDriver (UNRESTRICTED mode)")
        return base_driver


def format_text_response(text: Any) -> ResponseType:
    """Format a text response."""
    return [types.TextContent(type="text", text=str(text))]


def format_error_response(error: str) -> ResponseType:
    """Format an error response."""
    return format_text_response(f"Error: {error}")


@mcp.tool(description="List all schemas in the database")
@handle_database_errors
@log_function_call
async def list_schemas() -> ResponseType:
    """List all schemas in the database."""
    with ErrorContext("list_schemas"):
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
        explain_tool = ExplainPlanTool(sql_driver=sql_driver)
        result: ExplainPlanArtifact | ErrorResult | None = None

        # If hypothetical indexes are specified, check for virtual index support
        if hypothetical_indexes and len(hypothetical_indexes) > 0:
            if analyze:
                return format_error_response("Cannot use analyze and hypothetical indexes together")
            try:
                # Use the common utility function to check if virtual indexes are supported
                (
                    is_virtual_index_supported,
                    virtual_index_message,
                ) = await check_virtual_index_support(sql_driver)

                # If virtual indexes are not supported, return the message
                if not is_virtual_index_supported:
                    return format_text_response(virtual_index_message)

                # Virtual indexes are supported, proceed with explaining with hypothetical indexes
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
    sql: str = Field(description="SQL to run", default="all"),
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
        if method == "dta":
            index_tuning = DatabaseTuningAdvisor(sql_driver)
        else:
            index_tuning = LLMOptimizerTool(sql_driver, api_key=os.getenv("ZAI_API_KEY"))
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
        if method == "dta":
            index_tuning = DatabaseTuningAdvisor(sql_driver)
        else:
            index_tuning = LLMOptimizerTool(sql_driver, api_key=os.getenv("ZAI_API_KEY"))
        dta_tool = TextPresentation(sql_driver, index_tuning)
        result = await dta_tool.analyze_queries(queries=queries, max_index_size_mb=max_index_size_mb)
        return format_text_response(result)
    except Exception as e:
        logger.error(f"Error analyzing queries: {e}")
        return format_error_response(str(e))


@mcp.tool(description="Generate intelligent index recommendations using only LLM analysis. This tool analyzes SQL queries and provides index recommendations without requiring database virtual indexes or complex optimization. It's fast, lightweight, and provides expert-level database optimization advice.")
@validate_call
async def analyze_indexes_with_llm_only(
    queries: list[str] = Field(description="List of SQL queries to analyze for index optimization"),
) -> ResponseType:
    """Generate index recommendations using only LLM analysis without virtual indexes.

    This tool provides intelligent database index recommendations by analyzing SQL queries
    using GLM-4.5-Flash AI model. It considers WHERE clauses, JOIN conditions, ORDER BY clauses,
    and other access patterns to suggest optimal indexes.

    Benefits:
    - Fast response time (no virtual index overhead)
    - Works with any PostgreSQL/openGauss database
    - Provides expert-level optimization advice
    - Handles complex multi-query analysis
    - Free to use with GLM-4.5-Flash model
    """
    if len(queries) == 0:
        return format_error_response("Please provide a non-empty list of queries to analyze.")
    if len(queries) > MAX_NUM_INDEX_TUNING_QUERIES:
        return format_error_response(f"Please provide a list of up to {MAX_NUM_INDEX_TUNING_QUERIES} queries to analyze.")

    try:
        sql_driver = await get_sql_driver()
        llm_optimizer = LLMOptimizerTool(sql_driver, api_key=os.getenv("ZAI_API_KEY"))

        # Use the new pure LLM method
        recommendations, analysis = await llm_optimizer.generate_pure_llm_recommendations(queries)

        # Format the results
        if not recommendations:
            result = "LLM Analysis Complete\n" + "="*50 + "\n"
            result += f"Analysis: {analysis}\n\n"
            result += "No specific index recommendations were generated.\n"
            result += "This may indicate that:\n"
            result += "- The queries are already optimized\n"
            result += "- Current indexes are sufficient\n"
            result += "- The queries don't have conditions that benefit from additional indexes\n"
        else:
            result = "LLM Index Recommendations\n" + "="*50 + "\n"
            result += f"Analysis: {analysis}\n\n"
            result += f"Generated {len(recommendations)} index recommendations:\n\n"

            for i, rec in enumerate(recommendations, 1):
                result += f"{i}. CREATE INDEX ON {rec.table} ({', '.join(rec.columns)});\n"

            result += "\n" + "="*50 + "\n"
            result += "Note: These recommendations are based on SQL analysis only.\n"
            result += "For actual performance improvement, consider creating these indexes\n"
            result += "and testing with real workloads.\n"

        return format_text_response(result)

    except Exception as e:
        logger.error(f"Error in LLM-only index analysis: {e}")
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
    "You can optionally specify a single health check or a comma-separated list of health checks. The default is 'all' checks."
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
    health_tool = DatabaseHealthTool(await get_sql_driver())
    result = await health_tool.health(health_type=health_type)
    return format_text_response(result)


@mcp.tool(
    name="get_top_queries",
    description=f"Reports the slowest or most resource-intensive queries using data from the '{DBE_PERF_STATEMENT}' view.",
)
async def get_top_queries(
    sort_by: str = Field(
        description="Ranking criteria: 'total_time' for total execution time, 'mean_time' for mean execution time per call, 'resources' "
        "for resource-intensive queries, or 'io' for I/O-intensive queries",
        default="resources",
    ),
    limit: int = Field(description="Number of queries to return when ranking based on mean_time or total_time", default=10),
    threshold: float = Field(description="Fraction threshold for filtering resource/io queries (default: 0.05)", default=0.05),
) -> ResponseType:
    try:
        sql_driver = await get_sql_driver()
        top_queries_tool = TopQueriesCalc(sql_driver=sql_driver)

        if sort_by == "resources":
            result = await top_queries_tool.get_top_resource_queries(frac_threshold=threshold)
            return format_text_response(result)
        elif sort_by == "io":
            result = await top_queries_tool.get_io_intensive_queries(io_threshold=threshold)
            return format_text_response(result)
        elif sort_by == "mean_time" or sort_by == "total_time":
            # Map the sort_by values to what get_top_queries_by_time expects
            result = await top_queries_tool.get_top_queries_by_time(limit=limit, sort_by="mean" if sort_by == "mean_time" else "total")
        else:
            return format_error_response("Invalid sort criteria. Please use 'resources', 'io', 'mean_time' or 'total_time'.")
        return format_text_response(result)
    except Exception as e:
        logger.error(f"Error getting slow queries: {e}")
        return format_error_response(str(e))


@mcp.tool(
    description="Gets queries with detailed resource consumption metrics from dbe_perf.statement.",
)
async def get_queries_with_resource_metrics(
    limit: int = Field(description="Maximum number of queries to return", default=20),
) -> ResponseType:
    """Get queries with detailed resource consumption metrics from dbe_perf.statement."""
    try:
        sql_driver = await get_sql_driver()
        top_queries_tool = TopQueriesCalc(sql_driver=sql_driver)
        result = await top_queries_tool.get_queries_with_resource_metrics(limit=limit)
        return format_text_response(result)
    except Exception as e:
        logger.error(f"Error getting queries with resource metrics: {e}")
        return format_error_response(str(e))


@mcp.tool(
    description="Gets queries ranked by resource efficiency (rows returned per resource unit).",
)
async def get_queries_by_resource_efficiency(
    limit: int = Field(description="Maximum number of queries to return", default=20),
) -> ResponseType:
    """Get queries ranked by resource efficiency (rows returned per resource unit)."""
    try:
        sql_driver = await get_sql_driver()
        top_queries_tool = TopQueriesCalc(sql_driver=sql_driver)
        result = await top_queries_tool.get_queries_by_resource_efficiency(limit=limit)
        return format_text_response(result)
    except Exception as e:
        logger.error(f"Error getting queries by resource efficiency: {e}")
        return format_error_response(str(e))


@mcp.tool(
    description="Gets detailed session information for active connections using dbe_perf.session view.",
)
async def get_detailed_session_info(
    include_idle: bool = Field(description="Whether to include idle connections in the results", default=True),
) -> ResponseType:
    """Get detailed session information for active connections."""
    try:
        sql_driver = await get_sql_driver()
        connection_health = ConnectionHealthCalc(sql_driver=sql_driver)
        result = await connection_health.get_detailed_session_info(include_idle=include_idle)
        return format_text_response(result)
    except Exception as e:
        logger.error(f"Error getting detailed session info: {e}")
        return format_error_response(str(e))


@mcp.tool(
    description="Gets queries that have been running for longer than the specified threshold.",
)
async def get_long_running_queries(
    threshold_minutes: int = Field(description="Threshold in minutes for considering a query as long-running", default=5),
) -> ResponseType:
    """Get queries that have been running for longer than the threshold."""
    try:
        sql_driver = await get_sql_driver()
        connection_health = ConnectionHealthCalc(sql_driver=sql_driver)
        result = await connection_health.get_long_running_queries(threshold_minutes=threshold_minutes)
        return format_text_response(result)
    except Exception as e:
        logger.error(f"Error getting long-running queries: {e}")
        return format_error_response(str(e))


@mcp.tool(
    description="Gets information about blocked and blocking queries using dbe_perf.session view.",
)
async def get_blocked_queries() -> ResponseType:
    """Get information about blocked and blocking queries."""
    try:
        sql_driver = await get_sql_driver()
        connection_health = ConnectionHealthCalc(sql_driver=sql_driver)
        result = await connection_health.get_blocked_queries()
        return format_text_response(result)
    except Exception as e:
        logger.error(f"Error getting blocked queries: {e}")
        return format_error_response(str(e))


@mcp.tool(
    description="Creates a virtual index using hypopg extension for testing query performance without creating a real index.",
)
async def create_virtual_index(
    table: str = Field(description="Table name to create the index on"),
    columns: list[str] = Field(description="List of column names for the index"),
    index_type: str = Field(description="Type of index (btree, hash, gin, gist, spgist, brin)", default="btree"),
    where_clause: str = Field(description="Optional WHERE clause for partial index", default=""),
) -> ResponseType:
    """Create a virtual index using hypopg extension."""
    try:
        sql_driver = await get_sql_driver()
        
        # Build the index definition for hypopg
        index_def = f"{table}({','.join(columns)})"
        
        # Add index type if not btree
        if index_type != "btree":
            index_def = f"{index_def} USING {index_type}"
            
        # Add WHERE clause for partial index
        if where_clause:
            index_def = f"{index_def} WHERE {where_clause}"
            
        # Create the virtual index using hypopg_create_index
        create_sql = f"SELECT * FROM hypopg_create_index('{index_def}')"
        logger.debug(f"Creating virtual index: {create_sql}")
        result = await sql_driver.execute_query(cast(LiteralString, create_sql))
        
        if not result or len(result) == 0:
            return format_error_response("Failed to create virtual index")
            
        # Get the index ID from the result
        index_id = result[0].cells.get("indexrelid")
        if not index_id:
            return format_error_response("Failed to get virtual index ID")
        
        return format_text_response(f"Created virtual index with ID: {index_id}")
    except Exception as e:
        logger.error(f"Error creating virtual index: {e}")
        return format_error_response(str(e))


@mcp.tool(
    description="Drops a virtual index using hypopg extension.",
)
async def drop_virtual_index(
    index_id: int = Field(description="ID of the virtual index to drop"),
) -> ResponseType:
    """Drop a virtual index using hypopg extension."""
    try:
        sql_driver = await get_sql_driver()
        
        # Drop the virtual index using hypopg_drop_index
        drop_sql = f"SELECT * FROM hypopg_drop_index({index_id})"
        logger.debug(f"Dropping virtual index: {drop_sql}")
        result = await sql_driver.execute_query(cast(LiteralString, drop_sql))
        
        if result and len(result) > 0:
            success = result[0].cells.get("hypopg_drop_index", False)
            if success:
                return format_text_response(f"Dropped virtual index with ID: {index_id}")
            else:
                return format_error_response(f"Failed to drop virtual index with ID: {index_id}")
        else:
            return format_error_response(f"Failed to drop virtual index with ID: {index_id}")
    except Exception as e:
        logger.error(f"Error dropping virtual index: {e}")
        return format_error_response(str(e))


@mcp.tool(
    description="Lists all virtual indexes currently created using hypopg extension.",
)
async def list_virtual_indexes() -> ResponseType:
    """List all virtual indexes currently created using hypopg extension."""
    try:
        sql_driver = await get_sql_driver()
        
        # Use hypopg_display_index to get all virtual indexes
        query = "SELECT * FROM hypopg_display_index()"
        result = await sql_driver.execute_query(cast(LiteralString, query))
        
        if not result:
            return format_text_response("No virtual indexes found.")
        
        indexes = []
        for row in result:
            # Get the index information from the fields returned by hypopg_display_index
            indexname = row.cells.get("indexname")
            indexrelid = row.cells.get("indexrelid")
            table_name = row.cells.get("table")
            columns = row.cells.get("column")
            
            if not indexname or not indexrelid:
                continue
            
            # Get the estimated size
            size = 0
            try:
                size_query = f"SELECT * FROM hypopg_estimate_size({indexrelid})"
                size_result = await sql_driver.execute_query(cast(LiteralString, size_query))
                if size_result and len(size_result) > 0:
                    size = size_result[0].cells.get("hypopg_estimate_size", 0)
            except Exception as e:
                logger.warning(f"Error getting size for index {indexname}: {e}")
            
            indexes.append({
                "name": indexname,
                "id": indexrelid,
                "table": table_name,
                "columns": columns,
                "size": size
            })
        
        if not indexes:
            return format_text_response("No virtual indexes found.")
        
        result = ["Virtual indexes:"]
        for idx in indexes:
            result.append(f"\nName: {idx['name']}")
            result.append(f"  ID: {idx['id']}")
            result.append(f"  Table: {idx['table']}")
            result.append(f"  Columns: {idx['columns']}")
            result.append(f"  Size: {idx['size']} bytes")
        
        return format_text_response("\n".join(result))
    except Exception as e:
        logger.error(f"Error listing virtual indexes: {e}")
        return format_error_response(str(e))


@mcp.tool(
    description="Drops all virtual indexes using hypopg extension.",
)
async def drop_all_virtual_indexes() -> ResponseType:
    """Drop all virtual indexes using hypopg extension."""
    try:
        sql_driver = await get_sql_driver()
        
        # First, get all virtual indexes to count them
        list_query = "SELECT * FROM hypopg_display_index()"
        indexes = await sql_driver.execute_query(cast(LiteralString, list_query))
        
        count = 0
        if indexes:
            count = len(indexes)
        
        # Reset all virtual indexes using hypopg_reset_index
        reset_query = "SELECT * FROM hypopg_reset_index()"
        await sql_driver.execute_query(cast(LiteralString, reset_query))
        
        return format_text_response(f"Dropped {count} virtual indexes and reset virtual index state.")
    except Exception as e:
        logger.error(f"Error dropping all virtual indexes: {e}")
        return format_error_response(str(e))


@mcp.tool(
    description="Estimates the benefit of a virtual index for a specific query using hypopg extension.",
)
async def estimate_index_benefit(
    query: str = Field(description="SQL query to analyze"),
    index_id: int = Field(description="ID of the virtual index to evaluate"),
) -> ResponseType:
    """Estimate the benefit of a virtual index for a specific query using hypopg extension."""
    try:
        sql_driver = await get_sql_driver()
        
        # Get the plan without the index (reset all virtual indexes first)
        reset_query = "SELECT * FROM hypopg_reset_index()"
        await sql_driver.execute_query(cast(LiteralString, reset_query))
        
        # Get plan without index
        explain_sql = f"EXPLAIN (COSTS OFF, FORMAT JSON) {query}"
        result_without = await sql_driver.execute_query(cast(LiteralString, explain_sql))
        
        cost_without = 0.0
        if result_without and len(result_without) > 0:
            plan_data = result_without[0].cells.get("QUERY PLAN", {})
            if plan_data and isinstance(plan_data, list) and len(plan_data) > 0:
                cost_without = _extract_plan_cost(plan_data[0])
        
        # Recreate the specific virtual index
        # First get the index definition
        list_query = "SELECT * FROM hypopg_display_index()"
        all_indexes = await sql_driver.execute_query(cast(LiteralString, list_query))
        
        target_index = None
        if all_indexes:
            for row in all_indexes:
                if row.cells.get("indexrelid") == index_id:
                    target_index = row
                    break
        
        if not target_index:
            return format_error_response(f"Virtual index with ID {index_id} not found")
        
        # Recreate the index
        table_name = target_index.cells.get("table")
        columns = target_index.cells.get("column")
        index_def = f"{table_name}({columns})"
        
        create_sql = f"SELECT * FROM hypopg_create_index('{index_def}')"
        await sql_driver.execute_query(cast(LiteralString, create_sql))
        
        # Get plan with index
        result_with = await sql_driver.execute_query(cast(LiteralString, explain_sql))
        
        cost_with = 0.0
        plan_data_with = None
        if result_with and len(result_with) > 0:
            plan_data_with = result_with[0].cells.get("QUERY PLAN", {})
            if plan_data_with and isinstance(plan_data_with, list) and len(plan_data_with) > 0:
                cost_with = _extract_plan_cost(plan_data_with[0])
        
        # Calculate improvement
        improvement = 0.0
        if cost_without > 0:
            improvement = ((cost_without - cost_with) / cost_without) * 100
        
        # Check if the index is used
        index_used = _check_index_used(plan_data_with[0] if plan_data_with else {}, index_id)
        
        result = [f"Index benefit analysis for ID: {index_id}"]
        result.append(f"Cost without index: {cost_without}")
        result.append(f"Cost with index: {cost_with}")
        result.append(f"Improvement: {improvement:.2f}%")
        result.append(f"Index used: {index_used}")
        
        return format_text_response("\n".join(result))
    except Exception as e:
        logger.error(f"Error estimating index benefit: {e}")
        return format_error_response(str(e))


@mcp.tool(
    description="Gets global file I/O statistics from dbe_perf.global_file_iostat view.",
)
async def get_global_file_iostat(
    hours: int = Field(description="Number of hours to analyze", default=24),
) -> ResponseType:
    """Get global file I/O statistics from dbe_perf.global_file_iostat view."""
    try:
        sql_driver = await get_sql_driver()
        health_monitor = DbePerfHealthMonitor(sql_driver=sql_driver)
        result = await health_monitor.get_global_file_iostat(hours=hours)
        return format_text_response(result)
    except Exception as e:
        logger.error(f"Error getting global file I/O stats: {e}")
        return format_error_response(str(e))


@mcp.tool(
    description="Gets global wait events from dbe_perf.global_wait_events view.",
)
async def get_global_wait_events(
    hours: int = Field(description="Number of hours to analyze", default=24),
) -> ResponseType:
    """Get global wait events from dbe_perf.global_wait_events view."""
    try:
        sql_driver = await get_sql_driver()
        health_monitor = DbePerfHealthMonitor(sql_driver=sql_driver)
        result = await health_monitor.get_global_wait_events(hours=hours)
        return format_text_response(result)
    except Exception as e:
        logger.error(f"Error getting global wait events: {e}")
        return format_error_response(str(e))


@mcp.tool(
    description="Gets a comprehensive health report using multiple dbe_perf views.",
)
async def get_comprehensive_health_report() -> ResponseType:
    """Get a comprehensive health report using multiple dbe_perf views."""
    try:
        sql_driver = await get_sql_driver()
        health_monitor = DbePerfHealthMonitor(sql_driver=sql_driver)
        result = await health_monitor.get_comprehensive_health_report()
        return format_text_response(result)
    except Exception as e:
        logger.error(f"Error getting comprehensive health report: {e}")
        return format_error_response(str(e))


async def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="openGauss MCP Server")
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
    parser.add_argument(
        "--log-level",
        type=str,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default="INFO",
        help="Set logging level (default: INFO)",
    )

    args = parser.parse_args()
    
    # Set up logging
    setup_logging(level=args.log_level)

    # Store the access mode in the global variable
    global current_access_mode
    current_access_mode = AccessMode(args.access_mode)

    # Add the query tool with a description appropriate to the access mode
    if current_access_mode == AccessMode.UNRESTRICTED:
        mcp.add_tool(execute_sql, description="Execute any SQL query")
    else:
        mcp.add_tool(execute_sql, description="Execute a read-only SQL query")

    logger.info(f"Starting openGauss MCP Server in {current_access_mode.upper()} mode")

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


def _extract_plan_cost(plan: dict[str, Any]) -> float:
    """Extract the total cost from an explain plan.

    Args:
        plan: Explain plan dictionary

    Returns:
        Total cost as a float
    """
    try:
        if not plan:
            return 0.0
            
        # Check if this is a plan node with a cost
        if "Total Cost" in plan:
            return float(plan["Total Cost"])
            
        # Recursively check child plans
        if "Plans" in plan:
            max_cost = 0.0
            for child_plan in plan["Plans"]:
                child_cost = _extract_plan_cost(child_plan)
                if child_cost > max_cost:
                    max_cost = child_cost
            return max_cost
            
        return 0.0
    except Exception as e:
        logger.error(f"Error extracting plan cost: {e}")
        return 0.0


def _check_index_used(plan: dict[str, Any], index_id: int) -> bool:
    """Check if an index is used in an explain plan.

    Args:
        plan: Explain plan dictionary
        index_id: ID of the index to check

    Returns:
        True if the index is used, False otherwise
    """
    try:
        if not plan:
            return False
            
        # Check if this node uses the index
        node_type = plan.get("Node Type", "")
        if node_type in ["Index Scan", "Index Only Scan", "Bitmap Index Scan"]:
            plan_index_name = plan.get("Index Name", "")
            # For hypopg, we can't easily match by ID, so we'll just check if any index is used
            if plan_index_name:
                return True
                
        # Recursively check child plans
        if "Plans" in plan:
            for child_plan in plan["Plans"]:
                if _check_index_used(child_plan, index_id):
                    return True
                    
        return False
    except Exception as e:
        logger.error(f"Error checking if index is used: {e}")
        return False
