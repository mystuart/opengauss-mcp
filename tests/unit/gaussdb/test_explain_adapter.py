"""
Unit tests for GaussDB EXPLAIN adapter.

This module tests the GaussDbExplainPlanTool class and its integration
with the GaussDB SQL driver adapter.
"""

from typing import Any
from typing import Dict
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from postgres_mcp.artifacts import ErrorResult
from postgres_mcp.artifacts import ExplainPlanArtifact
from postgres_mcp.gaussdb.config import GaussDbCompatibilityConfig
from postgres_mcp.gaussdb.error_handler import GaussDbErrorHandler
from postgres_mcp.gaussdb.explain_adapter import GaussDbExplainPlanTool
from postgres_mcp.sql import IndexDefinition


class MockRowResult:
    """Mock row result for testing."""

    def __init__(self, cells: Dict[str, Any]):
        self.cells = cells


@pytest.fixture
def mock_gaussdb_driver():
    """Create a mock GaussDbSqlDriver."""
    driver = MagicMock()
    driver.base_driver = MagicMock()
    driver.execute_query = AsyncMock()
    driver.adapt_query = AsyncMock(side_effect=lambda x: x)  # Return query unchanged by default
    driver._ensure_config_loaded = AsyncMock()
    driver.compatibility_config = None
    return driver


@pytest.fixture
def mock_compatibility_config():
    """Create a mock GaussDB compatibility configuration."""
    config = GaussDbCompatibilityConfig(
        version="8.1.0",
        supports_hypopg=False,
        supports_pg_stat_statements=True,
        supports_explain_analyze=True
    )
    config.is_feature_supported = MagicMock(return_value=True)
    return config


@pytest.fixture
def gaussdb_explain_tool(mock_gaussdb_driver, mock_compatibility_config):
    """Create a GaussDbExplainPlanTool instance for testing."""
    tool = GaussDbExplainPlanTool(mock_gaussdb_driver)
    tool._compatibility_config = mock_compatibility_config
    tool._error_handler = GaussDbErrorHandler(mock_compatibility_config)
    return tool


@pytest.mark.asyncio
async def test_gaussdb_explain_tool_initialization(mock_gaussdb_driver):
    """Test initialization of GaussDbExplainPlanTool."""
    tool = GaussDbExplainPlanTool(mock_gaussdb_driver)

    assert tool.gaussdb_driver == mock_gaussdb_driver
    assert tool.sql_driver == mock_gaussdb_driver.base_driver
    assert tool._compatibility_config is None
    assert tool._error_handler is None


@pytest.mark.asyncio
async def test_ensure_config_loaded(mock_gaussdb_driver, mock_compatibility_config):
    """Test configuration loading."""
    mock_gaussdb_driver.compatibility_config = mock_compatibility_config

    tool = GaussDbExplainPlanTool(mock_gaussdb_driver)
    await tool._ensure_config_loaded()

    assert tool._compatibility_config == mock_compatibility_config
    assert tool._error_handler is not None
    mock_gaussdb_driver._ensure_config_loaded.assert_called_once()


@pytest.mark.asyncio
async def test_basic_explain_success(gaussdb_explain_tool, mock_gaussdb_driver):
    """Test successful basic EXPLAIN execution."""
    # Mock successful EXPLAIN result
    plan_data = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "users",
            "Total Cost": 100.0,
            "Startup Cost": 0.0,
            "Plan Rows": 1000,
            "Plan Width": 32
        }
    }

    mock_gaussdb_driver.execute_query.return_value = [
        MockRowResult({"QUERY PLAN": [plan_data]})
    ]

    # Mock parameter replacement
    with patch.object(gaussdb_explain_tool, 'replace_query_parameters_if_needed',
                     return_value=("SELECT * FROM users", False)):
        result = await gaussdb_explain_tool.explain("SELECT * FROM users")

    assert isinstance(result, ExplainPlanArtifact)
    mock_gaussdb_driver.adapt_query.assert_called_once_with("SELECT * FROM users")
    mock_gaussdb_driver.execute_query.assert_called_once()


