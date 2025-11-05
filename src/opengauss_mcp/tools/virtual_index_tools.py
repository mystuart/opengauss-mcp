"""
Virtual index tools for OpenGauss MCP Server.

This module contains tools for virtual index management and performance estimation
using the hypopg extension.
"""

import logging
from typing import Any, List
import mcp.types as types
from pydantic import Field
from typing_extensions import cast, LiteralString

from opengauss_mcp.server import mcp
from opengauss_mcp.utils import (
    ErrorContext,
    handle_database_errors,
    log_function_call,
)

logger = logging.getLogger(__name__)


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


ResponseType = List[types.TextContent | types.ImageContent | types.EmbeddedResource]


def format_text_response(text: str) -> ResponseType:
    """Format a text response."""
    return [types.TextContent(type="text", text=str(text))]


def format_error_response(error: str) -> ResponseType:
    """Format an error response."""
    return format_text_response(f"Error: {error}")


@mcp.tool(
    description="Creates a virtual index using hypopg extension for testing query performance without creating a real index.",
)
@handle_database_errors
@log_function_call
async def create_virtual_index(
    table: str = Field(description="Table name to create the index on"),
    columns: list[str] = Field(description="List of column names for the index"),
    index_type: str = Field(description="Type of index (btree, hash, gin, gist, spgist, brin)", default="btree"),
    where_clause: str = Field(description="Optional WHERE clause for partial index", default=""),
) -> ResponseType:
    """Create a virtual index using hypopg extension."""
    from opengauss_mcp.server import get_sql_driver

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
@handle_database_errors
@log_function_call
async def drop_virtual_index(
    index_id: int = Field(description="ID of the virtual index to drop"),
) -> ResponseType:
    """Drop a virtual index using hypopg extension."""
    from opengauss_mcp.server import get_sql_driver

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
@handle_database_errors
@log_function_call
async def list_virtual_indexes() -> ResponseType:
    """List all virtual indexes currently created using hypopg extension."""
    from opengauss_mcp.server import get_sql_driver

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
@handle_database_errors
@log_function_call
async def drop_all_virtual_indexes() -> ResponseType:
    """Drop all virtual indexes using hypopg extension."""
    from opengauss_mcp.server import get_sql_driver

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
