"""Utilities for working with openGauss system views and virtual indexes."""

import logging
from dataclasses import dataclass
from typing import Literal
from typing_extensions import LiteralString

from .safe_sql import SafeSqlDriver
from .sql_driver import SqlDriver

logger = logging.getLogger(__name__)

# Single global database version cache
# TODO: If we support multiple connections in the future, this should be connection-specific
_DATABASE_VERSION = None
_DATABASE_TYPE = None


@dataclass
class ExtensionStatus:
    """Status of an extension."""

    is_installed: bool
    is_available: bool
    name: str
    message: str
    default_version: str | None


def reset_database_cache() -> None:
    """Reset the database version and type cache. Primarily used for testing."""
    global _DATABASE_VERSION, _DATABASE_TYPE
    _DATABASE_VERSION = None
    _DATABASE_TYPE = None


async def get_database_type(sql_driver: SqlDriver) -> str:
    """
    Detect the database type (openGauss or PostgreSQL).

    Args:
        sql_driver: An instance of SqlDriver to execute queries

    Returns:
        Database type: 'opengauss', 'postgresql', or 'unknown'
    """
    # Check if we have a cached database type
    global _DATABASE_TYPE
    if _DATABASE_TYPE is not None:
        return _DATABASE_TYPE

    try:
        rows = await sql_driver.execute_query("SELECT version()")
        if not rows:
            logger.warning("Could not determine database type")
            return "unknown"

        version_string = rows[0].cells["version"].lower()
        if "opengauss" in version_string:
            _DATABASE_TYPE = "opengauss"
        elif "gaussdb" in version_string:
            _DATABASE_TYPE = "opengauss"
        elif "mogdb" in version_string:
            _DATABASE_TYPE = "opengauss"
        elif "postgresql" in version_string:
            _DATABASE_TYPE = "postgresql"
        else:
            _DATABASE_TYPE = "unknown"

        return _DATABASE_TYPE
    except Exception as e:
        logger.error(f"Error determining database type: {e}")
        return "unknown"


async def get_database_version(sql_driver: SqlDriver) -> int:
    """
    Get the major database version as an integer.

    Args:
        sql_driver: An instance of SqlDriver to execute queries

    Returns:
        The major database version as an integer (e.g., 16 for PostgreSQL 16.2 or openGauss 16.x)
        Returns 0 if the version cannot be determined
    """
    # Check if we have a cached version
    global _DATABASE_VERSION
    if _DATABASE_VERSION is not None:
        return _DATABASE_VERSION

    try:
        rows = await sql_driver.execute_query("SHOW server_version")
        if not rows:
            logger.warning("Could not determine database version")
            return 0

        version_string = rows[0].cells["server_version"]
        # Extract the major version (before the first dot)
        major_version = version_string.split(".")[0]
        version = int(major_version)

        # Cache the version globally
        _DATABASE_VERSION = version

        return version
    except Exception as e:
        raise ValueError("Error determining database version") from e


async def check_database_version_requirement(sql_driver: SqlDriver, min_version: int, feature_name: str) -> tuple[bool, str]:
    """
    Check if the database version meets the minimum requirement.

    Args:
        sql_driver: An instance of SqlDriver to execute queries
        min_version: The minimum required database version
        feature_name: Name of the feature that requires this version

    Returns:
        A tuple of (meets_requirement, message)
    """
    db_type = await get_database_type(sql_driver)
    db_version = await get_database_version(sql_driver)

    if db_version >= min_version:
        return True, f"{db_type.capitalize()} version {db_version} meets the requirement for {feature_name}"

    return False, (
        f"This feature ({feature_name}) requires {db_type.capitalize()} {min_version} or later. Your current version is {db_type.capitalize()} {db_version or 'unknown'}."
    )


async def check_system_view(
    sql_driver: SqlDriver,
    view_name: str,
    include_messages: bool = True,
    message_type: Literal["plain", "markdown"] = "plain",
) -> ExtensionStatus:
    """
    Check if a system view is available in the database.

    Args:
        sql_driver: An instance of SqlDriver to execute queries
        view_name: Name of the system view to check
        include_messages: Whether to include user-friendly messages in the result
        message_type: Format for messages - 'plain' or 'markdown'

    Returns:
        ExtensionStatus with fields:
            - is_installed: True if the view is available
            - is_available: True if the view is available (same as is_installed for views)
            - name: The view name
            - message: A user-friendly message about the view status
            - default_version: None for views
    """
    db_type = await get_database_type(sql_driver)
    
    try:
        # Check if the view exists by querying it
        from typing import cast
        test_query = cast(LiteralString, f"SELECT 1 FROM {view_name} LIMIT 1")
        await sql_driver.execute_query(test_query)
        
        # View exists and is accessible
        result = ExtensionStatus(
            is_installed=True,
            is_available=True,
            name=view_name,
            message="",
            default_version=None,
        )

        if include_messages:
            if message_type == "markdown":
                result.message = f"The **{view_name}** system view is available in this {db_type} database."
            else:
                result.message = f"The {view_name} system view is available in this {db_type} database."

        return result
    except Exception as e:
        # View doesn't exist or is not accessible
        result = ExtensionStatus(
            is_installed=False,
            is_available=False,
            name=view_name,
            message="",
            default_version=None,
        )

        if include_messages:
            if message_type == "markdown":
                result.message = (
                    f"The **{view_name}** system view is not available in this {db_type} database.\n\n"
                    f"This view is required for the requested functionality. "
                    f"Please ensure you are using a compatible version of {db_type}."
                )
            else:
                result.message = (
                    f"The {view_name} system view is not available in this {db_type} database. "
                    f"Please ensure you are using a compatible version of {db_type}."
                )

        return result