@pytest.mark.asyncio
async def test_explain_analyze_success(gaussdb_explain_tool, mock_gaussdb_driver):
    """Test successful EXPLAIN ANALYZE execution."""
    # Mock successful EXPLAIN ANALYZE result
    plan_data = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "users",
            "Total Cost": 100.0,
            "Startup Cost": 0.0,
            "Plan Rows": 1000,
            "Plan Width": 32,
            "Actual Total Time": 50.0,
            "Actual Startup Time": 1.0,
            "Actual Rows": 1000,
            "Actual Loops": 1
        },
        "Execution Time": 52.5
    }

    mock_gaussdb_driver.execute_query.return_value = [
        MockRowResult({"QUERY PLAN": [plan_data]})
    ]

    # Mock parameter replacement
    with patch.object(gaussdb_explain_tool, 'replace_query_parameters_if_needed',
                     return_value=("SELECT * FROM users", False)):
        result = await gaussdb_explain_tool.explain_analyze("SELECT * FROM users")

    assert isinstance(result, ExplainPlanArtifact)
    mock_gaussdb_driver.execute_query.assert_called_once()

    # Verify ANALYZE was included in the query
    call_args = mock_gaussdb_driver.execute_query.call_args[0][0]
    assert "ANALYZE" in call_args


@pytest.mark.asyncio
async def test_explain_analyze_not_supported(gaussdb_explain_tool, mock_compatibility_config):
    """Test EXPLAIN ANALYZE when not supported."""
    # Configure as not supported
    mock_compatibility_config.is_feature_supported = MagicMock(return_value=False)

    result = await gaussdb_explain_tool.explain("SELECT * FROM users", do_analyze=True)

    assert isinstance(result, ErrorResult)
    assert "EXPLAIN ANALYZE is not supported" in result.to_text()


@pytest.mark.asyncio
async def test_explain_with_hypothetical_indexes_not_supported(gaussdb_explain_tool):
    """Test explain with hypothetical indexes when hypopg is not supported."""
    hypothetical_indexes = [
        {"table": "users", "columns": ["name"], "using": "btree"}
    ]

    result = await gaussdb_explain_tool.explain_with_hypothetical_indexes(
        "SELECT * FROM users WHERE name = 'test'",
        hypothetical_indexes
    )

    assert isinstance(result, ErrorResult)
    assert "Hypothetical indexes (hypopg) are not supported" in result.to_text()


@pytest.mark.asyncio
async def test_explain_with_hypothetical_indexes_supported(gaussdb_explain_tool, mock_gaussdb_driver, mock_compatibility_config):
    """Test explain with hypothetical indexes when hypopg is supported."""
    # Configure hypopg as supported
    mock_compatibility_config.supports_hypopg = True

    hypothetical_indexes = [
        {"table": "users", "columns": ["name"], "using": "btree"}
    ]

    plan_data = {
        "Plan": {
            "Node Type": "Index Scan",
            "Index Name": "btree_users_name",
            "Relation Name": "users",
            "Total Cost": 10.0,
            "Startup Cost": 0.1,
            "Plan Rows": 100,
            "Plan Width": 32
        }
    }

    mock_gaussdb_driver.execute_query.return_value = [
        MockRowResult({"QUERY PLAN": [plan_data]})
    ]

    # Mock parameter replacement
    with patch.object(gaussdb_explain_tool, 'replace_query_parameters_if_needed',
                     return_value=("SELECT * FROM users WHERE name = 'test'", False)):
        result = await gaussdb_explain_tool.explain_with_hypothetical_indexes(
            "SELECT * FROM users WHERE name = 'test'",
            hypothetical_indexes
        )

    assert isinstance(result, ExplainPlanArtifact)
    mock_gaussdb_driver.execute_query.assert_called_once()

    # Verify hypopg functions were called
    call_args = mock_gaussdb_driver.execute_query.call_args[0][0]
    assert "hypopg_reset()" in call_args
    assert "hypopg_create_index" in call_args


@pytest.mark.asyncio
async def test_validate_index_definitions_valid(gaussdb_explain_tool):
    """Test validation of valid index definitions."""
    valid_indexes = [
        {"table": "users", "columns": ["name"]},
        {"table": "orders", "columns": ["user_id", "created_at"], "using": "btree"}
    ]

    result = gaussdb_explain_tool._validate_index_definitions(valid_indexes)
    assert result is None  # No error


@pytest.mark.asyncio
async def test_validate_index_definitions_invalid(gaussdb_explain_tool):
    """Test validation of invalid index definitions."""
    # Missing table
    invalid_indexes = [
        {"columns": ["name"]}
    ]

    result = gaussdb_explain_tool._validate_index_definitions(invalid_indexes)
    assert isinstance(result, ErrorResult)
    assert "missing required 'table' field" in result.to_text()

    # Missing columns
    invalid_indexes = [
        {"table": "users"}
    ]

    result = gaussdb_explain_tool._validate_index_definitions(invalid_indexes)
    assert isinstance(result, ErrorResult)
    assert "missing required 'columns' field" in result.to_text()


