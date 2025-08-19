"""Database type detection utilities for PostgreSQL and GaussDB compatibility."""

import logging
from enum import Enum
from typing import Tuple

from typing_extensions import LiteralString

logger = logging.getLogger(__name__)


class DatabaseType(str, Enum):
    """Enumeration of supported database types."""
    POSTGRESQL = "postgresql"
    GAUSSDB = "gaussdb"


async def detect_database_type(sql_driver) -> DatabaseType:
    """
    Detect the database type by querying system information.
    
    Args:
        sql_driver: SqlDriver instance to use for queries
        
    Returns:
        DatabaseType enum value indicating the detected database type
        
    Raises:
        Exception: If database type cannot be determined
    """
    try:
        # First, try to get version information
        version_query: LiteralString = "SELECT version()"
        result = await sql_driver.execute_query(version_query, force_readonly=True, skip_db_init=True)

        if not result or not result[0].cells.get('version'):
            raise Exception("Could not retrieve database version information")

        version_string = result[0].cells['version'].lower()
        logger.debug(f"Database version string: {version_string}")

        # Check for GaussDB indicators in version string
        if any(indicator in version_string for indicator in ['gaussdb', 'gauss', 'mogdb', 'opengauss']):
            logger.info("Detected GaussDB database")
            return DatabaseType.GAUSSDB

        # Check for additional GaussDB-specific system views or functions
        try:
            # Try to query GaussDB-specific system tables or functions
            # GaussDB/MogDB/openGauss often have specific system catalogs
            gaussdb_checks = [
                # Check for GaussDB-specific tables in information_schema
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables 
                    WHERE table_schema = 'information_schema' 
                    AND table_name LIKE '_pg_%'
                    LIMIT 1
                ) as has_gaussdb_tables
                """,
                # Check for GaussDB-specific functions
                """
                SELECT EXISTS (
                    SELECT 1 FROM pg_proc 
                    WHERE proname IN ('gs_password_deadline', 'gs_password_notifytime')
                    LIMIT 1
                ) as has_gaussdb_functions
                """,
                # Check for GaussDB-specific system views
                """
                SELECT EXISTS (
                    SELECT 1 FROM pg_class c 
                    JOIN pg_namespace n ON c.relnamespace = n.oid 
                    WHERE n.nspname = 'pg_catalog' 
                    AND c.relname IN ('gs_auditing', 'gs_session_stat')
                    LIMIT 1
                ) as has_gaussdb_views
                """
            ]

            for check_query in gaussdb_checks:
                try:
                    gaussdb_result = await sql_driver.execute_query(check_query, force_readonly=True, skip_db_init=True)
                    if gaussdb_result and gaussdb_result[0].cells:
                        # Get the first (and only) column value
                        has_gaussdb_feature = list(gaussdb_result[0].cells.values())[0]
                        if has_gaussdb_feature:
                            logger.info("Detected GaussDB database via system tables/functions")
                            return DatabaseType.GAUSSDB
                except Exception as check_e:
                    logger.debug(f"GaussDB check failed (trying next): {check_e}")
                    continue

        except Exception as e:
            logger.debug(f"GaussDB-specific checks failed (expected for PostgreSQL): {e}")

        # Check for PostgreSQL indicators
        if 'postgresql' in version_string or 'postgres' in version_string:
            logger.info("Detected PostgreSQL database")
            return DatabaseType.POSTGRESQL

        # Default to PostgreSQL if we can't determine otherwise
        logger.warning(f"Could not definitively identify database type from version: {version_string}")
        logger.info("Defaulting to PostgreSQL compatibility mode")
        return DatabaseType.POSTGRESQL

    except Exception as e:
        logger.error(f"Error detecting database type: {e}")
        raise Exception(f"Failed to detect database type: {e}")


async def get_database_version(sql_driver) -> Tuple[str, str]:
    """
    Get detailed database version information.
    
    Args:
        sql_driver: SqlDriver instance to use for queries
        
    Returns:
        Tuple of (version_string, version_number) where:
        - version_string: Full version string from the database
        - version_number: Extracted version number (e.g., "13.2", "8.1.0")
        
    Raises:
        Exception: If version information cannot be retrieved
    """
    try:
        # Get full version string
        version_query: LiteralString = "SELECT version()"
        result = await sql_driver.execute_query(version_query, force_readonly=True, skip_db_init=True)

        if not result or not result[0].cells.get('version'):
            raise Exception("Could not retrieve database version information")

        version_string = result[0].cells['version']
        logger.debug(f"Full version string: {version_string}")

        # Extract version number using different patterns
        version_number = _extract_version_number(version_string)

        # Try to get additional version details if available
        try:
            # PostgreSQL has pg_version_num() function
            version_num_query: LiteralString = "SELECT current_setting('server_version_num') as version_num"
            num_result = await sql_driver.execute_query(version_num_query, force_readonly=True, skip_db_init=True)

            if num_result and num_result[0].cells.get('version_num'):
                # Convert numeric version to dotted format if needed
                numeric_version = num_result[0].cells['version_num']
                logger.debug(f"Numeric version: {numeric_version}")

        except Exception as e:
            logger.debug(f"Could not get numeric version (may not be supported): {e}")

        return version_string, version_number

    except Exception as e:
        logger.error(f"Error getting database version: {e}")
        raise Exception(f"Failed to get database version: {e}")


def _extract_version_number(version_string: str) -> str:
    """
    Extract version number from database version string.
    
    Args:
        version_string: Full version string from database
        
    Returns:
        Extracted version number string
    """
    import re

    # Common patterns for version extraction
    patterns = [
        # PostgreSQL pattern: "PostgreSQL 13.2 on ..."
        r'PostgreSQL\s+(\d+\.\d+(?:\.\d+)?)',
        # GaussDB pattern: "GaussDB 8.1.0 ..." or similar
        r'GaussDB\s+(\d+\.\d+\.\d+)',
        # MogDB pattern: "(MogDB 5.0.0 build ...)" or "MogDB 5.0.0"
        r'MogDB\s+(\d+\.\d+\.\d+)',
        # openGauss pattern: "openGauss 3.1.0" or similar
        r'openGauss\s+(\d+\.\d+\.\d+)',
        # Generic pattern: any sequence of digits and dots
        r'(\d+\.\d+(?:\.\d+)?)',
    ]

    for pattern in patterns:
        match = re.search(pattern, version_string, re.IGNORECASE)
        if match:
            version_number = match.group(1)
            logger.debug(f"Extracted version number: {version_number}")
            return version_number

    # If no pattern matches, try to find any version-like string
    fallback_match = re.search(r'(\d+(?:\.\d+)*)', version_string)
    if fallback_match:
        version_number = fallback_match.group(1)
        logger.debug(f"Fallback version extraction: {version_number}")
        return version_number

    logger.warning(f"Could not extract version number from: {version_string}")
    return "unknown"


async def get_database_info(sql_driver) -> dict:
    """
    Get comprehensive database information including type and version.
    
    Args:
        sql_driver: SqlDriver instance to use for queries
        
    Returns:
        Dictionary containing database information:
        {
            'type': DatabaseType,
            'version_string': str,
            'version_number': str,
            'is_gaussdb': bool,
            'is_postgresql': bool
        }
    """
    try:
        db_type = await detect_database_type(sql_driver)
        version_string, version_number = await get_database_version(sql_driver)

        return {
            'type': db_type,
            'version_string': version_string,
            'version_number': version_number,
            'is_gaussdb': db_type == DatabaseType.GAUSSDB,
            'is_postgresql': db_type == DatabaseType.POSTGRESQL,
        }

    except Exception as e:
        logger.error(f"Error getting database info: {e}")
        raise Exception(f"Failed to get database information: {e}")
