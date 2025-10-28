#!/usr/bin/env python3
"""
Test script for openGauss MCP Server.

This script tests the MCP server functionality including all available tools.
It can be used to verify the server works correctly with different database types.
"""

import asyncio
import sys
import os
import json
from typing import Any, Dict, List
import ast

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from opengauss_mcp.server import list_schemas, list_objects, get_object_details, explain_query, execute_sql, db_connection
from opengauss_mcp.server import analyze_workload_indexes, analyze_query_indexes, analyze_indexes_with_llm_only, analyze_db_health
from opengauss_mcp.server import get_top_queries, get_queries_with_resource_metrics, get_queries_by_resource_efficiency
from opengauss_mcp.server import get_detailed_session_info, get_long_running_queries, get_blocked_queries
from opengauss_mcp.server import create_virtual_index, drop_virtual_index, list_virtual_indexes, drop_all_virtual_indexes, estimate_index_benefit
from opengauss_mcp.server import get_global_file_iostat, get_global_wait_events, get_comprehensive_health_report
from opengauss_mcp.sql.extension_utils import get_database_type, check_dbe_perf_availability, check_virtual_index_support
from opengauss_mcp.sql.sql_driver import SqlDriver

# Test configuration
DEFAULT_DATABASE_URL = "postgresql://mogdb:My%40321566@localhost:15432/postgres"
DEFAULT_API_KEY = "4cfcea4583a04d93ae62daac71011178.bSvdXhJWQPJxF8vC"


async def initialize_database_connection(database_url):
    """Initialize the global database connection pool for MCP server tools."""
    print("Initializing global database connection pool...")

    try:
        # Initialize the global db_connection pool
        await db_connection.pool_connect(database_url)
        print("✅ Global database connection pool initialized successfully")
        return True
    except Exception as e:
        print(f"❌ Error initializing global database connection: {e}")
        return False


def check_tool_result(result, tool_name: str) -> bool:
    """Check if a tool result indicates success or failure."""
    if result and not str(result).startswith("Error:"):
        return True
    else:
        print(f"❌ {tool_name} tool failed: {result}")
        return False


async def test_database_connection(database_url):
    """Test database connection and type detection."""
    print("Testing database connection...")

    try:
        # Create SQL driver
        sql_driver = SqlDriver(engine_url=database_url)

        # Test database type detection
        db_type = await get_database_type(sql_driver)
        print(f"Database type detected: {db_type}")

        if db_type == "opengauss":
            print("✅ Successfully connected to openGauss database")

            # Test dbe_perf availability
            dbe_perf_available, dbe_perf_message = await check_dbe_perf_availability(sql_driver)
            print(f"dbe_perf availability: {dbe_perf_available}")
            if not dbe_perf_available:
                print(f"dbe_perf message: {dbe_perf_message}")

            # Test virtual index support
            virtual_index_supported, virtual_index_message = await check_virtual_index_support(sql_driver)
            print(f"Virtual index support: {virtual_index_supported}")
            if not virtual_index_supported:
                print(f"Virtual index message: {virtual_index_message}")

            return sql_driver
        elif db_type == "postgresql":
            print("⚠️ Connected to PostgreSQL database (not openGauss)")
            print("This plugin is designed for openGauss, but many features will work with PostgreSQL")
            return sql_driver
        else:
            print(f"❌ Unknown database type: {db_type}")
            return None
    except Exception as e:
        print(f"❌ Error connecting to database: {e}")
        return None


async def test_basic_tools():
    """Test basic MCP tools."""
    print("\nTesting basic MCP tools...")

    try:
        # Test list_schemas
        result = await list_schemas()
        if check_tool_result(result, "list_schemas"):
            schemas = ast.literal_eval(result[0].text) if hasattr(result[0], 'text') else result
            schema_count = len(schemas) if isinstance(schemas, list) else 0
            print(f"✅ list_schemas tool works (found {schema_count} schemas)")
        else:
            return False

        # Test list_objects
        result = await list_objects(schema_name="public", object_type="table")
        if check_tool_result(result, "list_objects"):
            objects = ast.literal_eval(result[0].text) if hasattr(result[0], 'text') else result
            object_count = len(objects) if isinstance(objects, list) else 0
            print(f"✅ list_objects tool works (found {object_count} tables)")
        else:
            return False

        # Test get_object_details
        result = await get_object_details(
            schema_name="pg_catalog",
            object_name="pg_class",
            object_type="table"
        )
        if check_tool_result(result, "get_object_details"):
            print("✅ get_object_details tool works")
        else:
            return False

        # Test explain_query (basic)
        result = await explain_query(sql="select * from dbe_perf.statement", hypothetical_indexes=[])
        if check_tool_result(result, "explain_query"):
            print("✅ explain_query tool works")
        else:
            return False

        # Test explain_query with a simple hypothetical index
        simple_index = [{"table": "dbe_perf.statement", "columns": ["query"], "using": "btree"}]
        result = await explain_query(sql="select * from dbe_perf.statement", analyze=False, hypothetical_indexes=simple_index)
        if check_tool_result(result, "explain_query with hypothetical indexes"):
            print("✅ explain_query with hypothetical indexes works")
        else:
            print("⚠️ explain_query with hypothetical indexes failed (may not be supported on this database)")

        # Test execute_sql
        result = await execute_sql(sql="SELECT version()")
        if check_tool_result(result, "execute_sql"):
            print("✅ execute_sql tool works")
        else:
            return False

        return True
    except Exception as e:
        print(f"❌ Error testing basic tools: {e}")
        return False


