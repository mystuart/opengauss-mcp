# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] - 2024-11-05

### Added
- New `analyze_indexes_with_llm_only` tool for pure LLM-based index recommendations
- GLM-4.5-Flash integration via Zhipu AI (ZAI SDK)
- Enhanced column information display with detailed type information
- Support for MogDB database (openGauss compatible)

### Changed
- Migrated from OpenAI API to Zhipu AI GLM-4.5-Flash model
- Environment variable changed from `OPENAI_API_KEY` to `ZAI_API_KEY`
- Improved error handling and logging
- Updated documentation to reflect openGauss-specific features

### Removed
- `estimate_index_benefit` tool (functionality merged into other tools)
- Hard-coded sensitive information from test files

### Fixed
- Security issue: Removed hard-coded database credentials and API keys from test files
- Documentation errors and outdated references

## [0.2.0] - 2024-10-21

### Added
- Database health monitoring tools
- Query performance analysis tools
- Virtual index support for openGauss
- Comprehensive test suite

### Changed
- Adapted all queries to use openGauss's dbe_perf views
- Enhanced virtual index support for openGauss native implementation

## [0.1.0] - 2024-08-15

### Added
- Initial release based on PostgreSQL MCP Pro
- Basic database tools (list_schemas, list_objects, get_object_details)
- SQL execution with safety controls
- Explain plan analysis
- Index optimization with DTA algorithm
- Connection pooling support
