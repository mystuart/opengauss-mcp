#!/usr/bin/env python3
"""
Configuration validation script for GaussDB compatibility settings.

This script validates the GaussDB compatibility configuration file
and provides feedback on any issues found.
"""

import logging
import sys
from typing import List

from .config_loader import ConfigLoader
from .config_loader import ConfigValidationError

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def validate_config_file(config_path: str = None) -> bool:
    """
    Validate the GaussDB compatibility configuration file.
    
    Args:
        config_path: Path to configuration file directory
        
    Returns:
        True if validation passes, False otherwise
    """
    try:
        loader = ConfigLoader(config_path)

        # Get list of available versions
        versions = loader.list_available_versions()

        if not versions:
            logger.warning("No version configurations found")
            return False

        logger.info(f"Found {len(versions)} version configurations: {', '.join(versions)}")

        # Validate each version configuration
        validation_errors: List[str] = []

        for version in versions:
            try:
                config = loader.load_config_for_version(version)
                logger.info(f"✓ Version {version}: Configuration loaded successfully")

                # Additional validation checks
                if not config.system_views:
                    validation_errors.append(f"Version {version}: No system views configured")

                if not config.query_adaptations:
                    logger.warning(f"Version {version}: No query adaptations configured")

                # Check for required system views
                required_views = [
                    "pg_stat_user_indexes",
                    "pg_stat_user_tables",
                    "pg_stat_database"
                ]

                missing_views = [view for view in required_views if view not in config.system_views]
                if missing_views:
                    validation_errors.append(f"Version {version}: Missing required system views: {', '.join(missing_views)}")

            except ConfigValidationError as e:
                validation_errors.append(f"Version {version}: {e}")
                logger.error(f"✗ Version {version}: Validation failed - {e}")
            except Exception as e:
                validation_errors.append(f"Version {version}: Unexpected error - {e}")
                logger.error(f"✗ Version {version}: Unexpected error - {e}")

        # Report results
        if validation_errors:
            logger.error(f"Configuration validation failed with {len(validation_errors)} errors:")
            for error in validation_errors:
                logger.error(f"  - {error}")
            return False
        else:
            logger.info("✓ All configurations validated successfully")
            return True

    except Exception as e:
        logger.error(f"Failed to validate configuration: {e}")
        return False


def create_default_config(config_path: str = None, force: bool = False) -> bool:
    """
    Create a default configuration file.
    
    Args:
        config_path: Path to configuration directory
        force: Whether to overwrite existing file
        
    Returns:
        True if creation successful, False otherwise
    """
    try:
        loader = ConfigLoader(config_path)
        config_file = loader.create_default_config_file(force=force)
        logger.info(f"✓ Default configuration created: {config_file}")
        return True
    except FileExistsError:
        logger.error("Configuration file already exists. Use --force to overwrite.")
        return False
    except Exception as e:
        logger.error(f"Failed to create default configuration: {e}")
        return False


def main():
    """Main entry point for the validation script."""
    import argparse

    parser = argparse.ArgumentParser(description="Validate GaussDB compatibility configuration")
    parser.add_argument("--config-dir", help="Configuration directory path")
    parser.add_argument("--create-default", action="store_true", help="Create default configuration file")
    parser.add_argument("--force", action="store_true", help="Force overwrite existing configuration")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging")

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    success = True

    if args.create_default:
        success = create_default_config(args.config_dir, args.force)
    else:
        success = validate_config_file(args.config_dir)

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
