"""
Health monitoring tools for OpenGauss MCP Server.

This module contains tools for database health analysis and monitoring
including connection health, vacuum status, index health, and more.
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
@handle_database_errors
@log_function_call
async def analyze_db_health(
    health_type: str = Field(
        description="Optional. Valid values are: index, connection, vacuum, sequence, replication, buffer, constraint, all.",
        default="all",
    ),
) -> ResponseType:
    """Analyze database health for specified components.

    Args:
        health_type: Comma-separated list of health check types to perform.
                    Valid values: index, connection, vacuum, sequence, replication, buffer, constraint, all
    """
    from opengauss_mcp.server import get_sql_driver
    from opengauss_mcp.database_health import DatabaseHealthTool

    try:
        sql_driver = await get_sql_driver()
        health_tool = DatabaseHealthTool(sql_driver)
        result = await health_tool.health(health_type=health_type)
        return format_text_response(result)
    except Exception as e:
        logger.error(f"Error analyzing database health: {e}")
        return format_error_response(str(e))


@mcp.tool(description="Gets a comprehensive health report using multiple dbe_perf views.")
@handle_database_errors
@log_function_call
async def get_comprehensive_health_report() -> ResponseType:
    """Get a comprehensive health report using multiple dbe_perf views."""
    from opengauss_mcp.server import get_sql_driver
    from opengauss_mcp.database_health import DbePerfHealthMonitor

    try:
        sql_driver = await get_sql_driver()
        health_monitor = DbePerfHealthMonitor(sql_driver=sql_driver)
        result = await health_monitor.get_comprehensive_health_report()
        return format_text_response(result)
    except Exception as e:
        logger.error(f"Error getting comprehensive health report: {e}")
        return format_error_response(str(e))
