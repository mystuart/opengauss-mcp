"""SQL driver adapter for PostgreSQL connections."""

import logging
import re
from dataclasses import dataclass
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from urllib.parse import urlparse
from urllib.parse import urlunparse

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from typing_extensions import LiteralString

from .database_detection import DatabaseType
from .database_detection import detect_database_type
from .database_detection import get_database_version

logger = logging.getLogger(__name__)


def obfuscate_password(text: str | None) -> str | None:
    """
    Obfuscate password in any text containing connection information.
    Works on connection URLs, error messages, and other strings.
    """
    if text is None:
        return None

    if not text:
        return text

    # Try first as a proper URL
    try:
        parsed = urlparse(text)
        if parsed.scheme and parsed.netloc and parsed.password:
            # Replace password with asterisks in proper URL
            netloc = parsed.netloc.replace(parsed.password, "****")
            return urlunparse(parsed._replace(netloc=netloc))
    except Exception:
        pass

    # Handle strings that contain connection strings but aren't proper URLs
    # Match postgres://user:password@host:port/dbname pattern
    url_pattern = re.compile(r"(postgres(?:ql)?:\/\/[^:]+:)([^@]+)(@[^\/\s]+)")
    text = re.sub(url_pattern, r"\1****\3", text)

    # Match connection string parameters (password=xxx)
    # This simpler pattern captures password without quotes
    param_pattern = re.compile(r'(password=)([^\s&;"\']+)', re.IGNORECASE)
    text = re.sub(param_pattern, r"\1****", text)

    # Match password in DSN format with single quotes
    dsn_single_quote = re.compile(r"(password\s*=\s*')([^']+)(')", re.IGNORECASE)
    text = re.sub(dsn_single_quote, r"\1****\3", text)

    # Match password in DSN format with double quotes
    dsn_double_quote = re.compile(r'(password\s*=\s*")([^"]+)(")', re.IGNORECASE)
    text = re.sub(dsn_double_quote, r"\1****\3", text)

    return text


class DbConnPool:
    """Database connection manager using psycopg's connection pool."""

    def __init__(self, connection_url: Optional[str] = None):
        self.connection_url = connection_url
        self.pool: AsyncConnectionPool | None = None
        self._is_valid = False
        self._last_error = None

    async def pool_connect(self, connection_url: Optional[str] = None) -> AsyncConnectionPool:
        """Initialize connection pool with retry logic."""
        # If we already have a valid pool, return it
        if self.pool and self._is_valid:
            return self.pool

        url = connection_url or self.connection_url
        self.connection_url = url
        if not url:
            self._is_valid = False
            self._last_error = "Database connection URL not provided"
            raise ValueError(self._last_error)

        # Close any existing pool before creating a new one
        await self.close()

        try:
            # Configure connection pool with appropriate settings
            self.pool = AsyncConnectionPool(
                conninfo=url,
                min_size=1,
                max_size=5,
                open=False,  # Don't connect immediately, let's do it explicitly
            )

            # Open the pool explicitly
            await self.pool.open()

            # Test the connection pool by executing a simple query
            async with self.pool.connection() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute("SELECT 1")

            self._is_valid = True
            self._last_error = None
            return self.pool
        except Exception as e:
            self._is_valid = False
            self._last_error = str(e)

            # Clean up failed pool
            await self.close()

            raise ValueError(f"Connection attempt failed: {obfuscate_password(str(e))}") from e

    async def close(self) -> None:
        """Close the connection pool."""
        if self.pool:
            try:
                # Close the pool
                await self.pool.close()
            except Exception as e:
                logger.warning(f"Error closing connection pool: {e}")
            finally:
                self.pool = None
                self._is_valid = False

    @property
    def is_valid(self) -> bool:
        """Check if the connection pool is valid."""
        return self._is_valid

    @property
    def last_error(self) -> Optional[str]:
        """Get the last error message."""
        return self._last_error


