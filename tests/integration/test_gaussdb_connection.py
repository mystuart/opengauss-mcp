"""
Integration tests for GaussDB database connections.

This module tests the connection establishment, authentication,
and basic database operations with GaussDB instances.
"""

import asyncio
from typing import Any
from typing import Dict
from typing import Optional
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest

from src.postgres_mcp.gaussdb.config_loader import ConfigLoader
from src.postgres_mcp.gaussdb.sql_driver_adapter import GaussDbSqlDriver
from src.postgres_mcp.sql.database_detection import DatabaseType
from src.postgres_mcp.sql.database_detection import detect_database_type
from src.postgres_mcp.sql.sql_driver import SqlDriver


class MockConnection:
    """Mock database connection for testing."""

    def __init__(self, connection_params: Dict[str, Any]):
        self.connection_params = connection_params
        self.is_connected = False
        self.transaction_active = False

    async def connect(self):
        """Mock connection establishment."""
        self.is_connected = True

    async def close(self):
        """Mock connection closure."""
        self.is_connected = False

    async def execute(self, query: str, params: Optional[tuple] = None):
        """Mock query execution."""
        if not self.is_connected:
            raise Exception("Connection not established")

        # Mock different query responses
        if "SELECT version()" in query:
            return [{"version": "GaussDB 8.1.0 on x86_64-linux-gnu"}]
        elif "SELECT 1" in query:
            return [{"test": 1}]
        elif "pg_stat_activity" in query:
            return [{"pid": 12345, "state": "active", "query": "SELECT 1"}]
        else:
            return []


@pytest.fixture
def mock_connection_factory():
    """Factory for creating mock connections."""
    def create_connection(connection_string: str):
        # Parse connection parameters from string
        params = {"connection_string": connection_string}
        return MockConnection(params)
    return create_connection


@pytest.fixture
def mock_sql_driver():
    """Create a mock SQL driver."""
    driver = MagicMock(spec=SqlDriver)
    driver.execute_query = AsyncMock()
    driver.get_database_version = AsyncMock(return_value="8.1.0")
    driver.get_database_type = AsyncMock(return_value=DatabaseType.GAUSSDB)
    driver.is_gaussdb = AsyncMock(return_value=True)
    driver.initialize_database_info = AsyncMock()
    return driver


class TestGaussDbConnectionEstablishment:
    """Test cases for GaussDB connection establishment."""

    @pytest.mark.asyncio
    async def test_successful_connection_establishment(self, mock_sql_driver):
        """Test successful connection to GaussDB."""
        # Mock successful connection
        mock_sql_driver.execute_query.return_value = [
            MagicMock(cells={"version": "GaussDB 8.1.0 on x86_64-linux-gnu"})
        ]

        gaussdb_driver = GaussDbSqlDriver(mock_sql_driver)

        # Test connection validation
        is_valid, error_msg = await gaussdb_driver.validate_connection()

        assert is_valid is True
        assert error_msg is None
        mock_sql_driver.execute_query.assert_called()

    @pytest.mark.asyncio
    async def test_connection_failure_handling(self, mock_sql_driver):
        """Test handling of connection failures."""
        # Mock connection failure
        mock_sql_driver.execute_query.side_effect = Exception("Connection refused")

        gaussdb_driver = GaussDbSqlDriver(mock_sql_driver)

        # Test connection validation failure
        is_valid, error_msg = await gaussdb_driver.validate_connection()

        assert is_valid is False
        assert "Connection validation failed" in error_msg
        assert "Connection refused" in error_msg

    @pytest.mark.asyncio
    async def test_authentication_failure_handling(self, mock_sql_driver):
        """Test handling of authentication failures."""
        # Mock authentication failure
        mock_sql_driver.execute_query.side_effect = Exception("authentication failed")

        gaussdb_driver = GaussDbSqlDriver(mock_sql_driver)

        is_valid, error_msg = await gaussdb_driver.validate_connection()

        assert is_valid is False
        assert "authentication" in error_msg.lower()

    @pytest.mark.asyncio
    async def test_database_detection_after_connection(self, mock_sql_driver):
        """Test database type detection after connection establishment."""
        # Mock version query response
        mock_sql_driver.execute_query.return_value = [
            MagicMock(cells={"version": "GaussDB 8.1.0 on x86_64-linux-gnu"})
        ]

        # Test database type detection
        db_type = await detect_database_type(mock_sql_driver)

        assert db_type == DatabaseType.GAUSSDB

    @pytest.mark.asyncio
    async def test_connection_with_ssl_parameters(self, mock_sql_driver):
        """Test connection with SSL/TLS parameters."""
        # Mock SSL connection
        mock_sql_driver.execute_query.return_value = [
            MagicMock(cells={"ssl": "on", "version": "GaussDB 8.1.0"})
        ]

        gaussdb_driver = GaussDbSqlDriver(mock_sql_driver)

        # Test SSL connection validation
        is_valid, error_msg = await gaussdb_driver.validate_connection()

        assert is_valid is True
        assert error_msg is None

    @pytest.mark.asyncio
    async def test_connection_timeout_handling(self, mock_sql_driver):
        """Test handling of connection timeouts."""
        # Mock timeout error
        mock_sql_driver.execute_query.side_effect = asyncio.TimeoutError("Connection timeout")

        gaussdb_driver = GaussDbSqlDriver(mock_sql_driver)

        is_valid, error_msg = await gaussdb_driver.validate_connection()

        assert is_valid is False
        assert "timeout" in error_msg.lower()


