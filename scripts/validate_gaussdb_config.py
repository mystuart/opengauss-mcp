#!/usr/bin/env python3
"""
GaussDB Configuration Validation Script

This script validates GaussDB compatibility configuration files and environment settings.
It can be used to verify configuration before deployment or during troubleshooting.

Usage:
    python scripts/validate_gaussdb_config.py [config_file]
    python scripts/validate_gaussdb_config.py --env-only
    python scripts/validate_gaussdb_config.py --help
"""

import argparse
import os
import re
import sys
from typing import Any
from typing import Dict
from typing import List

import yaml


# Color codes for output
class Colors:
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    PURPLE = '\033[0;35m'
    CYAN = '\033[0;36m'
    NC = '\033[0m'  # No Color

def log_info(message: str):
    print(f"{Colors.BLUE}[INFO]{Colors.NC} {message}")

def log_warn(message: str):
    print(f"{Colors.YELLOW}[WARN]{Colors.NC} {message}")

def log_error(message: str):
    print(f"{Colors.RED}[ERROR]{Colors.NC} {message}")

def log_success(message: str):
    print(f"{Colors.GREEN}[SUCCESS]{Colors.NC} {message}")

def log_debug(message: str):
    print(f"{Colors.PURPLE}[DEBUG]{Colors.NC} {message}")