@pytest.mark.asyncio
async def test_build_gaussdb_explain_options(gaussdb_explain_tool, mock_compatibility_config):
    """Test building EXPLAIN options for GaussDB."""
    # Test basic options
    options = gaussdb_explain_tool._build_gaussdb_explain_options(False, False)
    assert "FORMAT JSON" in options

    # Test with ANALYZE
    mock_compatibility_config.is_feature_supported = MagicMock(return_value=True)
    options = gaussdb_explain_tool._build_gaussdb_explain_options(True, False)
    assert "FORMAT JSON" in options
    assert "ANALYZE" in options

    # Test with GENERIC_PLAN
    options = gaussdb_explain_tool._build_gaussdb_explain_options(False, True)
    assert "FORMAT JSON" in options
    assert "GENERIC_PLAN" in options


@pytest.mark.asyncio
async def test_parse_gaussdb_explain_output_success(gaussdb_explain_tool):
    """Test successful parsing of GaussDB EXPLAIN output."""
    plan_data = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "users",
            "Total Cost": 100.0,
            "Startup Cost": 0.0,
            "Plan Rows": 1000,
            "Plan Width": 32
        }
    }

    rows = [MockRowResult({"QUERY PLAN": [plan_data]})]
    result = gaussdb_explain_tool._parse_gaussdb_explain_output(rows)

    assert isinstance(result, ExplainPlanArtifact)


@pytest.mark.asyncio
async def test_parse_gaussdb_explain_output_empty(gaussdb_explain_tool):
    """Test parsing empty EXPLAIN output."""
    rows = []
    result = gaussdb_explain_tool._parse_gaussdb_explain_output(rows)

    assert isinstance(result, ErrorResult)
    assert "Empty EXPLAIN result" in result.to_text()


@pytest.mark.asyncio
async def test_parse_gaussdb_explain_output_no_query_plan(gaussdb_explain_tool):
    """Test parsing EXPLAIN output without QUERY PLAN column."""
    rows = [MockRowResult({"OTHER_COLUMN": "data"})]
    result = gaussdb_explain_tool._parse_gaussdb_explain_output(rows)

    assert isinstance(result, ErrorResult)
    assert "No QUERY PLAN column found" in result.to_text()


@pytest.mark.asyncio
async def test_adapt_gaussdb_plan_structure(gaussdb_explain_tool):
    """Test adaptation of GaussDB plan structure to PostgreSQL format."""
    gaussdb_plan = {
        "Plan": {
            "Node Type": "SeqScan",  # GaussDB format
            "execution_time": 50.0,  # GaussDB field name
            "total_cost": 100.0      # GaussDB field name
        },
        "planning_time": 5.0         # GaussDB field name
    }

    adapted_plan = gaussdb_explain_tool._adapt_gaussdb_plan_structure(gaussdb_plan)

    # Check field mappings
    assert adapted_plan["Planning Time"] == 5.0
    # Note: execution_time is mapped to the plan level, not the Plan node level
    assert adapted_plan["Plan"]["Total Cost"] == 100.0


@pytest.mark.asyncio
async def test_adapt_plan_node(gaussdb_explain_tool):
    """Test adaptation of individual plan nodes."""
    gaussdb_node = {
        "Node Type": "SeqScan",  # Should be mapped to "Seq Scan"
        "Plans": [
            {"Node Type": "IndexScan"}  # Should be mapped to "Index Scan"
        ]
    }

    adapted_node = gaussdb_explain_tool._adapt_plan_node(gaussdb_node)

    # Check node type mapping
    assert adapted_node["Node Type"] == "Seq Scan"
    assert adapted_node["Plans"][0]["Node Type"] == "Index Scan"


@pytest.mark.asyncio
async def test_check_feature_availability(gaussdb_explain_tool, mock_gaussdb_driver, mock_compatibility_config):
    """Test checking feature availability."""
    # Mock successful basic EXPLAIN test
    mock_gaussdb_driver.execute_query.return_value = [
        MockRowResult({"QUERY PLAN": [{"Plan": {"Node Type": "Result"}}]})
    ]

    features = await gaussdb_explain_tool.check_feature_availability()

    assert isinstance(features, dict)
    assert "explain_analyze" in features
    assert "hypopg" in features
    assert "generic_plan" in features
    assert "basic_explain" in features
    assert features["basic_explain"] is True


@pytest.mark.asyncio
async def test_get_explain_capabilities(gaussdb_explain_tool, mock_compatibility_config):
    """Test getting comprehensive EXPLAIN capabilities."""
    mock_compatibility_config.version = "8.1.0"

    with patch.object(gaussdb_explain_tool, 'check_feature_availability',
                     return_value={"explain_analyze": True, "hypopg": False}):
        capabilities = await gaussdb_explain_tool.get_explain_capabilities()

    assert capabilities["database_type"] == "gaussdb"
    assert capabilities["version"] == "8.1.0"
    assert "features" in capabilities
    assert "supported_formats" in capabilities
    assert "supported_options" in capabilities
    assert "JSON" in capabilities["supported_formats"]