async def check_virtual_index_support(sql_driver: SqlDriver, message_type: Literal["plain", "markdown"] = "markdown") -> tuple[bool, str]:
    """
    Check if virtual indexes are supported in the database.

    Args:
        sql_driver: An instance of SqlDriver to execute queries
        message_type: Format for messages - 'plain' or 'markdown'

    Returns:
        A formatted message about virtual index support
    """
    db_type = await get_database_type(sql_driver)

    if db_type == "opengauss":
        if message_type == "markdown":
            return True, (
                "**openGauss** natively supports virtual indexes.\n\n"
                "Virtual indexes allow you to test index performance without actually creating the indexes. "
                "They are useful for evaluating the potential impact of indexes on query performance.\n\n"
                "**How to use:** The system will automatically use `CREATE VIRTUAL INDEX` and `DROP VIRTUAL INDEX` "
                "statements when testing hypothetical indexes."
            )
        else:
            return True, (
                "openGauss natively supports virtual indexes. "
                "Virtual indexes allow you to test index performance without actually creating the indexes. "
                "The system will automatically use CREATE VIRTUAL INDEX and DROP VIRTUAL INDEX statements."
            )
    elif db_type == "postgresql":
        if message_type == "markdown":
            return False, (
                "**PostgreSQL** does not natively support virtual indexes.\n\n"
                "This feature requires the **hypopg** extension to be installed.\n\n"
                "You can install it by running: `CREATE EXTENSION hypopg;`\n\n"
                "**Is it safe?** Installing 'hypopg' is generally safe and a standard practice for index testing. "
                "It adds a virtual layer that simulates indexes without actually creating them in the database."
            )
        else:
            return False, (
                "PostgreSQL does not natively support virtual indexes. "
                "This feature requires the hypopg extension to be installed. "
                "You can install it by running: CREATE EXTENSION hypopg;"
            )
    else:
        if message_type == "markdown":
            return False, (
                "**Unknown database type** - virtual index support cannot be determined.\n\n"
                "Virtual indexes are supported in openGauss and in PostgreSQL with the hypopg extension. "
                "Please ensure you are using a compatible database system."
            )
        else:
            return False, (
                "Unknown database type - virtual index support cannot be determined. "
                "Virtual indexes are supported in openGauss and in PostgreSQL with the hypopg extension."
            )


async def check_dbe_perf_availability(sql_driver: SqlDriver, message_type: Literal["plain", "markdown"] = "markdown") -> tuple[bool, str]:
    """
    Check if dbe_perf system views are available for query statistics.

    Args:
        sql_driver: An instance of SqlDriver to execute queries
        message_type: Format for messages - 'plain' or 'markdown'

    Returns:
        A formatted message about dbe_perf availability
    """
    db_type = await get_database_type(sql_driver)

    if db_type == "opengauss":
        # Check if dbe_perf.statement view is available
        try:
            await sql_driver.execute_query("SELECT 1 FROM dbe_perf.statement LIMIT 1")
            if message_type == "markdown":
                return True, (
                    "**openGauss** dbe_perf system views are available.\n\n"
                    "The `dbe_perf.statement` view provides comprehensive query statistics "
                    "for performance analysis and optimization."
                )
            else:
                return True, (
                    "openGauss dbe_perf system views are available. "
                    "The dbe_perf.statement view provides comprehensive query statistics."
                )
        except Exception:
            if message_type == "markdown":
                return False, (
                    "**openGauss** dbe_perf system views are not accessible.\n\n"
                    "Please ensure you have the necessary permissions to access dbe_perf views. "
                    "These views are essential for query performance analysis."
                )
            else:
                return False, (
                    "openGauss dbe_perf system views are not accessible. "
                    "Please ensure you have the necessary permissions to access dbe_perf views."
                )
    else:
        if message_type == "markdown":
            return False, (
                "**Unknown database type** - query statistics availability cannot be determined.\n\n"
                "Query statistics are available through dbe_perf views in openGauss "
                "and through pg_stat_statements extension in PostgreSQL."
            )
        else:
            return False, (
                "Unknown database type - query statistics availability cannot be determined. "
                "Query statistics are available through dbe_perf views in openGauss "
                "and through pg_stat_statements extension in PostgreSQL."
            )