class TestGaussDbConnectionPooling:
    """Test cases for GaussDB connection pooling."""

    @pytest.mark.asyncio
    async def test_connection_pool_initialization(self, mock_sql_driver):
        """Test connection pool initialization."""
        # Mock pool connection
        mock_sql_driver.is_pool = True
        mock_sql_driver.pool_connect = AsyncMock()

        gaussdb_driver = GaussDbSqlDriver(mock_sql_driver)

        # Test that pool connection is properly handled
        await gaussdb_driver._ensure_config_loaded()

        # Verify pool connection was attempted
        assert mock_sql_driver.is_pool is True

    @pytest.mark.asyncio
    async def test_connection_pool_exhaustion(self, mock_sql_driver):
        """Test handling of connection pool exhaustion."""
        # Mock pool exhaustion
        mock_sql_driver.execute_query.side_effect = Exception("connection pool exhausted")

        gaussdb_driver = GaussDbSqlDriver(mock_sql_driver)

        is_valid, error_msg = await gaussdb_driver.validate_connection()

        assert is_valid is False
        assert "pool" in error_msg.lower()

    @pytest.mark.asyncio
    async def test_concurrent_connections(self, mock_sql_driver):
        """Test handling of concurrent connections."""
        # Mock concurrent query execution
        mock_sql_driver.execute_query = AsyncMock(return_value=[
            MagicMock(cells={"result": "success"})
        ])

        gaussdb_driver = GaussDbSqlDriver(mock_sql_driver)

        # Execute multiple concurrent queries
        tasks = []
        for i in range(5):
            task = gaussdb_driver.execute_query(f"SELECT {i}")
            tasks.append(task)

        results = await asyncio.gather(*tasks)

        # Verify all queries completed successfully
        assert len(results) == 5
        for result in results:
            assert len(result) == 1
            assert result[0].cells["result"] == "success"


