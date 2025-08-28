"""Unit tests for database type detection functionality."""

from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from opengauss_mcp.sql.database_detection import DatabaseType
from opengauss_mcp.sql.database_detection import _extract_version_number
from opengauss_mcp.sql.database_detection import detect_database_type
from opengauss_mcp.sql.database_detection import get_database_info
from opengauss_mcp.sql.database_detection import get_database_version
from opengauss_mcp.sql.sql_driver import SqlDriver


class TestDatabaseDetection:
    """Test database type detection functions."""

    @pytest.fixture
    def mock_sql_driver(self):
        """Create a mock SQL driver for testing."""
        driver = MagicMock()
        driver.execute_query = AsyncMock()
        return driver

    @pytest.mark.asyncio
    async def test_detect_postgresql(self, mock_sql_driver):
        """Test detection of PostgreSQL database."""
        # Mock version query response
        version_result = [MagicMock()]
        version_result[0].cells = {'version': 'PostgreSQL 13.2 on x86_64-pc-linux-gnu'}

        # Mock GaussDB checks (all return False)
        gaussdb_result = [MagicMock()]
        gaussdb_result[0].cells = {'has_gaussdb_tables': False}

        # Set up side effects for multiple calls
        mock_sql_driver.execute_query.side_effect = [
            version_result,  # First call for version
            gaussdb_result,  # GaussDB table check
            gaussdb_result,  # GaussDB function check
            gaussdb_result,  # GaussDB view check
        ]

        result = await detect_database_type(mock_sql_driver)

        assert result == DatabaseType.POSTGRESQL

    @pytest.mark.asyncio
    async def test_detect_gaussdb_from_version(self, mock_sql_driver):
        """Test detection of GaussDB from version string."""
        # Mock version query response with GaussDB indicator
        mock_result = [MagicMock()]
        mock_result[0].cells = {'version': 'GaussDB 8.1.0 on x86_64-linux-gnu'}
        mock_sql_driver.execute_query.return_value = mock_result

        result = await detect_database_type(mock_sql_driver)

        assert result == DatabaseType.GAUSSDB

    @pytest.mark.asyncio
    async def test_detect_mogdb_from_version(self, mock_sql_driver):
        """Test detection of MogDB (GaussDB variant) from version string."""
        # Mock version query response with MogDB indicator
        mock_result = [MagicMock()]
        mock_result[0].cells = {'version': '(MogDB 5.0.0 build 503a9ef7) compiled at 2023-06-26 16:30:46 commit 0 last mr 1804  on aarch64-unknown-linux-gnu, compiled by g++ (GCC) 7.3.0, 64-bit'}
        mock_sql_driver.execute_query.return_value = mock_result

        result = await detect_database_type(mock_sql_driver)

        assert result == DatabaseType.GAUSSDB

    @pytest.mark.asyncio
    async def test_detect_opengauss_from_version(self, mock_sql_driver):
        """Test detection of openGauss from version string."""
        # Mock version query response with openGauss indicator
        mock_result = [MagicMock()]
        mock_result[0].cells = {'version': 'openGauss 3.1.0 on x86_64-linux-gnu'}
        mock_sql_driver.execute_query.return_value = mock_result

        result = await detect_database_type(mock_sql_driver)

        assert result == DatabaseType.GAUSSDB

    @pytest.mark.asyncio
    async def test_detect_gaussdb_from_system_table(self, mock_sql_driver):
        """Test detection of GaussDB from system tables."""
        # Mock version query response (generic)
        version_result = [MagicMock()]
        version_result[0].cells = {'version': 'PostgreSQL 9.2.4 compiled at Sep 9 2021'}

        # Mock GaussDB system table check (first check succeeds)
        gaussdb_result = [MagicMock()]
        gaussdb_result[0].cells = {'has_gaussdb_tables': True}

        # Set up side effects for multiple calls
        mock_sql_driver.execute_query.side_effect = [version_result, gaussdb_result]

        result = await detect_database_type(mock_sql_driver)

        assert result == DatabaseType.GAUSSDB
        assert mock_sql_driver.execute_query.call_count == 2

    @pytest.mark.asyncio
    async def test_detect_database_type_error_handling(self, mock_sql_driver):
        """Test error handling in database type detection."""
        # Mock query failure
        mock_sql_driver.execute_query.side_effect = Exception("Connection failed")

        with pytest.raises(Exception, match="Failed to detect database type"):
            await detect_database_type(mock_sql_driver)

    @pytest.mark.asyncio
    async def test_get_database_version_postgresql(self, mock_sql_driver):
        """Test getting PostgreSQL version information."""
        # Mock version query response
        mock_result = [MagicMock()]
        mock_result[0].cells = {'version': 'PostgreSQL 13.2 on x86_64-pc-linux-gnu'}

        # Mock version number query
        version_num_result = [MagicMock()]
        version_num_result[0].cells = {'version_num': '130002'}

        mock_sql_driver.execute_query.side_effect = [mock_result, version_num_result]

        version_string, version_number = await get_database_version(mock_sql_driver)

        assert version_string == 'PostgreSQL 13.2 on x86_64-pc-linux-gnu'
        assert version_number == '13.2'

    @pytest.mark.asyncio
    async def test_get_database_version_gaussdb(self, mock_sql_driver):
        """Test getting GaussDB version information."""
        # Mock version query response
        mock_result = [MagicMock()]
        mock_result[0].cells = {'version': 'GaussDB 8.1.0 on x86_64-linux-gnu'}

        # Mock version number query (may fail for GaussDB)
        mock_sql_driver.execute_query.side_effect = [
            mock_result,
            Exception("Function not supported")
        ]

        version_string, version_number = await get_database_version(mock_sql_driver)

        assert version_string == 'GaussDB 8.1.0 on x86_64-linux-gnu'
        assert version_number == '8.1.0'

    @pytest.mark.asyncio
    async def test_get_database_info(self, mock_sql_driver):
        """Test getting comprehensive database information."""
        # Mock version query response for detect_database_type
        version_result = [MagicMock()]
        version_result[0].cells = {'version': 'PostgreSQL 13.2 on x86_64-pc-linux-gnu'}

        # Mock GaussDB system table checks (all return False)
        gaussdb_tables_result = [MagicMock()]
        gaussdb_tables_result[0].cells = {'has_gaussdb_tables': False}
        
        gaussdb_functions_result = [MagicMock()]
        gaussdb_functions_result[0].cells = {'has_gaussdb_functions': False}
        
        gaussdb_views_result = [MagicMock()]
        gaussdb_views_result[0].cells = {'has_gaussdb_views': False}
        
        mogdb_hypopg_result = [MagicMock()]
        mogdb_hypopg_result[0].cells = {'has_mogdb_hypopg': False}
        
        mogdb_settings_result = [MagicMock()]
        mogdb_settings_result[0].cells = {'has_mogdb_settings': False}

        # Set up side effects for detect_database_type calls only
        mock_sql_driver.execute_query.side_effect = [
            version_result,  # First call for detect_database_type version
            gaussdb_tables_result,  # GaussDB table check
            gaussdb_functions_result,  # GaussDB function check
            gaussdb_views_result,  # GaussDB view check
            mogdb_hypopg_result,  # MogDB hypopg check
            mogdb_settings_result,  # MogDB settings check
        ]

        # Mock get_database_version to avoid additional query complexity
        with patch('postgres_mcp.sql.database_detection.get_database_version') as mock_get_version:
            mock_get_version.return_value = ('PostgreSQL 13.2 on x86_64-pc-linux-gnu', '13.2')
            
            info = await get_database_info(mock_sql_driver)

        assert info['type'] == DatabaseType.POSTGRESQL
        assert info['version_string'] == 'PostgreSQL 13.2 on x86_64-pc-linux-gnu'
        assert info['version_number'] == '13.2'
        assert info['is_postgresql'] is True
        assert info['is_gaussdb'] is False

    def test_extract_version_number_postgresql(self):
        """Test version number extraction from PostgreSQL version string."""
        version_string = "PostgreSQL 13.2 on x86_64-pc-linux-gnu"
        result = _extract_version_number(version_string)
        assert result == "13.2"

    def test_extract_version_number_gaussdb(self):
        """Test version number extraction from GaussDB version string."""
        version_string = "GaussDB 8.1.0 on x86_64-linux-gnu"
        result = _extract_version_number(version_string)
        assert result == "8.1.0"

    def test_extract_version_number_mogdb(self):
        """Test version number extraction from MogDB version string."""
        version_string = "(MogDB 5.0.0 build 503a9ef7) compiled at 2023-06-26 16:30:46 commit 0 last mr 1804  on aarch64-unknown-linux-gnu, compiled by g++ (GCC) 7.3.0, 64-bit"
        result = _extract_version_number(version_string)
        assert result == "5.0.0"

    def test_extract_version_number_opengauss(self):
        """Test version number extraction from openGauss version string."""
        version_string = "openGauss 3.1.0 on x86_64-linux-gnu"
        result = _extract_version_number(version_string)
        assert result == "3.1.0"

    def test_extract_version_number_generic(self):
        """Test version number extraction from generic version string."""
        version_string = "Some Database 12.5.3 with extra info"
        result = _extract_version_number(version_string)
        assert result == "12.5.3"

    def test_extract_version_number_fallback(self):
        """Test version number extraction fallback behavior."""
        version_string = "Database without clear version pattern 15"
        result = _extract_version_number(version_string)
        assert result == "15"

    def test_extract_version_number_unknown(self):
        """Test version number extraction when no pattern matches."""
        version_string = "Database with no version numbers"
        result = _extract_version_number(version_string)
        assert result == "unknown"