class GaussDBConfigValidator:
    """Validator for GaussDB compatibility configuration"""

    def __init__(self):
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.info: List[str] = []

    def validate_config_file(self, config_path: str) -> bool:
        """Validate a GaussDB configuration file"""
        log_info(f"Validating configuration file: {config_path}")

        if not os.path.exists(config_path):
            self.errors.append(f"Configuration file not found: {config_path}")
            return False

        try:
            with open(config_path, encoding='utf-8') as f:
                config = yaml.safe_load(f)
        except yaml.YAMLError as e:
            self.errors.append(f"Invalid YAML syntax: {e}")
            return False
        except Exception as e:
            self.errors.append(f"Failed to read configuration file: {e}")
            return False

        return self._validate_config_structure(config)

    def _validate_config_structure(self, config: Dict[str, Any]) -> bool:
        """Validate the structure of the configuration"""
        valid = True

        # Validate global section
        if 'global' in config:
            valid &= self._validate_global_config(config['global'])
        else:
            self.warnings.append("No global configuration section found")

        # Validate benchmark section
        if 'benchmark' in config:
            valid &= self._validate_benchmark_config(config['benchmark'])
        else:
            self.warnings.append("No benchmark configuration section found")

        # Validate versions section
        if 'versions' in config:
            valid &= self._validate_versions_config(config['versions'])
        else:
            self.errors.append("No versions configuration section found")
            valid = False

        return valid

    def _validate_global_config(self, global_config: Dict[str, Any]) -> bool:
        """Validate global configuration section"""
        valid = True

        # Validate compatibility_mode
        if 'compatibility_mode' in global_config:
            mode = global_config['compatibility_mode']
            if mode not in ['auto', 'force', 'disabled']:
                self.errors.append(f"Invalid compatibility_mode: {mode}. Must be 'auto', 'force', or 'disabled'")
                valid = False

        # Validate numeric values
        numeric_fields = {
            'default_timeout': (1, 300),
            'max_retry_attempts': (1, 10),
            'retry_delay': (0.1, 60),
            'max_cached_queries': (10, 10000)
        }

        for field, (min_val, max_val) in numeric_fields.items():
            if field in global_config:
                value = global_config[field]
                if not isinstance(value, (int, float)) or value < min_val or value > max_val:
                    self.errors.append(f"Invalid {field}: {value}. Must be between {min_val} and {max_val}")
                    valid = False

        # Validate boolean fields
        boolean_fields = ['debug_logging', 'enable_query_cache']
        for field in boolean_fields:
            if field in global_config:
                value = global_config[field]
                if not isinstance(value, bool):
                    self.errors.append(f"Invalid {field}: {value}. Must be true or false")
                    valid = False

        return valid

    def _validate_benchmark_config(self, benchmark_config: Dict[str, Any]) -> bool:
        """Validate benchmark configuration section"""
        valid = True

        # Validate enabled flag
        if 'enabled' in benchmark_config:
            if not isinstance(benchmark_config['enabled'], bool):
                self.errors.append("benchmark.enabled must be true or false")
                valid = False

        # Validate sysbench config
        if 'sysbench' in benchmark_config:
            sysbench_config = benchmark_config['sysbench']
            if 'default_config' in sysbench_config:
                valid &= self._validate_sysbench_config(sysbench_config['default_config'])

        # Validate tpcc config
        if 'tpcc' in benchmark_config:
            tpcc_config = benchmark_config['tpcc']
            if 'default_config' in tpcc_config:
                valid &= self._validate_tpcc_config(tpcc_config['default_config'])

        return valid

    def _validate_sysbench_config(self, sysbench_config: Dict[str, Any]) -> bool:
        """Validate sysbench configuration"""
        valid = True

        numeric_fields = {
            'tables': (1, 100),
            'table_size': (1000, 10000000),
            'threads': (1, 256),
            'time': (10, 3600),
            'events': (0, 1000000)
        }

        for field, (min_val, max_val) in numeric_fields.items():
            if field in sysbench_config:
                value = sysbench_config[field]
                if not isinstance(value, int) or value < min_val or value > max_val:
                    self.errors.append(f"Invalid sysbench.{field}: {value}. Must be between {min_val} and {max_val}")
                    valid = False

        return valid

    def _validate_tpcc_config(self, tpcc_config: Dict[str, Any]) -> bool:
        """Validate TPC-C configuration"""
        valid = True

        numeric_fields = {
            'warehouses': (1, 1000),
            'connections': (1, 256),
            'rampup_time': (10, 600),
            'measure_time': (60, 3600)
        }

        for field, (min_val, max_val) in numeric_fields.items():
            if field in tpcc_config:
                value = tpcc_config[field]
                if not isinstance(value, int) or value < min_val or value > max_val:
                    self.errors.append(f"Invalid tpcc.{field}: {value}. Must be between {min_val} and {max_val}")
                    valid = False

        return valid

    def _validate_versions_config(self, versions_config: Dict[str, Any]) -> bool:
        """Validate versions configuration section"""
        valid = True

        if not versions_config:
            self.errors.append("Versions configuration is empty")
            return False

        # Check for default version
        if 'default' not in versions_config:
            self.warnings.append("No 'default' version configuration found")

        # Validate each version
        for version, version_config in versions_config.items():
            valid &= self._validate_version_config(version, version_config)

        return valid

    def _validate_version_config(self, version: str, version_config: Dict[str, Any]) -> bool:
        """Validate a specific version configuration"""
        valid = True

        # Validate boolean support flags
        support_flags = [
            'supports_hypopg', 'supports_pg_stat_statements',
            'supports_explain_analyze', 'supports_vacuum_analyze',
            'supports_replication_stats'
        ]

        for flag in support_flags:
            if flag in version_config:
                if not isinstance(version_config[flag], bool):
                    self.errors.append(f"Version {version}: {flag} must be true or false")
                    valid = False

        # Validate system_views section
        if 'system_views' in version_config:
            valid &= self._validate_system_views(version, version_config['system_views'])

        # Validate query_adaptations section
        if 'query_adaptations' in version_config:
            valid &= self._validate_query_adaptations(version, version_config['query_adaptations'])

        # Validate error_mappings section
        if 'error_mappings' in version_config:
            valid &= self._validate_error_mappings(version, version_config['error_mappings'])

        return valid

    def _validate_system_views(self, version: str, system_views: Dict[str, Any]) -> bool:
        """Validate system views configuration"""
        valid = True

        required_views = [
            'pg_stat_user_indexes', 'pg_stat_user_tables',
            'pg_stat_database', 'pg_stat_activity'
        ]

        for view in required_views:
            if view not in system_views:
                self.warnings.append(f"Version {version}: Missing system view mapping for {view}")

        return valid

    def _validate_query_adaptations(self, version: str, adaptations: List[Dict[str, Any]]) -> bool:
        """Validate query adaptations configuration"""
        valid = True

        if not isinstance(adaptations, list):
            self.errors.append(f"Version {version}: query_adaptations must be a list")
            return False

        for i, adaptation in enumerate(adaptations):
            if not isinstance(adaptation, dict):
                self.errors.append(f"Version {version}: query_adaptations[{i}] must be a dictionary")
                valid = False
                continue

            required_fields = ['name', 'pattern', 'replacement']
            for field in required_fields:
                if field not in adaptation:
                    self.errors.append(f"Version {version}: query_adaptations[{i}] missing required field: {field}")
                    valid = False

            # Validate regex pattern
            if 'pattern' in adaptation:
                try:
                    re.compile(adaptation['pattern'])
                except re.error as e:
                    self.errors.append(f"Version {version}: Invalid regex pattern in query_adaptations[{i}]: {e}")
                    valid = False

        return valid

    def _validate_error_mappings(self, version: str, error_mappings: Dict[str, str]) -> bool:
        """Validate error mappings configuration"""
        valid = True

        required_mappings = [
            'hypopg_not_supported', 'connection_failed',
            'pg_stat_statements_unavailable'
        ]

        for mapping in required_mappings:
            if mapping not in error_mappings:
                self.warnings.append(f"Version {version}: Missing error mapping for {mapping}")

        return valid

    def validate_environment(self) -> bool:
        """Validate environment variables"""
        log_info("Validating environment variables...")

        valid = True

        # Check required environment variables
        env_vars = {
            'GAUSSDB_COMPATIBILITY_MODE': ['auto', 'force', 'disabled'],
            'BENCHMARK_ENABLED': ['true', 'false'],
            'DEBUG_LOGGING': ['true', 'false'],
            'QUERY_CACHE_ENABLED': ['true', 'false']
        }

        for var, valid_values in env_vars.items():
            value = os.environ.get(var)
            if value is not None:
                if value not in valid_values:
                    self.errors.append(f"Invalid {var}: {value}. Valid values: {', '.join(valid_values)}")
                    valid = False
                else:
                    self.info.append(f"{var}={value}")
            else:
                self.info.append(f"{var} not set (will use default)")

        # Check numeric environment variables
        numeric_vars = {
            'MAX_CONNECTIONS': (1, 1000),
            'CONNECTION_TIMEOUT': (5, 300)
        }

        for var, (min_val, max_val) in numeric_vars.items():
            value = os.environ.get(var)
            if value is not None:
                try:
                    num_value = int(value)
                    if num_value < min_val or num_value > max_val:
                        self.errors.append(f"Invalid {var}: {value}. Must be between {min_val} and {max_val}")
                        valid = False
                    else:
                        self.info.append(f"{var}={value}")
                except ValueError:
                    self.errors.append(f"Invalid {var}: {value}. Must be a number")
                    valid = False
            else:
                self.info.append(f"{var} not set (will use default)")

        # Check path variables
        path_vars = ['GAUSSDB_CONFIG_PATH', 'BENCHMARK_RESULTS_DIR', 'SYSBENCH_PATH', 'TPCC_PATH']
        for var in path_vars:
            value = os.environ.get(var)
            if value is not None:
                self.info.append(f"{var}={value}")
                if var.endswith('_PATH') and value and not os.path.exists(value):
                    self.warnings.append(f"Path does not exist: {var}={value}")
            else:
                self.info.append(f"{var} not set")

        return valid

    def print_results(self):
        """Print validation results"""
        print("\n" + "="*60)
        print("VALIDATION RESULTS")
        print("="*60)

        if self.info:
            log_info("Information:")
            for info in self.info:
                print(f"  {info}")
            print()

        if self.warnings:
            log_warn("Warnings:")
            for warning in self.warnings:
                print(f"  {warning}")
            print()

        if self.errors:
            log_error("Errors:")
            for error in self.errors:
                print(f"  {error}")
            print()

        # Summary
        if not self.errors:
            log_success("Configuration validation passed!")
            if self.warnings:
                log_warn(f"Found {len(self.warnings)} warnings")
        else:
            log_error(f"Configuration validation failed with {len(self.errors)} errors")
            if self.warnings:
                log_warn(f"Also found {len(self.warnings)} warnings")

        return len(self.errors) == 0