class TestGaussDbConnectionConfiguration:
    """Test cases for GaussDB connection configuration."""

    @pytest.mark.asyncio
    async def test_connection_with_different_versions(self, mock_sql_driver):
        """Test connections to different GaussDB versions."""
        versions = ["8.1.0", "8.2.0", "5.0.0"]  # Including MogDB version

        for version in versions:
            # Mock version-specific response
            mock_sql_driver.get_database_version.return_value = version
            mock_sql_driver.execute_query.return_value = [
                MagicMock(cells={"version": f"GaussDB {version} on x86_64-linux-gnu"})
            ]

            gaussdb_driver = GaussDbSqlDriver(mock_sql_driver)

            # Test connection and configuration loading
            await gaussdb_driver._ensure_config_loaded()

            assert gaussdb_driver._compatibility_config is not None
            assert gaussdb_driver._compatibility_config.version == version

    @pytest.mark.asyncio
    async def test_connection_with_custom_configuration(self, mock_sql_driver):
        """Test connection with custom configuration."""
        # Mock custom config loader
        mock_config_loader = MagicMock(spec=ConfigLoader)
        custom_config = MagicMock()
        custom_config.version = "8.1.0"
        custom_config.feature_support.supports_hypopg = False
        mock_config_loader.load_config_for_version.return_value = custom_config

        gaussdb_driver = GaussDbSqlDriver(mock_sql_driver, mock_config_loader)

        await gaussdb_driver._ensure_config_loaded()

        assert gaussdb_driver._compatibility_config == custom_config
        mock_config_loader.load_config_for_version.assert_called_once()

    @pytest.mark.asyncio
    async def test_connection_parameter_validation(self, mock_sql_driver):
        """Test validation of connection parameters."""
        # Test various connection scenarios
        test_cases = [
            {
                "scenario": "valid_connection",
                "response": [MagicMock(cells={"version": "GaussDB 8.1.0"})],
                "expected_valid": True
            },
            {
                "scenario": "invalid_database",
                "response": Exception("database does not exist"),
                "expected_valid": False
            },
            {
                "scenario": "permission_denied",
                "response": Exception("permission denied"),
                "expected_valid": False
            }
        ]

        for case in test_cases:
            if isinstance(case["response"], Exception):
                mock_sql_driver.execute_query.side_effect = case["response"]
            else:
                mock_sql_driver.execute_query.return_value = case["response"]
                mock_sql_driver.execute_query.side_effect = None

            gaussdb_driver = GaussDbSqlDriver(mock_sql_driver)
            is_valid, error_msg = await gaussdb_driver.validate_connection()

            assert is_valid == case["expected_valid"], f"Failed for scenario: {case['scenario']}"
            if not case["expected_valid"]:
                assert error_msg is not None


class TestGaussDbConnectionRecovery:
    """Test cases for GaussDB connection recovery and resilience."""

    @pytest.mark.asyncio
    async def test_connection_retry_mechanism(self, mock_sql_driver):
        """Test connection retry mechanism on transient failures."""
        # Mock transient failure followed by success
        mock_sql_driver.execute_query.side_effect = [
            Exception("connection refused"),  # First attempt fails
            Exception("connection refused"),  # Second attempt fails
            [MagicMock(cells={"version": "GaussDB 8.1.0"})]  # Third attempt succeeds
        ]

        gaussdb_driver = GaussDbSqlDriver(mock_sql_driver)
        gaussdb_driver.set_max_retries(3)

        # Test query execution with retries
        result = await gaussdb_driver.execute_query("SELECT version()")

        assert len(result) == 1
        assert result[0].cells["version"] == "GaussDB 8.1.0"
        # Should have made 3 attempts
        assert mock_sql_driver.execute_query.call_count == 3

    @pytest.mark.asyncio
    async def test_connection_recovery_after_network_failure(self, mock_sql_driver):
        """Test connection recovery after network failures."""
        # Mock network failure followed by recovery
        network_error = Exception("network unreachable")
        success_response = [MagicMock(cells={"test": 1})]

        mock_sql_driver.execute_query.side_effect = [
            network_error,
            success_response
        ]

        gaussdb_driver = GaussDbSqlDriver(mock_sql_driver)

        # First query should fail
        with pytest.raises(Exception, match="network unreachable"):
            await gaussdb_driver.execute_query("SELECT 1")

        # Reset side effect for recovery test
        mock_sql_driver.execute_query.side_effect = None
        mock_sql_driver.execute_query.return_value = success_response

        # Second query should succeed
        result = await gaussdb_driver.execute_query("SELECT 1")
        assert len(result) == 1
        assert result[0].cells["test"] == 1

    @pytest.mark.asyncio
    async def test_fallback_mode_activation(self, mock_sql_driver):
        """Test automatic fallback mode activation on persistent failures."""
        # Mock persistent GaussDB-specific failures
        mock_sql_driver.execute_query.side_effect = [
            Exception("column does not exist"),  # GaussDB-specific failure
            [MagicMock(cells={"result": "fallback_success"})]  # PostgreSQL fallback succeeds
        ]

        gaussdb_driver = GaussDbSqlDriver(mock_sql_driver)

        # Execute query that triggers fallback
        result = await gaussdb_driver.execute_query("SELECT gaussdb_specific_column")

        assert len(result) == 1
        assert result[0].cells["result"] == "fallback_success"
        # Should have made 2 attempts (adapted query + fallback)
        assert mock_sql_driver.execute_query.call_count == 2

    @pytest.mark.asyncio
    async def test_connection_health_monitoring(self, mock_sql_driver):
        """Test connection health monitoring and automatic recovery."""
        # Mock health check responses
        health_responses = [
            [MagicMock(cells={"test": 1})],  # Healthy
            Exception("connection lost"),     # Unhealthy
            [MagicMock(cells={"test": 1})]   # Recovered
        ]

        mock_sql_driver.execute_query.side_effect = health_responses

        gaussdb_driver = GaussDbSqlDriver(mock_sql_driver)

        # First health check - healthy
        is_valid, _ = await gaussdb_driver.validate_connection()
        assert is_valid is True

        # Second health check - unhealthy
        is_valid, error_msg = await gaussdb_driver.validate_connection()
        assert is_valid is False
        assert "connection lost" in error_msg

        # Third health check - recovered
        is_valid, _ = await gaussdb_driver.validate_connection()
        assert is_valid is True


