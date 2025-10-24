<div align="center">

<img src="assets/opengauss-mcp.png" alt="OpenGauss MCP Logo" width="600"/>

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![PyPI - Version](https://img.shields.io/pypi/v/opengauss-mcp)](https://pypi.org/project/opengauss-mcp/)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

<h3>An openGauss MCP server with advanced index tuning, explain plans, health monitoring, and intelligent optimization.</h3>

<div class="toc">
  <a href="#overview">Overview</a> •
  <a href="#features">Features</a> •
  <a href="#quick-start">Quick Start</a> •
  <a href="#installation">Installation</a> •
  <a href="#configuration">Configuration</a> •
  <a href="#usage">Usage</a> •
  <a href="#mcp-server-api">MCP API</a> •
  <a href="#testing">Testing</a> •
  <a href="#technical-notes">Technical Notes</a>
</div>

</div>

## Overview

**OpenGauss MCP** is a powerful Model Context Protocol (MCP) server specifically designed for openGauss databases. Built by migrating and enhancing the PostgreSQL MCP Pro codebase, it provides comprehensive database optimization, monitoring, and intelligent tuning capabilities.

OpenGauss MCP goes beyond simple database connections by offering advanced features tailored for openGauss's unique capabilities, including dbe_perf performance views and virtual index support.

## Features

### 🔍 Advanced Database Health Monitoring
- **Connection Health**: Monitor active connections, idle sessions, and connection pool utilization
- **Performance Metrics**: Leverage openGauss's dbe_perf views for comprehensive performance insights
- **Buffer Cache Analysis**: Track cache hit rates and I/O efficiency
- **Replication Health**: Monitor replication lag and synchronization status
- **Constraint Validation**: Check for invalid constraints and data integrity issues
- **Sequence Health**: Monitor sequence usage and prevent overflow scenarios
- **Vacuum Health**: Track autovacuum performance and prevent transaction ID wraparound

### ⚡ Intelligent Index Optimization
- **Workload Analysis**: Analyze query patterns to identify performance bottlenecks
- **DTA Algorithm**: Database Tuning Advisor algorithm for systematic index optimization
- **LLM-Driven Optimization**: AI-powered index recommendations using advanced reasoning
- **Virtual Index Support**: Test index performance without creating actual indexes
- **Cost-Benefit Analysis**: Balance performance improvements against storage costs
- **Multi-Column Indexes**: Support for complex multi-column index optimization

### 📈 Query Performance Analysis
- **TOP Queries**: Identify resource-intensive queries using dbe_perf.statement
- **Resource Metrics**: Comprehensive analysis of CPU, memory, and I/O usage
- **Query Efficiency**: Rank queries by performance efficiency and identify optimization opportunities
- **Long-Running Queries**: Monitor and alert on long-running operations
- **Blocked Queries**: Detect and analyze query blocking scenarios
- **Session Monitoring**: Real-time session activity tracking

### 🧠 Smart Schema Intelligence
- **Schema Discovery**: Automatic detection and mapping of database objects
- **Context-Aware SQL**: Generate optimized SQL based on detailed schema understanding
- **Object Analysis**: Detailed information about tables, views, indexes, and constraints
- **Relationship Mapping**: Understand table relationships and foreign key dependencies

### 🛡️ Secure SQL Execution
- **Access Control**: Configurable access modes for different environments
- **Read-Only Mode**: Safe execution environment for production databases
- **SQL Parsing**: Advanced SQL parsing to prevent unsafe operations
- **Transaction Safety**: Protected transaction management and rollback capabilities

### 🚀 High-Performance Architecture
- **Async I/O**: Built on psycopg3 for optimal performance
- **Connection Pooling**: Efficient database connection management
- **SSE Transport**: Support for Server-Sent Events for scalable deployments
- **Error Handling**: Comprehensive error handling and recovery mechanisms

## Quick Start

### Prerequisites

- openGauss database (version 3.0+) or PostgreSQL database (compatible mode)
- Python 3.12 or higher
- Database credentials with appropriate permissions

### Installation

#### Option 1: Using pipx

```bash
pipx install opengauss-mcp
```

#### Option 2: Using uv

```bash
uv pip install opengauss-mcp
```

#### Option 3: From Source

```bash
git clone https://github.com/mystuart/opengauss-mcp.git
cd opengauss-mcp
uv pip install -e .
```

## Configuration

### Environment Variables

Set the following environment variables:

```bash
# Required: Database connection
export DATABASE_URI="postgresql://username:password@localhost:15432/dbname"

# Optional: LLM optimization features
export OPENAI_API_KEY="your_openai_api_key_here"

# Optional: Log level
export OPENGAUSS_MCP_LOG_LEVEL="INFO"
```

### Claude Desktop Configuration

Add to your Claude Desktop configuration file:

```json
{
  "mcpServers": {
    "opengauss": {
      "command": "opengauss-mcp",
      "args": ["--access-mode=unrestricted"],
      "env": {
        "DATABASE_URI": "postgresql://username:password@localhost:15432/dbname",
        "OPENAI_API_KEY": "your_openai_api_key_here"
      }
    }
  }
}
```

### SSE Transport Mode

For shared server deployments:

```bash
# Start SSE server
opengauss-mcp --access-mode=unrestricted --transport=sse --port=8000
```

Client configuration:
```json
{
  "mcpServers": {
    "opengauss": {
      "type": "sse",
      "url": "http://localhost:8000/sse"
    }
  }
}
```

## Usage

### Basic Usage Examples

**Check Database Health**
```
Perform a comprehensive health check of my openGauss database
```

**Analyze Slow Queries**
```
What are the slowest queries running on my database? How can I optimize them?
```

**Index Optimization**
```
Analyze my database workload and recommend indexes to improve performance
```

**Query Performance Analysis**
```
Explain the execution plan for: SELECT * FROM orders WHERE created_at > '2024-01-01'
```

### Advanced Usage

**LLM-Driven Optimization**
```
Use AI-powered optimization to analyze my complex workload and suggest index improvements
```

**Virtual Index Testing**
```
Create a virtual index on orders(customer_id) and test its performance impact
```

**Real-time Monitoring**
```
Show me active sessions, long-running queries, and any blocking situations
```

## MCP Server API

OpenGauss MCP provides comprehensive tools through the Model Context Protocol:

### Core Tools

| Tool Name | Description |
|-----------|-------------|
| `list_schemas` | List all database schemas |
| `list_objects` | List objects (tables, views, indexes) in a schema |
| `get_object_details` | Get detailed information about database objects |
| `execute_sql` | Execute SQL statements with safety controls |
| `explain_query` | Get and analyze query execution plans |

### Performance Analysis Tools

| Tool Name | Description |
|-----------|-------------|
| `get_top_queries` | Get resource-intensive queries from dbe_perf.statement |
| `get_queries_with_resource_metrics` | Queries with detailed resource usage |
| `get_queries_by_resource_efficiency` | Queries ranked by efficiency |
| `analyze_workload_indexes` | Comprehensive workload index analysis |
| `analyze_query_indexes` | Index analysis for specific queries |

### Health Monitoring Tools

| Tool Name | Description |
|-----------|-------------|
| `analyze_db_health` | Comprehensive health checks |
| `get_detailed_session_info` | Active session information |
| `get_long_running_queries` | Long-running query detection |
| `get_blocked_queries` | Blocked query analysis |
| `get_comprehensive_health_report` | Complete health assessment |

### Virtual Index Tools

| Tool Name | Description |
|-----------|-------------|
| `create_virtual_index` | Create virtual indexes for testing |
| `list_virtual_indexes` | List existing virtual indexes |
| `drop_virtual_index` | Remove specific virtual indexes |
| `drop_all_virtual_indexes` | Clean up all virtual indexes |
| `estimate_index_benefit` | Estimate performance impact of indexes |

### Monitoring Tools

| Tool Name | Description |
|-----------|-------------|
| `get_global_file_iostat` | Global file I/O statistics |
| `get_global_wait_events` | Global wait event analysis |

## Testing

### Running Tests

The project includes a comprehensive test suite:

```bash
# Run the test script
python test_opengauss_mcp.py

# Set database URL
export DATABASE_URI="postgresql://user:pass@host:port/db"
python test_opengauss_mcp.py
```

### Test Coverage

The test suite covers:
- ✅ Database connection and type detection
- ✅ Basic MCP tools (schemas, objects, explain plans)
- ✅ Query analysis tools
- ✅ Health monitoring tools
- ✅ Virtual index functionality
- ✅ Index optimization algorithms
- ✅ Performance monitoring tools

### Detailed Testing Guide

See [TEST_GUIDE.md](TEST_GUIDE.md) for comprehensive testing instructions, including:
- MCP client configuration
- LLM integration testing
- Performance benchmarking
- Troubleshooting guide

## Technical Notes

### openGauss Specific Features

This MCP server leverages openGauss-specific capabilities:

- **dbe_perf Views**: Advanced performance monitoring views not available in standard PostgreSQL
- **Virtual Indexes**: Test index performance without storage overhead
- **Enhanced Statistics**: More detailed query performance statistics
- **Optimized Algorithms**: Tuned for openGauss's query optimizer

### Migration from PostgreSQL

This project is a successful migration from PostgreSQL MCP Pro with the following enhancements:
- Adapted all queries to use openGauss's dbe_perf views
- Enhanced virtual index support
- Improved error handling for openGauss-specific features
- Added openGauss-specific health checks
- Maintained full compatibility with PostgreSQL (when available)

### Performance Optimizations

- **Connection Pooling**: Efficient database connection management
- **Async Architecture**: Non-blocking I/O for optimal performance
- **Smart Caching**: Cache frequently accessed metadata
- **Batch Operations**: Optimize bulk data retrieval

## Requirements and Compatibility

### Database Requirements

- **openGauss**: Version 3.0+ (full feature support)
- **PostgreSQL**: Version 13+ (compatibility mode, some features limited)

### Python Requirements

- Python 3.12+
- psycopg[binary] >= 3.2.6
- mcp[cli] >= 1.5.0
- Additional dependencies in pyproject.toml

### Extensions

For full functionality, ensure these extensions are available:
- `dbe_perf` (openGauss built-in)
- Virtual index support (openGauss built-in)

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Ensure all tests pass
5. Submit a pull request

## License

MIT License - see [LICENSE](LICENSE) file for details.

## Support

For issues and questions:
- Create an issue on GitHub
- Check [TEST_GUIDE.md](TEST_GUIDE.md) for troubleshooting
- Review the comprehensive test suite for usage examples