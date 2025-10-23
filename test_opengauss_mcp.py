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

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from opengauss_mcp.server import list_schemas, list_objects, get_object_details, explain_query
from opengauss_mcp.server import analyze_workload_indexes, analyze_query_indexes, analyze_db_health
from opengauss_mcp.server import get_top_queries, get_queries_with_resource_metrics, get_queries_by_resource_efficiency
from opengauss_mcp.server import get_detailed_session_info, get_long_running_queries, get_blocked_queries
from opengauss_mcp.server import create_virtual_index, drop_virtual_index, list_virtual_indexes, drop_all_virtual_indexes, estimate_index_benefit
from opengauss_mcp.server import get_global_file_iostat, get_global_wait_events, get_comprehensive_health_report
from opengauss_mcp.sql.extension_utils import get_database_type, check_dbe_perf_availability, check_virtual_index_support
from opengauss_mcp.sql.sql_driver import SqlDriver

# Test configuration
DEFAULT_DATABASE_URL = "postgresql://mogdb:My%40321566@localhost:15432/postgres"


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
        print("✅ list_schemas tool works")
        print(f"Found {len(result[0].text) if result else 0} schemas")
        
        # Test list_objects
        result = await list_objects(schema_name="public", object_type="table")
        print("✅ list_objects tool works")
        print(f"Found {len(result[0].text) if result else 0} tables")
        
        # Test explain_query
        result = await explain_query(sql="SELECT 1")
        print("✅ explain_query tool works")
        
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
        print("✅ get_top_queries tool works")
        
        # Test get_queries_with_resource_metrics
        result = await get_queries_with_resource_metrics(limit=5)
        print("✅ get_queries_with_resource_metrics tool works")
        
        # Test get_queries_by_resource_efficiency
        result = await get_queries_by_resource_efficiency(limit=5)
        print("✅ get_queries_by_resource_efficiency tool works")
        
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
        # For now, we'll just test that the function exists
        print("✅ estimate_index_benefit tool available")
        
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
    
    # Test database connection
    sql_driver = await test_database_connection(database_url)
    if not sql_driver:
        print("Database connection failed, but some tools might still work without a connection")
    
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
    
    # Close the database connection if it was established
    if sql_driver:
        try:
            # SqlDriver doesn't have a close method, but if its conn is a DbConnPool, we can close it
            if sql_driver.conn and hasattr(sql_driver.conn, 'close'):
                await sql_driver.conn.close()
                print("Database connection closed")
            else:
                print("Cannot close database connection - no close method available")
        except Exception as e:
            print(f"Error closing database connection: {e}")
    
    # Print test results
    print("\n" + "=" * 40)
    if all(test_results):
        print("✅ All tests completed successfully!")
    else:
        print("⚠️ Some tests failed. Check the output above for details.")
        failed_count = sum(1 for result in test_results if not result)
        print(f"Failed tests: {failed_count}/{len(test_results)}")


if __name__ == "__main__":
    asyncio.run(main())