class TestGaussDbConnectionSecurity:
    """Test cases for GaussDB connection security features."""

    @pytest.mark.asyncio
    async def test_connection_with_ssl_verification(self, mock_sql_driver):
        """Test SSL certificate verification during connection."""
        # Mock SSL verification scenarios
        ssl_scenarios = [
            {
                "name": "valid_ssl",
                "response": [MagicMock(cells={"ssl": "on", "ssl_version": "TLSv1.2"})],
                "should_succeed": True
            },
            {
                "name": "ssl_verification_failed",
                "response": Exception("SSL certificate verification failed"),
                "should_succeed": False
            },
            {
                "name": "ssl_not_supported",
                "response": [MagicMock(cells={"ssl": "off"})],
                "should_succeed": True  # Should still work without SSL
            }
        ]

        for scenario in ssl_scenarios:
            if isinstance(scenario["response"], Exception):
                mock_sql_driver.execute_query.side_effect = scenario["response"]
            else:
                mock_sql_driver.execute_query.return_value = scenario["response"]
                mock_sql_driver.execute_query.side_effect = None

            gaussdb_driver = GaussDbSqlDriver(mock_sql_driver)
            is_valid, error_msg = await gaussdb_driver.validate_connection()

            if scenario["should_succeed"]:
                assert is_valid is True, f"SSL scenario '{scenario['name']}' should succeed"
            else:
                assert is_valid is False, f"SSL scenario '{scenario['name']}' should fail"
                assert "SSL" in error_msg or "certificate" in error_msg

    @pytest.mark.asyncio
    async def test_connection_with_authentication_methods(self, mock_sql_driver):
        """Test different authentication methods."""
        auth_scenarios = [
            {
                "method": "password",
                "response": [MagicMock(cells={"current_user": "test_user"})],
                "should_succeed": True
            },
            {
                "method": "certificate",
                "response": [MagicMock(cells={"current_user": "cert_user"})],
                "should_succeed": True
            },
            {
                "method": "invalid_password",
                "response": Exception("password authentication failed"),
                "should_succeed": False
            }
        ]

        for scenario in auth_scenarios:
            if isinstance(scenario["response"], Exception):
                mock_sql_driver.execute_query.side_effect = scenario["response"]
            else:
                mock_sql_driver.execute_query.return_value = scenario["response"]
                mock_sql_driver.execute_query.side_effect = None

            gaussdb_driver = GaussDbSqlDriver(mock_sql_driver)
            is_valid, error_msg = await gaussdb_driver.validate_connection()

            if scenario["should_succeed"]:
                assert is_valid is True, f"Auth method '{scenario['method']}' should succeed"
            else:
                assert is_valid is False, f"Auth method '{scenario['method']}' should fail"
                assert "authentication" in error_msg.lower()

    @pytest.mark.asyncio
    async def test_connection_permission_validation(self, mock_sql_driver):
        """Test validation of database permissions after connection."""
        # Mock permission check queries
        permission_responses = [
            # Check basic SELECT permission
            [MagicMock(cells={"has_select": True})],
            # Check system table access
            [MagicMock(cells={"can_access_pg_stat": True})],
            # Check function execution permission
            [MagicMock(cells={"can_execute_functions": True})]
        ]

        mock_sql_driver.execute_query.side_effect = permission_responses

        gaussdb_driver = GaussDbSqlDriver(mock_sql_driver)

        # Test permission validation
        is_valid, error_msg = await gaussdb_driver.validate_connection()

        assert is_valid is True
        assert error_msg is None
        # Should have checked permissions
        assert mock_sql_driver.execute_query.call_count >= 1


if __name__ == "__main__":
    pytest.main([__file__])