class SqlDriver:
    """Adapter class that wraps a PostgreSQL connection with the interface expected by DTA."""

    @dataclass
    class RowResult:
        """Simple class to match the Griptape RowResult interface."""

        cells: Dict[str, Any]

    def __init__(
        self,
        conn: Any = None,
        engine_url: str | None = None,
    ):
        """
        Initialize with a PostgreSQL connection or pool.

        Args:
            conn: PostgreSQL connection object or pool
            engine_url: Connection URL string as an alternative to providing a connection
        """
        if conn:
            self.conn = conn
            # Check if this is a connection pool
            self.is_pool = isinstance(conn, DbConnPool)
        elif engine_url:
            # Don't connect here since we need async connection
            self.engine_url = engine_url
            self.conn = None
            self.is_pool = False
        else:
            raise ValueError("Either conn or engine_url must be provided")

        # Database type detection attributes
        self.db_type: Optional[DatabaseType] = None
        self.db_version: Optional[str] = None
        self._db_info_initialized: bool = False

    def connect(self):
        if self.conn is not None:
            return self.conn
        if self.engine_url:
            self.conn = DbConnPool(self.engine_url)
            self.is_pool = True
            return self.conn
        else:
            raise ValueError("Connection not established. Either conn or engine_url must be provided")

    async def initialize_database_info(self) -> None:
        """
        Initialize database type and version information.
        This method is called automatically when needed.
        """
        if self._db_info_initialized:
            return

        try:
            # Ensure connection is established
            if self.conn is None:
                self.connect()

            # Detect database type and version
            self.db_type = await detect_database_type(self)
            _, self.db_version = await get_database_version(self)

            self._db_info_initialized = True
            logger.info(f"Database detected: {self.db_type.value} version {self.db_version}")

        except Exception as e:
            logger.error(f"Failed to initialize database info: {e}")
            # Set defaults to allow continued operation
            self.db_type = DatabaseType.POSTGRESQL
            self.db_version = "unknown"
            self._db_info_initialized = True

    async def execute_query_auto_commit(
        self,
        query: LiteralString | str,
        params: list[Any] | None = None,
        skip_db_init: bool = False,
    ) -> Optional[List[RowResult]]:
        """
        Execute a query with autocommit enabled.
        
        This method temporarily enables autocommit mode for the current session,
        executes the query, then restores the original autocommit setting. This is
        useful for SQL commands that cannot run inside explicit transaction blocks,
        such as ANALYZE, VACUUM, CREATE DATABASE, etc.
        
        The method works by:
        1. Saving the current autocommit setting
        2. Setting autocommit = ON
        3. Executing the query
        4. Restoring the original autocommit setting
        
        Args:
            query: SQL query to execute
            params: Query parameters
            skip_db_init: Skip database info initialization (used internally to avoid recursion)
            
        Returns:
            List of RowResult objects or None on error
        """
        return await self.execute_query(query, params, False, skip_db_init, auto_commit=True)

    async def get_database_type(self) -> DatabaseType:
        """
        Get the detected database type.
        
        Returns:
            DatabaseType enum value
        """
        if not self._db_info_initialized:
            await self.initialize_database_info()
        return self.db_type or DatabaseType.POSTGRESQL

    async def get_database_version(self) -> str:
        """
        Get the detected database version.
        
        Returns:
            Database version string
        """
        if not self._db_info_initialized:
            await self.initialize_database_info()
        return self.db_version or "unknown"

    async def is_gaussdb(self) -> bool:
        """
        Check if the connected database is GaussDB.
        
        Returns:
            True if database is GaussDB, False otherwise
        """
        db_type = await self.get_database_type()
        return db_type == DatabaseType.GAUSSDB

    async def is_postgresql(self) -> bool:
        """
        Check if the connected database is PostgreSQL.
        
        Returns:
            True if database is PostgreSQL, False otherwise
        """
        db_type = await self.get_database_type()
        return db_type == DatabaseType.POSTGRESQL

    async def execute_query(
        self,
        query: LiteralString | str,
        params: list[Any] | None = None,
        force_readonly: bool = False,
        skip_db_init: bool = False,
        auto_commit: bool = False,
    ) -> Optional[List[RowResult]]:
        """
        Execute a query and return results.

        Args:
            query: SQL query to execute
            params: Query parameters
            force_readonly: Whether to enforce read-only mode
            skip_db_init: Skip database info initialization (used internally to avoid recursion)
            auto_commit: Execute without explicit transaction (for commands like ANALYZE that cannot run in transactions)

        Returns:
            List of RowResult objects or None on error
        """
        try:
            if self.conn is None:
                self.connect()
                if self.conn is None:
                    raise ValueError("Connection not established")

            # Initialize database info on first query execution (unless skipped)
            if not self._db_info_initialized and not skip_db_init:
                await self.initialize_database_info()

            # Handle connection pool vs direct connection
            if self.is_pool:
                # For pools, get a connection from the pool
                pool = await self.conn.pool_connect()
                async with pool.connection() as connection:
                    return await self._execute_with_connection(connection, query, params, force_readonly=force_readonly, auto_commit=auto_commit)
            else:
                # Direct connection approach
                return await self._execute_with_connection(self.conn, query, params, force_readonly=force_readonly, auto_commit=auto_commit)
        except Exception as e:
            # Mark pool as invalid if there was a connection issue
            if self.conn and self.is_pool:
                self.conn._is_valid = False  # type: ignore
                self.conn._last_error = str(e)  # type: ignore
            elif self.conn and not self.is_pool:
                self.conn = None

            raise e

    async def _execute_with_connection(self, connection, query: LiteralString | str, params, force_readonly, auto_commit=False) -> Optional[List[RowResult]]:
        """Execute query with the given connection."""
        original_autocommit = None
        original_connection_autocommit = None
        transaction_started = False
        try:
            async with connection.cursor(row_factory=dict_row) as cursor:
                # Handle autocommit mode
                if auto_commit:
                    # Check if we're already in a transaction using a more reliable method
                    try:
                        await cursor.execute("SELECT txid_current_if_assigned();")
                        tx_result = await cursor.fetchall()
                        in_transaction = tx_result and tx_result[0].get('txid_current_if_assigned') is not None
                    except Exception:
                        # Fallback: try to commit any existing transaction
                        try:
                            await cursor.execute("COMMIT;")
                            logger.debug("Attempted to commit any existing transaction")
                        except Exception:
                            pass
                    
                    # Get current autocommit state to restore later
                    await cursor.execute("SHOW autocommit;")
                    result = await cursor.fetchall()
                    original_autocommit = result[0].get('autocommit', 'off').lower()
                    
                    # Store the original connection autocommit state
                    original_connection_autocommit = connection.autocommit
                    
                    # Set connection to autocommit mode
                    try:
                        await connection.set_autocommit(True)
                        logger.debug("Connection autocommit enabled for auto_commit mode")
                    except Exception as e:
                        logger.error(f"Failed to set autocommit: {e}")
                        # If we can't set autocommit, try to commit and retry
                        try:
                            await cursor.execute("COMMIT;")
                            await connection.set_autocommit(True)
                            logger.debug("Connection autocommit enabled after commit")
                        except Exception as e2:
                            logger.error(f"Failed to set autocommit after commit: {e2}")
                            raise e2
                elif force_readonly:
                    # Start read-only transaction
                    await cursor.execute("BEGIN TRANSACTION READ ONLY")
                    transaction_started = True

                if params:
                    await cursor.execute(query, params)
                else:
                    await cursor.execute(query)

                # For multiple statements, move to the last statement's results
                while cursor.nextset():
                    pass

                if cursor.description is None:  # No results (like DDL statements)
                    if auto_commit and original_autocommit is not None:
                        # Restore original connection autocommit state
                        await connection.set_autocommit(original_connection_autocommit)
                        logger.debug(f"Connection autocommit restored to: {original_connection_autocommit}")
                    elif not force_readonly and not auto_commit:
                        await cursor.execute("COMMIT")
                    elif transaction_started:
                        await cursor.execute("ROLLBACK")
                        transaction_started = False
                    return None

                # Get results from the last statement only
                rows = await cursor.fetchall()

                # Handle transaction/autocommit cleanup
                if auto_commit and original_autocommit is not None:
                    # Restore original connection autocommit state
                    await connection.set_autocommit(original_connection_autocommit)
                    logger.debug(f"Connection autocommit restored to: {original_connection_autocommit}")
                elif not force_readonly and not auto_commit:
                    await cursor.execute("COMMIT")
                elif transaction_started:
                    await cursor.execute("ROLLBACK")
                    transaction_started = False

                return [SqlDriver.RowResult(cells=dict(row)) for row in rows]

        except Exception as e:
            # Clean up transaction state if needed
            if auto_commit and original_autocommit is not None:
                try:
                    await connection.set_autocommit(original_connection_autocommit)
                except Exception as cleanup_error:
                    logger.error(f"Error restoring autocommit: {cleanup_error}")
            elif transaction_started:
                try:
                    await connection.rollback()
                except Exception as rollback_error:
                    logger.error(f"Error rolling back transaction: {rollback_error}")

            logger.error(f"Error executing query ({query}): {e}")
            raise e