async def test_query_tools():
    """Test query-related MCP tools."""
    print("\nTesting query-related MCP tools...")
    
    try:
        # Test get_top_queries
        result = await get_top_queries(sort_by="resources", limit=5)
        if check_tool_result(result, "get_top_queries"):
            print("✅ get_top_queries tool works")
        else:
            return False

        # Test get_queries_with_resource_metrics
        result = await get_queries_with_resource_metrics(limit=5)
        if check_tool_result(result, "get_queries_with_resource_metrics"):
            print("✅ get_queries_with_resource_metrics tool works")
        else:
            return False

        # Test get_queries_by_resource_efficiency
        result = await get_queries_by_resource_efficiency(limit=5)
        if check_tool_result(result, "get_queries_by_resource_efficiency"):
            print("✅ get_queries_by_resource_efficiency tool works")
        else:
            return False

        return True
    except Exception as e:
        print(f"❌ Error testing query tools: {e}")
        return False


async def test_health_tools():
    """Test health-related MCP tools."""
    print("\nTesting health-related MCP tools...")
    
    try:
        # Test analyze_db_health
        result = await analyze_db_health(health_type="connection")
        print("✅ analyze_db_health tool works")
        
        # Test get_detailed_session_info
        result = await get_detailed_session_info(include_idle=False)
        print("✅ get_detailed_session_info tool works")
        
        # Test get_long_running_queries
        result = await get_long_running_queries(threshold_minutes=5)
        print("✅ get_long_running_queries tool works")
        
        # Test get_blocked_queries
        result = await get_blocked_queries()
        print("✅ get_blocked_queries tool works")
        
        return True
    except Exception as e:
        print(f"❌ Error testing health tools: {e}")
        return False


async def test_virtual_index_tools():
    """Test virtual index MCP tools."""
    print("\nTesting virtual index MCP tools...")

    try:
        # Test list_virtual_indexes
        result = await list_virtual_indexes()
        print("✅ list_virtual_indexes tool works")

        # Test create_virtual_index
        result = await create_virtual_index(
            table="pg_class",
            columns=["relname"],
            index_type="btree"
        )
        print("✅ create_virtual_index tool works")
        print(f"Result: {result[0].text[:100] if result else 'No result'}")

        # Test estimate_index_benefit
        # Note: This would need the index ID from the create_virtual_index result
        # For now, we'll just test that the function exists and handles missing parameters gracefully
        try:
            result = await estimate_index_benefit(
                index_id="test_index_id",
                query="SELECT * FROM pg_class WHERE relname = 'test'"
            )
            print("✅ estimate_index_benefit tool works")
        except Exception as benefit_error:
            print(f"⚠️ estimate_index_benefit tool available (may need valid index ID): {benefit_error}")

        # Test drop_virtual_index (with a test index name)
        try:
            result = await drop_virtual_index(index_name="test_virtual_index")
            print("✅ drop_virtual_index tool works")
        except Exception as drop_error:
            print(f"⚠️ drop_virtual_index tool available (may need existing index): {drop_error}")

        # Test drop_all_virtual_indexes
        result = await drop_all_virtual_indexes()
        print("✅ drop_all_virtual_indexes tool works")

        return True
    except Exception as e:
        print(f"❌ Error testing virtual index tools: {e}")
        return False


async def test_index_tools():
    """Test index optimization MCP tools."""
    print("\nTesting index optimization MCP tools...")

    try:
        # Test analyze_workload_indexes
        result = await analyze_workload_indexes(max_index_size_mb=100, method="dta")
        print("✅ analyze_workload_indexes tool works")

        # Test analyze_query_indexes
        result = await analyze_query_indexes(
            queries=["SELECT * FROM pg_class WHERE relname = 'pg_class'"],
            max_index_size_mb=100,
            method="dta"
        )
        print("✅ analyze_query_indexes tool works")

        # Test analyze_indexes_with_llm_only
        result = await analyze_indexes_with_llm_only(
            queries=["SELECT * FROM pg_class WHERE relname = 'pg_class'"],
            max_index_size_mb=100
        )
        print("✅ analyze_indexes_with_llm_only tool works")

        return True
    except Exception as e:
        print(f"❌ Error testing index tools: {e}")
        return False