def main():
    parser = argparse.ArgumentParser(
        description="Validate GaussDB compatibility configuration",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/validate_gaussdb_config.py config/gaussdb_compatibility.yaml
  python scripts/validate_gaussdb_config.py --env-only
  python scripts/validate_gaussdb_config.py --help
        """
    )

    parser.add_argument(
        'config_file',
        nargs='?',
        help='Path to GaussDB configuration file'
    )

    parser.add_argument(
        '--env-only',
        action='store_true',
        help='Only validate environment variables'
    )

    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose output'
    )

    args = parser.parse_args()

    validator = GaussDBConfigValidator()

    if args.env_only:
        # Only validate environment variables
        valid = validator.validate_environment()
    elif args.config_file:
        # Validate specific configuration file
        valid = validator.validate_config_file(args.config_file)
        # Also validate environment
        valid &= validator.validate_environment()
    else:
        # Try to find and validate default configuration files
        default_paths = [
            'config/gaussdb_compatibility.yaml',
            'src/opengauss_mcp/gaussdb/config/gaussdb_compatibility.yaml',
            '/app/config/gaussdb_compatibility.yaml'
        ]

        config_found = False
        for path in default_paths:
            if os.path.exists(path):
                log_info(f"Found configuration file: {path}")
                valid = validator.validate_config_file(path)
                config_found = True
                break

        if not config_found:
            log_warn("No configuration file found. Checking environment only.")
            valid = True

        # Always validate environment
        valid &= validator.validate_environment()

    # Print results
    success = validator.print_results()

    # Exit with appropriate code
    sys.exit(0 if success else 1)

if __name__ == '__main__':
    main()