@pytest.mark.asyncio
async def test_error_handling_with_error_handler(gaussdb_explain_tool, mock_gaussdb_driver):
    """Test error handling with GaussDB error handler."""
    # Mock an exception during query execution
    mock_gaussdb_driver.execute_query.side_effect = Exception("GaussDB connection error")

    # Mock parameter replacement
    with patch.object(gaussdb_explain_tool, 'replace_query_parameters_if_needed',
                     return_value=("SELECT * FROM users", False)):
        result = await gaussdb_explain_tool.explain("SELECT * FROM users")

    assert isinstance(result, ErrorResult)
    error_text = result.to_text()
    assert "Error executing explain plan" in error_text


@pytest.mark.asyncio
async def test_fallback_to_basic_explain(gaussdb_explain_tool, mock_gaussdb_driver):
    """Test fallback to basic EXPLAIN when enhanced options fail."""
    # First call fails (enhanced EXPLAIN), second succeeds (basic EXPLAIN)
    plan_data = {
        "Plan": {
            "Node Type": "Result",
            "Total Cost": 0.01,
            "Startup Cost": 0.0,
            "Plan Rows": 1,
            "Plan Width": 4
        }
    }
    mock_gaussdb_driver.execute_query.side_effect = [
        Exception("Enhanced EXPLAIN failed"),
        [MockRowResult({"QUERY PLAN": [plan_data]})]
    ]

    result = await gaussdb_explain_tool._run_gaussdb_explain_query(
        "SELECT 1", analyze=True, generic_plan=True
    )

    assert isinstance(result, ExplainPlanArtifact)
    # Should have been called twice (failed attempt + successful fallback)
    assert mock_gaussdb_driver.execute_query.call_count == 2


@pytest.mark.asyncio
async def test_build_gaussdb_hypopg_query(gaussdb_explain_tool):
    """Test building hypopg query for GaussDB."""
    indexes = frozenset([
        IndexDefinition(table="users", columns=("name",), using="btree"),
        IndexDefinition(table="orders", columns=("user_id", "created_at"), using="btree")
    ])

    query = await gaussdb_explain_tool._build_gaussdb_hypopg_query(indexes)

    assert "SELECT hypopg_reset();" in query
    assert "SELECT hypopg_create_index(" in query
    assert query.count("SELECT hypopg_create_index(") == 2  # Two indexes


@pytest.mark.asyncio
async def test_build_gaussdb_hypopg_query_empty(gaussdb_explain_tool):
    """Test building hypopg query with no indexes."""
    indexes = frozenset()

    query = await gaussdb_explain_tool._build_gaussdb_hypopg_query(indexes)

    assert query == "SELECT hypopg_reset();"


@pytest.mark.asyncio
async def test_feature_support_checks(gaussdb_explain_tool, mock_compatibility_config):
    """Test individual feature support checks."""
    # Test EXPLAIN ANALYZE support
    mock_compatibility_config.is_feature_supported = MagicMock(return_value=True)
    assert gaussdb_explain_tool._is_explain_analyze_supported() is True

    # Test hypopg support
    mock_compatibility_config.supports_hypopg = True
    assert gaussdb_explain_tool._is_hypopg_supported() is True

    # Test generic plan support
    mock_compatibility_config.is_feature_supported = MagicMock(return_value=False)
    assert gaussdb_explain_tool._is_generic_plan_supported() is False


@pytest.mark.asyncio
async def test_explain_with_query_adaptation(gaussdb_explain_tool, mock_gaussdb_driver):
    """Test that queries are properly adapted for GaussDB."""
    plan_data = {
        "Plan": {
            "Node Type": "Result",
            "Total Cost": 0.01,
            "Startup Cost": 0.0,
            "Plan Rows": 1,
            "Plan Width": 4
        }
    }
    mock_gaussdb_driver.execute_query.return_value = [
        MockRowResult({"QUERY PLAN": [plan_data]})
    ]

    # Mock query adaptation
    mock_gaussdb_driver.adapt_query.return_value = "SELECT version() -- adapted"

    with patch.object(gaussdb_explain_tool, 'replace_query_parameters_if_needed',
                     return_value=("SELECT version() -- adapted", False)):
        result = await gaussdb_explain_tool.explain("SELECT version()")

    assert isinstance(result, ExplainPlanArtifact)
    mock_gaussdb_driver.adapt_query.assert_called_once_with("SELECT version()")