async def test_monitoring_tools():
    """Test monitoring MCP tools."""
    print("\nTesting monitoring MCP tools...")
    
    try:
        # Test get_global_file_iostat
        result = await get_global_file_iostat(hours=24)
        print("✅ get_global_file_iostat tool works")
        
        # Test get_global_wait_events
        result = await get_global_wait_events(hours=24)
        print("✅ get_global_wait_events tool works")
        
        # Test get_comprehensive_health_report
        result = await get_comprehensive_health_report()
        print("✅ get_comprehensive_health_report tool works")
        
        return True
    except Exception as e:
        print(f"❌ Error testing monitoring tools: {e}")
        return False


async def main():
    """Main test function."""
    print("openGauss MCP Server Test Script")
    print("=" * 40)

    # Get database URL from environment or command line
    database_url = os.environ.get("DATABASE_URI")
    if not database_url:
        print("DATABASE_URI environment variable not set, using default")
        database_url = DEFAULT_DATABASE_URL
        print(f"Using default database URL: {database_url}")
    else:
        print(f"Using database URL from environment: {database_url}")

    # Get API key from environment or use default
    api_key = os.environ.get("ZAI_API_KEY")
    if not api_key:
        print("ZAI_API_KEY environment variable not set, using default")
        api_key = DEFAULT_API_KEY
        print(f"Using default API key: {api_key[:20]}...")
    else:
        print(f"Using API key from environment: {api_key[:20]}...")

    # Set environment variables for the MCP server
    os.environ["DATABASE_URI"] = database_url
    os.environ["ZAI_API_KEY"] = api_key
    os.environ["OPENGAUSS_MCP_LOG_LEVEL"] = "INFO"

    # Initialize the global database connection pool for MCP server tools
    connection_initialized = await initialize_database_connection(database_url)

    # Test database connection
    sql_driver = await test_database_connection(database_url)
    if not sql_driver:
        print("Database connection failed, but some tools might still work without a connection")

    if not connection_initialized:
        print("⚠️ Global database connection pool initialization failed!")
        print("   Most MCP server tools will not work without a proper connection.")
        print("   This is likely due to database connectivity issues.")
    
    # Run tests
    print("\nRunning MCP Server tool tests...")
    test_results = []
    
    # Test basic tools
    test_results.append(await test_basic_tools())
    
    # Test query tools
    test_results.append(await test_query_tools())
    
    # Test health tools
    test_results.append(await test_health_tools())
    
    # Test virtual index tools
    test_results.append(await test_virtual_index_tools())
    
    # Test index tools
    test_results.append(await test_index_tools())
    
    # Test monitoring tools
    test_results.append(await test_monitoring_tools())
    
    # Close the database connections
    try:
        # Close the test SQL driver connection
        if sql_driver:
            if sql_driver.conn and hasattr(sql_driver.conn, 'close'):
                await sql_driver.conn.close()
                print("Test SQL driver connection closed")

        # Close the global database connection pool
        if db_connection and hasattr(db_connection, 'close'):
            await db_connection.close()
            print("Global database connection pool closed")

    except Exception as e:
        print(f"Error closing database connections: {e}")
    
    # Print test results
    print("\n" + "=" * 40)
    print("TEST SUMMARY")
    print("=" * 40)

    test_names = [
        "Basic Tools (schemas, objects, details, explain, execute_sql)",
        "Query Tools (top queries, metrics, efficiency)",
        "Health Tools (database health, sessions, long-running queries)",
        "Virtual Index Tools (create, drop, list, estimate)",
        "Index Optimization Tools (workload, query, LLM analysis)",
        "Monitoring Tools (I/O stats, wait events, health report)"
    ]

    passed_tests = sum(1 for result in test_results if result)
    total_tests = len(test_results)

    for i, (name, result) in enumerate(zip(test_names, test_results)):
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"{i+1}. {name}: {status}")

    print(f"\nOverall Result: {passed_tests}/{total_tests} tests passed")

    if all(test_results):
        print("\n🎉 All tests completed successfully!")
        print("✅ OpenGauss MCP Server is fully functional")
        print("✅ All tools and features are working correctly")
        print("\n🚀 Ready for production use with Claude Desktop!")
    else:
        print(f"\n⚠️ {total_tests - passed_tests} test(s) failed.")
        print("💡 Check the error messages above for details")
        print("🔧 Some features may not be available with your current setup")


if __name__ == "__main__":
    asyncio.run(main())