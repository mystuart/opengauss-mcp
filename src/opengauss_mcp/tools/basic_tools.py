"""
Basic database tools for OpenGauss MCP Server.

This module contains fundamental database operation tools including
schema listing, object inspection, and SQL execution.
"""

import logging
from typing import List, Union, Optional, Any
import mcp.types as types
from pydantic import Field

from opengauss_mcp.server import mcp
from opengauss_mcp.utils import (
    ErrorContext,
    handle_database_errors,
    log_function_call,
)

logger = logging.getLogger(__name__)


def format_column_info(row: Any) -> dict[str, Any]:
    """Format column information with detailed type information.

    Args:
        row: Database row containing column information

    Returns:
        Dictionary with formatted column information
    """
    column_name = row.cells["column_name"]
    data_type = row.cells["data_type"]
    is_nullable = row.cells["is_nullable"]
    column_default = row.cells["column_default"]

    # Base column info
    column_info = {
        "column": column_name,
        "data_type": data_type,
        "is_nullable": is_nullable,
        "default": column_default,
    }

    # Get extended type information
    char_max_length = row.cells.get("character_maximum_length")
    char_octet_length = row.cells.get("character_octet_length")
    numeric_precision = row.cells.get("numeric_precision")
    numeric_scale = row.cells.get("numeric_scale")

    # Format type details based on data type
    type_details = {}

    # Character string types
    if data_type in ("character", "varchar", "char", "text", "character varying"):
        if char_max_length:
            type_details["length"] = f"{char_max_length} characters"
        if char_octet_length and char_max_length != char_octet_length:
            type_details["size"] = f"{char_octet_length} bytes"

    # Binary types
    elif data_type in ("binary", "varbinary", "blob"):
        if char_octet_length:
            type_details["size"] = f"{char_octet_length} bytes"

    # Numeric types
    elif data_type in ("numeric", "decimal", "number"):
        if numeric_precision and numeric_scale:
            type_details["precision"] = f"({numeric_precision}, {numeric_scale})"
        elif numeric_precision:
            type_details["precision"] = f"({numeric_precision})"

    # Integer types - show precision if available
    elif data_type in ("smallint", "integer", "int", "bigint", "int2", "int4", "int8"):
        # PostgreSQL doesn't store precision for int types in information_schema
        # But we can infer from data_type name
        type_info = {
            "smallint": "2 bytes",
            "integer": "4 bytes",
            "int": "4 bytes",
            "bigint": "8 bytes",
            "int2": "2 bytes",
            "int4": "4 bytes",
            "int8": "8 bytes"
        }
        if data_type in type_info:
            type_details["size"] = type_info[data_type]

    # Floating point types
    elif data_type in ("real", "float", "double", "double precision", "float4", "float8"):
        type_details["precision"] = "variable"

    # Date and time types
    elif data_type in ("date", "time", "timestamp", "timestamptz", "datetime"):
        type_info = {
            "date": "3 bytes",
            "time": "3-8 bytes",
            "timestamp": "8 bytes",
            "timestamptz": "8 bytes",
            "datetime": "8 bytes"
        }
        if data_type in type_info:
            type_details["size"] = type_info[data_type]

    # Boolean
    elif data_type == "boolean":
        type_details["size"] = "1 byte"

    # JSON types
    elif data_type in ("json", "jsonb"):
        type_info = {
            "json": "variable",
            "jsonb": "variable + overhead"
        }
        if data_type in type_info:
            type_details["size"] = type_info[data_type]

    # UUID
    elif data_type == "uuid":
        type_details["size"] = "16 bytes"

    # Bit types
    elif data_type in ("bit", "bit varying", "varbit"):
        if char_max_length:
            type_details["length"] = f"{char_max_length} bits"

    # Add type details to column info if any
    if type_details:
        column_info["type_details"] = type_details

    return column_info

ResponseType = List[types.TextContent | types.ImageContent | types.EmbeddedResource]


def format_text_response(text: str) -> ResponseType:
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
    from opengauss_mcp.server import get_sql_driver

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
@handle_database_errors
@log_function_call
async def list_objects(
    schema_name: str = Field(description="Schema name"),
    object_type: str = Field(description="Object type: 'table', 'view', 'sequence', or 'extension'", default="table"),
) -> ResponseType:
    """List objects of a given type in a schema."""
    from opengauss_mcp.server import get_sql_driver
    from opengauss_mcp.sql import SafeSqlDriver

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
@handle_database_errors
@log_function_call
async def get_object_details(
    schema_name: str = Field(description="Schema name"),
    object_name: str = Field(description="Object name"),
    object_type: str = Field(description="Object type: 'table', 'view', 'sequence', or 'extension'", default="table"),
) -> ResponseType:
    """Get detailed information about a database object."""
    from opengauss_mcp.server import get_sql_driver
    from opengauss_mcp.sql import SafeSqlDriver

    try:
        sql_driver = await get_sql_driver()

        if object_type in ("table", "view"):
            # Get columns
            col_rows = await SafeSqlDriver.execute_param_query(
                sql_driver,
                """
                SELECT column_name, data_type, is_nullable, column_default, character_maximum_length, character_octet_length, numeric_precision, numeric_scale
                FROM information_schema.columns
                WHERE table_schema = {} AND table_name = {}
                ORDER BY ordinal_position
                """,
                [schema_name, object_name],
            )
            columns = (
                [format_column_info(r) for r in col_rows]
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


# Query function declaration without the decorator - we'll add it dynamically based on access mode
# This function is defined here but registered in server.py based on access mode
async def execute_sql(
    sql: str = Field(description="SQL to run", default="all"),
) -> ResponseType:
    """Executes a SQL query against the database."""
    from opengauss_mcp.server import get_sql_driver

    try:
        sql_driver = await get_sql_driver()
        rows = await sql_driver.execute_query(sql)  # type: ignore
        if rows is None:
            return format_text_response("No results")
        return format_text_response(list([r.cells for r in rows]))
    except Exception as e:
        logger.error(f"Error executing query: {e}")
        return format_error_response(str(e))
