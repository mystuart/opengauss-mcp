"""
Index optimization tools for OpenGauss MCP Server.

This module contains tools for index analysis and optimization including
DTA algorithm and LLM-driven index recommendations.
"""

import os
import logging
from typing import List
import mcp.types as types
from pydantic import Field
from typing_extensions import Literal

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


@mcp.tool(description="Analyze frequently executed queries in the database and recommend optimal indexes")
@handle_database_errors
@log_function_call
async def analyze_workload_indexes(
    max_index_size_mb: int = Field(description="Max index size in MB", default=10000),
    method: Literal["dta", "llm"] = Field(description="Method to use for analysis", default="dta"),
) -> ResponseType:
    """Analyze frequently executed queries in the database and recommend optimal indexes."""
    from opengauss_mcp.server import get_sql_driver
    from opengauss_mcp.index.dta_calc import DatabaseTuningAdvisor
    from opengauss_mcp.index.llm_opt import LLMOptimizerTool
    from opengauss_mcp.index.presentation import TextPresentation

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
@handle_database_errors
@log_function_call
async def analyze_query_indexes(
    queries: list[str] = Field(description="List of Query strings to analyze"),
    max_index_size_mb: int = Field(description="Max index size in MB", default=10000),
    method: Literal["dta", "llm"] = Field(description="Method to use for analysis", default="dta"),
) -> ResponseType:
    """Analyze a list of SQL queries and recommend optimal indexes."""
    from opengauss_mcp.server import get_sql_driver
    from opengauss_mcp.index.dta_calc import DatabaseTuningAdvisor
    from opengauss_mcp.index.llm_opt import LLMOptimizerTool
    from opengauss_mcp.index.presentation import TextPresentation
    from opengauss_mcp.index.index_opt_base import MAX_NUM_INDEX_TUNING_QUERIES

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
@handle_database_errors
@log_function_call
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
    from opengauss_mcp.server import get_sql_driver
    from opengauss_mcp.index.llm_opt import LLMOptimizerTool
    from opengauss_mcp.index.index_opt_base import MAX_NUM_INDEX_TUNING_QUERIES

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