class TestSqlDriverDatabaseDetection:
    """Test database detection integration with SqlDriver."""

    @pytest.fixture
    def mock_connection_pool(self):
        """Create a mock connection pool."""
        pool = MagicMock()
        pool.pool_connect = AsyncMock()
        return pool

    @pytest.fixture
    def sql_driver_with_pool(self, mock_connection_pool):
        """Create SqlDriver with mock connection pool."""
        driver = SqlDriver(conn=mock_connection_pool)
        driver.is_pool = True
        return driver

    @pytest.mark.asyncio
    async def test_sql_driver_initialize_database_info(self, sql_driver_with_pool):
        """Test SqlDriver database info initialization."""
        # Mock the execute_query method to return PostgreSQL version
        async def mock_execute_query(query, force_readonly=False, skip_db_init=False):
            if "SELECT version()" in query:
                mock_result = [MagicMock()]
                mock_result[0].cells = {'version': 'PostgreSQL 13.2 on x86_64-pc-linux-gnu'}
                return mock_result
            elif any(check in query for check in ["has_gaussdb_tables", "has_gaussdb_functions", "has_gaussdb_views"]):
                mock_result = [MagicMock()]
                # Return False for any GaussDB check
                if "has_gaussdb_tables" in query:
                    mock_result[0].cells = {'has_gaussdb_tables': False}
                elif "has_gaussdb_functions" in query:
                    mock_result[0].cells = {'has_gaussdb_functions': False}
                else:
                    mock_result[0].cells = {'has_gaussdb_views': False}
                return mock_result
            elif "server_version_num" in query:
                mock_result = [MagicMock()]
                mock_result[0].cells = {'version_num': '130002'}
                return mock_result
            return None

        sql_driver_with_pool.execute_query = AsyncMock(side_effect=mock_execute_query)

        # Initialize database info
        await sql_driver_with_pool.initialize_database_info()

        assert sql_driver_with_pool.db_type == DatabaseType.POSTGRESQL
        assert sql_driver_with_pool.db_version == "13.2"
        assert sql_driver_with_pool._db_info_initialized is True

    @pytest.mark.asyncio
    async def test_sql_driver_get_database_type(self, sql_driver_with_pool):
        """Test SqlDriver get_database_type method."""
        # Mock the execute_query method
        async def mock_execute_query(query, force_readonly=False, skip_db_init=False):
            mock_result = [MagicMock()]
            mock_result[0].cells = {'version': 'GaussDB 8.1.0 on x86_64-linux-gnu'}
            return mock_result

        sql_driver_with_pool.execute_query = AsyncMock(side_effect=mock_execute_query)

        db_type = await sql_driver_with_pool.get_database_type()
        assert db_type == DatabaseType.GAUSSDB

    @pytest.mark.asyncio
    async def test_sql_driver_is_gaussdb(self, sql_driver_with_pool):
        """Test SqlDriver is_gaussdb method."""
        # Mock the execute_query method to return GaussDB
        async def mock_execute_query(query, force_readonly=False, skip_db_init=False):
            mock_result = [MagicMock()]
            mock_result[0].cells = {'version': 'GaussDB 8.1.0 on x86_64-linux-gnu'}
            return mock_result

        sql_driver_with_pool.execute_query = AsyncMock(side_effect=mock_execute_query)

        is_gaussdb = await sql_driver_with_pool.is_gaussdb()
        assert is_gaussdb is True

    @pytest.mark.asyncio
    async def test_sql_driver_is_postgresql(self, sql_driver_with_pool):
        """Test SqlDriver is_postgresql method."""
        # Mock the execute_query method to return PostgreSQL
        async def mock_execute_query(query, force_readonly=False, skip_db_init=False):
            if "SELECT version()" in query:
                mock_result = [MagicMock()]
                mock_result[0].cells = {'version': 'PostgreSQL 13.2 on x86_64-pc-linux-gnu'}
                return mock_result
            elif any(check in query for check in ["has_gaussdb_tables", "has_gaussdb_functions", "has_gaussdb_views"]):
                mock_result = [MagicMock()]
                # Return False for any GaussDB check
                if "has_gaussdb_tables" in query:
                    mock_result[0].cells = {'has_gaussdb_tables': False}
                elif "has_gaussdb_functions" in query:
                    mock_result[0].cells = {'has_gaussdb_functions': False}
                else:
                    mock_result[0].cells = {'has_gaussdb_views': False}
                return mock_result
            return None

        sql_driver_with_pool.execute_query = AsyncMock(side_effect=mock_execute_query)

        is_postgresql = await sql_driver_with_pool.is_postgresql()
        assert is_postgresql is True

    @pytest.mark.asyncio
    async def test_sql_driver_error_handling(self, sql_driver_with_pool):
        """Test SqlDriver error handling during database detection."""
        # Mock execute_query to raise an exception
        sql_driver_with_pool.execute_query = AsyncMock(side_effect=Exception("Connection failed"))

        # Should not raise exception, but set defaults
        await sql_driver_with_pool.initialize_database_info()

        assert sql_driver_with_pool.db_type == DatabaseType.POSTGRESQL
        assert sql_driver_with_pool.db_version == "unknown"
        assert sql_driver_with_pool._db_info_initialized is True
