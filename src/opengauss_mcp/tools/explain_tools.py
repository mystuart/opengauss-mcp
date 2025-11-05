"""
Explain and query analysis tools for OpenGauss MCP Server.

This module contains tools for query execution plan analysis and optimization.
"""

import logging
from typing import Any, List
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


@mcp.tool(description="Explains the execution plan for a SQL query, showing how the database will execute it and provides detailed cost estimates.")
@handle_database_errors
@log_function_call
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
    from opengauss_mcp.server import get_sql_driver
    from opengauss_mcp.explain import ExplainPlanTool
    from opengauss_mcp.sql import check_virtual_index_support

    try:
        sql_driver = await get_sql_driver()
        explain_tool = ExplainPlanTool(sql_driver=sql_driver)
        result = None

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

        if result:
            from opengauss_mcp.artifacts import ExplainPlanArtifact, ErrorResult

            if isinstance(result, ExplainPlanArtifact):
                return format_text_response(result.to_text())
            elif isinstance(result, ErrorResult):
                error_message = result.to_text()
                return format_error_response(error_message)

        return format_error_response("Error processing explain plan")
    except Exception as e:
        logger.error(f"Error explaining query: {e}")
        return format_error_response(str(e))
