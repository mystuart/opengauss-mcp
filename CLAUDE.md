# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Postgres MCP Pro is a Model Context Protocol (MCP) server for PostgreSQL databases with advanced features including index tuning, explain plans, health checks, and safe SQL execution. It supports both PostgreSQL and GaussDB databases through a compatibility layer.

## Development Commands

### Setup and Installation
```bash
# Install dependencies
uv pip install -e .
uv sync

# Run the server locally
uv run postgres-mcp "postgres://user:password@localhost:5432/dbname"

# Development mode with MCP dev server
uv run mcp dev -e . crystaldba/opengauss_mcp/server.py
```

### Testing
```bash
# Run all tests
uv run pytest

# Run specific test file
uv run pytest tests/unit/test_obfuscate_password.py

# Run specific test
uv run pytest tests/unit/test_db_conn_pool.py::test_pool_connect_success

# Run integration tests (requires Docker)
uv run pytest tests/integration/
```

### Code Quality
```bash
# Lint with ruff
uv run ruff check .

# Format with ruff
uv run ruff format .

# Type checking with pyright
uv run pyright
```

### Build and Release
```bash
# Build package
uv build

# Release (see justfile for details)
just release 0.3.0 "Release notes"
```

## Architecture

### Core Components

1. **Server Layer** (`server.py`): Main MCP server implementation using FastMCP
2. **SQL Layer** (`sql/`): Database connection management, safe SQL execution, and database type detection
3. **Index Tuning** (`index/`): Database tuning advisor with DTA algorithm and LLM optimization
4. **Health Checks** (`database_health/`): Comprehensive database health monitoring
5. **Query Analysis** (`explain/`, `top_queries/`): Query plan analysis and performance monitoring
6. **GaussDB Compatibility** (`gaussdb/`): Adapter layer for GaussDB database support

### Key Design Patterns

- **Adapter Pattern**: Used extensively for GaussDB compatibility (`gaussdb/` directory)
- **Strategy Pattern**: Different index optimization strategies (DTA vs LLM-based)
- **Factory Pattern**: Database type detection and appropriate driver selection
- **Safety Layers**: Multi-layered SQL execution safety with access modes

### Database Support

The project supports two database types with automatic detection:
- **PostgreSQL**: Native support with full feature set
- **GaussDB**: Compatibility layer with adapters for core functionality

Database detection happens automatically at startup via `detect_database_type()` in `sql/database_detection.py`.

### Access Modes

Two security modes control SQL execution permissions:
- **Unrestricted**: Full read/write access (development environments)
- **Restricted**: Read-only with execution time limits (production environments)

### MCP Tools Implementation

The server implements these MCP tools:
- `list_schemas`, `list_objects`, `get_object_details`: Schema exploration
- `execute_sql`: Safe SQL execution with access mode restrictions
- `explain_query`: Query plan analysis with hypothetical index simulation
- `get_top_queries`: Performance analysis using pg_stat_statements
- `analyze_workload_indexes`, `analyze_query_indexes`: Index tuning recommendations
- `analyze_db_health`: Comprehensive health checks

## Testing Architecture

### Test Structure
- **Unit Tests** (`tests/unit/`): Individual component testing
- **Integration Tests** (`tests/integration/`): Full workflow testing with Docker containers
- **Test Utilities** (`tests/utils.py`): Docker container management for PostgreSQL testing

### Test Dependencies
- Uses Docker containers for PostgreSQL testing (versions 15, 16)
- Requires HypoPG extension for index tuning tests
- Tests both PostgreSQL and GaussDB compatibility

## Development Environment

### Prerequisites
- Python 3.12+
- Docker (for integration tests)
- PostgreSQL with pg_stat_statements and hypopg extensions (for full functionality)

### Key Dependencies
- **mcp[cli]**: MCP server framework
- **psycopg[binary]**: PostgreSQL database driver
- **pglast**: SQL parsing for safety features
- **instructor**: Structured data extraction
- **pytest-asyncio**: Async testing support

### Environment Variables
- `DATABASE_URI`: PostgreSQL connection string
- `OPENAI_API_KEY`: For LLM-based index optimization (optional)

## Configuration

### MCP Server Configuration
The server accepts these command-line arguments:
- `database_url`: Database connection URL (can also use DATABASE_URI env var)
- `--access-mode`: Set SQL access mode (unrestricted/restricted)
- `--transport`: MCP transport type (stdio/sse)
- `--sse-host`, `--sse-port`: SSE server configuration

### GaussDB Configuration
GaussDB compatibility is configured through YAML files in `config/gaussdb_compatibility.yaml` with mappings for:
- System view translations
- Query adaptation rules
- Feature compatibility flags

## Important Notes

### Database Extensions
For full functionality, ensure these PostgreSQL extensions are installed:
- `pg_stat_statements`: Query performance statistics
- `hypopg`: Hypothetical index simulation

### Safety Features
- SQL parsing prevents transaction control statements in restricted mode
- Read-only transaction enforcement
- Execution time limiting in restricted mode
- Password obfuscation in logs and error messages

### Windows Compatibility
The application automatically configures WindowsSelectorEventLoopPolicy on Windows due to psycopg3 compatibility requirements.