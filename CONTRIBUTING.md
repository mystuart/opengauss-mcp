# Contributing to openGauss MCP

Thank you for your interest in contributing to openGauss MCP! This document provides guidelines and instructions for contributing.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Making Changes](#making-changes)
- [Testing](#testing)
- [Submitting Changes](#submitting-changes)

## Code of Conduct

This project follows the [Contributor Covenant Code of Conduct](https://www.contributor-covenant.org/version/2/1/code_of_conduct/). By participating, you are expected to uphold this code.

## Getting Started

1. Fork the repository on GitHub
2. Clone your fork locally:
   ```bash
   git clone https://github.com/YOUR_USERNAME/opengauss-mcp.git
   cd opengauss-mcp
   ```
3. Create a branch for your changes:
   ```bash
   git checkout -b feature/your-feature-name
   ```

## Development Setup

### Prerequisites

- Python 3.12 or higher
- uv package manager
- openGauss or compatible database (MogDB, GaussDB)

### Installation

```bash
# Install dependencies
uv sync

# Activate virtual environment
source .venv/bin/activate  # Linux/macOS
# or
.venv\Scripts\activate  # Windows
```

### Environment Variables

```bash
export DATABASE_URI="postgresql://username:password@localhost:15432/dbname"
export ZAI_API_KEY="your_zhipu_api_key_here"  # Optional, for LLM features
```

## Making Changes

### Code Style

This project uses:
- [Ruff](https://github.com/astral-sh/ruff) for linting and formatting
- [Pyright](https://github.com/microsoft/pyright) for type checking

```bash
# Run linter
uv run ruff check .

# Run formatter
uv run ruff format .

# Run type checker
uv run pyright
```

### Code Guidelines

1. **Type hints**: All functions should have proper type annotations
2. **Docstrings**: Use Google-style docstrings for all public functions and classes
3. **Error handling**: Use the `@handle_database_errors` decorator for database operations
4. **Logging**: Use the standard `logging` module, not `print()` statements

### Project Structure

```
opengauss-mcp/
├── src/opengauss_mcp/
│   ├── server.py          # Main MCP server
│   ├── tools/             # MCP tool implementations
│   │   ├── basic_tools.py
│   │   ├── health_tools.py
│   │   ├── index_tools.py
│   │   ├── query_tools.py
│   │   └── ...
│   ├── sql/               # SQL driver and utilities
│   ├── database_health/   # Health monitoring logic
│   ├── index/             # Index optimization logic
│   └── utils/             # Utility functions
├── tests/                 # Test files
├── docs/                  # Documentation
└── README.md
```

## Testing

### Running Tests

```bash
# Run all tests
uv run pytest

# Run specific test file
uv run pytest tests/unit/test_sql_driver.py

# Run with coverage
uv run pytest --cov=opengauss_mcp
```

### Writing Tests

- Place unit tests in `tests/unit/`
- Place integration tests in `tests/integration/`
- Use pytest fixtures from `tests/conftest.py`

## Submitting Changes

### Pull Request Process

1. Update the README.md or documentation with details of changes if needed
2. Update the CHANGELOG.md with your changes
3. Ensure all tests pass
4. Create a Pull Request with a clear description

### PR Title Format

- `feat:` - New feature
- `fix:` - Bug fix
- `docs:` - Documentation changes
- `refactor:` - Code refactoring
- `test:` - Adding or updating tests
- `chore:` - Maintenance tasks

Example: `feat: add new query analysis tool`

### Review Process

1. At least one maintainer must approve the PR
2. All CI checks must pass
3. No merge conflicts

## Questions?

If you have questions, feel free to:
- Open an issue on GitHub
- Check existing documentation in the `docs/` directory

Thank you for contributing!
