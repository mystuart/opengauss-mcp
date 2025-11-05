"""
Monitoring tools for OpenGauss MCP Server.

This module contains tools for system-level monitoring and performance tracking
including I/O statistics, wait events, and global metrics.
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
    description="Gets global file I/O statistics from dbe_perf.global_file_iostat view.",
)
@handle_database_errors
@log_function_call
async def get_global_file_iostat(
    hours: int = Field(description="Number of hours to analyze", default=24),
) -> ResponseType:
    """Get global file I/O statistics from dbe_perf.global_file_iostat view."""
    from opengauss_mcp.server import get_sql_driver
    from opengauss_mcp.database_health import DbePerfHealthMonitor

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
@handle_database_errors
@log_function_call
async def get_global_wait_events(
    hours: int = Field(description="Number of hours to analyze", default=24),
) -> ResponseType:
    """Get global wait events from dbe_perf.global_wait_events view."""
    from opengauss_mcp.server import get_sql_driver
    from opengauss_mcp.database_health import DbePerfHealthMonitor

    try:
        sql_driver = await get_sql_driver()
        health_monitor = DbePerfHealthMonitor(sql_driver=sql_driver)
        result = await health_monitor.get_global_wait_events(hours=hours)
        return format_text_response(result)
    except Exception as e:
        logger.error(f"Error getting global wait events: {e}")
        return format_error_response(str(e))
