"""
Query analysis tools for OpenGauss MCP Server.

This module contains tools for analyzing database queries including
top queries, resource metrics, efficiency analysis, and session monitoring.
"""

import logging
from typing import List
import mcp.types as types
from pydantic import Field

from opengauss_mcp.server import mcp
from opengauss_mcp.utils import (
    ErrorContext,
    handle_database_errors,
    log_function_call,
)

logger = logging.getLogger(__name__)

ResponseType = List[types.TextContent | types.ImageContent | types.EmbeddedResource]


def format_text_response(text: str) -> ResponseType:
    """Format a text response."""
    return [types.TextContent(type="text", text=str(text))]


def format_error_response(error: str) -> ResponseType:
    """Format an error response."""
    return format_text_response(f"Error: {error}")


@mcp.tool(
    name="get_top_queries",
    description="Reports the slowest or most resource-intensive queries using data from the 'dbe_perf.statement' view.",
)
@handle_database_errors
@log_function_call
async def get_top_queries(
    sort_by: str = Field(
        description="Ranking criteria: 'total_time' for total execution time, 'mean_time' for mean execution time per call, 'resources' "
        "for resource-intensive queries, or 'io' for I/O-intensive queries",
        default="resources",
    ),
    limit: int = Field(description="Number of queries to return when ranking based on mean_time or total_time", default=10),
    threshold: float = Field(description="Fraction threshold for filtering resource/io queries (default: 0.05)", default=0.05),
) -> ResponseType:
    """Get top queries by various criteria."""
    from opengauss_mcp.server import get_sql_driver
    from opengauss_mcp.top_queries import TopQueriesCalc
    from opengauss_mcp.server import DBE_PERF_STATEMENT

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
@handle_database_errors
@log_function_call
async def get_queries_with_resource_metrics(
    limit: int = Field(description="Maximum number of queries to return", default=20),
) -> ResponseType:
    """Get queries with detailed resource consumption metrics from dbe_perf.statement."""
    from opengauss_mcp.server import get_sql_driver
    from opengauss_mcp.top_queries import TopQueriesCalc

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
@handle_database_errors
@log_function_call
async def get_queries_by_resource_efficiency(
    limit: int = Field(description="Maximum number of queries to return", default=20),
) -> ResponseType:
    """Get queries ranked by resource efficiency (rows returned per resource unit)."""
    from opengauss_mcp.server import get_sql_driver
    from opengauss_mcp.top_queries import TopQueriesCalc

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
@handle_database_errors
@log_function_call
async def get_detailed_session_info(
    include_idle: bool = Field(description="Whether to include idle connections in the results", default=True),
) -> ResponseType:
    """Get detailed session information for active connections."""
    from opengauss_mcp.server import get_sql_driver
    from opengauss_mcp.database_health import ConnectionHealthCalc

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
@handle_database_errors
@log_function_call
async def get_long_running_queries(
    threshold_minutes: int = Field(description="Threshold in minutes for considering a query as long-running", default=5),
) -> ResponseType:
    """Get queries that have been running for longer than the threshold."""
    from opengauss_mcp.server import get_sql_driver
    from opengauss_mcp.database_health import ConnectionHealthCalc

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
@handle_database_errors
@log_function_call
async def get_blocked_queries() -> ResponseType:
    """Get information about blocked and blocking queries."""
    from opengauss_mcp.server import get_sql_driver
    from opengauss_mcp.database_health import ConnectionHealthCalc

    try:
        sql_driver = await get_sql_driver()
        connection_health = ConnectionHealthCalc(sql_driver=sql_driver)
        result = await connection_health.get_blocked_queries()
        return format_text_response(result)
    except Exception as e:
        logger.error(f"Error getting blocked queries: {e}")
        return format_error_response(str(e))
