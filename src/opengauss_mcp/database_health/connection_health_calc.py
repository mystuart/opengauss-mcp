import logging
from dataclasses import dataclass
from typing import LiteralString
from typing import cast

from ..sql import SqlDriver

logger = logging.getLogger(__name__)


@dataclass
class ConnectionHealthMetrics:
    total_connections: int
    idle_connections: int
    max_total_connections: int
    max_idle_connections: int
    is_total_connections_healthy: bool
    is_idle_connections_healthy: bool

    @property
    def is_healthy(self) -> bool:
        return self.is_total_connections_healthy and self.is_idle_connections_healthy


class ConnectionHealthCalc:
    def __init__(
        self,
        sql_driver: SqlDriver,
        max_total_connections: int = 500,
        max_idle_connections: int = 100,
    ):
        self.sql_driver = sql_driver
        self.max_total_connections = max_total_connections
        self.max_idle_connections = max_idle_connections

    async def total_connections_check(self) -> str:
        """Check if total number of connections is within healthy limits."""
        total = await self._get_total_connections()

        if total <= self.max_total_connections:
            return f"Total connections healthy: {total}"
        return f"High number of connections: {total} (max: {self.max_total_connections})"

    async def idle_connections_check(self) -> str:
        """Check if number of idle connections is within healthy limits."""
        idle = await self._get_idle_connections()

        if idle <= self.max_idle_connections:
            return f"Idle connections healthy: {idle}"
        return f"High number of idle connections: {idle} (max: {self.max_idle_connections})"

    async def connection_health_check(self) -> str:
        """Run all connection health checks and return combined results."""
        total = await self._get_total_connections()
        idle = await self._get_idle_connections()

        if total > self.max_total_connections:
            return f"High number of connections: {total}"
        elif idle > self.max_idle_connections:
            return f"High number of connections idle in transaction: {idle}"
        else:
            return f"Connections healthy: {total} total, {idle} idle"

    async def _get_total_connections(self) -> int:
        """Get the total number of database connections."""
        result = await self.sql_driver.execute_query("""
            SELECT COUNT(*) as count
            FROM pg_stat_activity
        """)
        result_list = [dict(x.cells) for x in result] if result else []
        return result_list[0]["count"] if result_list else 0

    async def _get_idle_connections(self) -> int:
        """Get the number of connections that are idle in transaction."""
        result = await self.sql_driver.execute_query("""
            SELECT COUNT(*) as count
            FROM pg_stat_activity
            WHERE state = 'idle in transaction'
        """)
        result_list = [dict(x.cells) for x in result] if result else []
        return result_list[0]["count"] if result_list else 0

    async def get_detailed_session_info(self, include_idle: bool = True) -> str:
        """Get detailed session information for active connections.

        Args:
            include_idle: Whether to include idle connections in the results

        Returns:
            A string with detailed session information or error message
        """
        try:
            idle_filter = "" if include_idle else "AND state NOT IN ('idle', 'idle in transaction')"
            query = f"""
            SELECT
                pid,
                datname as database,
                usename as username,
                application_name,
                client_addr,
                client_hostname,
                client_port,
                backend_start,
                xact_start,
                query_start,
                state_change,
                waiting,
                state,
                query
            FROM pg_stat_activity
            WHERE 1=1 {idle_filter}
            ORDER BY
                CASE
                    WHEN state IN ('active', 'waiting') THEN 1
                    ELSE 2
                END,
                query_start DESC NULLS LAST
            LIMIT 50
            """
            
            result = await self.sql_driver.execute_query(query)
            sessions = [dict(row.cells) for row in result] if result else []
            
            if not sessions:
                return "No active sessions found."
            
            # Format results
            result_text = [f"Active sessions (showing {len(sessions)}):"]
            for session in sessions:
                result_text.append(f"\nSession ID: {session.get('sessionid', session.get('pid', 'N/A'))}")
                result_text.append(f"  Database: {session.get('database', 'N/A')}")
                result_text.append(f"  User: {session.get('username', 'N/A')}")
                result_text.append(f"  Application: {session.get('application_name', 'N/A')}")
                result_text.append(f"  Client: {session.get('client_addr', 'N/A')}")
                result_text.append(f"  State: {session.get('state', 'N/A')}")
                result_text.append(f"  Waiting: {'Yes' if session.get('waiting') else 'No'}")
                
                # Add timing information
                if session.get('query_start'):
                    result_text.append(f"  Query started: {session['query_start']}")
                if session.get('backend_start'):
                    result_text.append(f"  Backend started: {session['backend_start']}")
                
                # Add query snippet (truncated)
                query = session.get('query', 'N/A')
                if query != 'N/A' and len(query) > 100:
                    query = query[:100] + "..."
                result_text.append(f"  Query: {query}")
            
            return "\n".join(result_text)
        except Exception as e:
            logger.error(f"Error getting detailed session info: {e}")
            return f"Error getting detailed session info: {e}"

    async def get_long_running_queries(self, threshold_minutes: int = 3) -> str:
        """Get queries that have been running for longer than the threshold.

        Args:
            threshold_minutes: Threshold in minutes for considering a query as long-running

        Returns:
            A string with long-running queries or error message
        """
        try:
            query = cast(
                LiteralString,
                f"""
            SELECT
                pid,
                datname as database,
                usename as username,
                application_name,
                client_addr,
                state,
                query_start,
                xact_start,
                backend_start,
                query,
                -- Calculate duration in minutes
                EXTRACT(EPOCH FROM (NOW() - query_start)) / 60 as query_duration_minutes,
                EXTRACT(EPOCH FROM (NOW() - xact_start)) / 60 as xact_duration_minutes
            FROM pg_stat_activity
            WHERE state = 'active'
            AND query_start < NOW() - INTERVAL '{threshold_minutes} minutes'
            ORDER BY query_start
            LIMIT 20
            """
            )
            
            result = await self.sql_driver.execute_query(query)
            queries = [dict(row.cells) for row in result] if result else []
            
            if not queries:
                return f"No queries found running longer than {threshold_minutes} minutes."
            
            # Format results
            result_text = [f"Long-running queries (threshold: {threshold_minutes} minutes):"]
            for query_info in queries:
                session_id = query_info.get('sessionid', query_info.get('pid', 'N/A'))
                query_duration = query_info.get('query_duration_minutes', 0)
                xact_duration = query_info.get('xact_duration_minutes', 0)
                
                result_text.append(f"\nSession ID: {session_id}")
                result_text.append(f"  Database: {query_info.get('database', 'N/A')}")
                result_text.append(f"  User: {query_info.get('username', 'N/A')}")
                result_text.append(f"  Application: {query_info.get('application_name', 'N/A')}")
                result_text.append(f"  Query duration: {query_duration:.2f} minutes")
                result_text.append(f"  Transaction duration: {xact_duration:.2f} minutes")
                
                # Add query snippet (truncated)
                query = query_info.get('query', 'N/A')
                if query != 'N/A' and len(query) > 150:
                    query = query[:150] + "..."
                result_text.append(f"  Query: {query}")
            
            return "\n".join(result_text)
        except Exception as e:
            logger.error(f"Error getting long-running queries: {e}")
            return f"Error getting long-running queries: {e}"

    async def get_blocked_queries(self) -> str:
        """Get information about blocked and blocking queries.

        Returns:
            A string with blocked queries information or error message
        """
        try:
            query = """
            SELECT
                blocked.pid as blocked_pid,
                blocked.usename as blocked_user,
                blocked.application_name as blocked_application,
                blocked.state as blocked_state,
                blocked.query as blocked_query,
                blocked.waiting,
                blocking.pid as blocking_pid,
                blocking.usename as blocking_user,
                blocking.application_name as blocking_application,
                blocking.state as blocking_state,
                blocking.query as blocking_query,
                blocked.query_start as blocked_query_start,
                blocking.query_start as blocking_query_start
            FROM pg_stat_activity blocked
            JOIN pg_stat_activity blocking ON blocked.waiting AND blocking.pid < pg_backend_pid()
            ORDER BY blocked.query_start
            LIMIT 20
            """
            
            result = await self.sql_driver.execute_query(query)
            blocked_queries = [dict(row.cells) for row in result] if result else []
            
            if not blocked_queries:
                return "No blocked queries found."
            
            # Format results
            result_text = ["Blocked queries:"]
            for bq in blocked_queries:
                blocked_id = bq.get('blocked_sessionid', bq.get('blocked_pid', 'N/A'))
                blocking_id = bq.get('blocking_sessionid', bq.get('blocking_pid', 'N/A'))
                
                result_text.append(f"\nBlocked Session: {blocked_id}")
                result_text.append(f"  User: {bq.get('blocked_user', 'N/A')}")
                result_text.append(f"  Application: {bq.get('blocked_application', 'N/A')}")
                result_text.append(f"  State: {bq.get('blocked_state', 'N/A')}")
                result_text.append(f"  Query started: {bq.get('blocked_query_start', 'N/A')}")
                
                # Add blocked query snippet (truncated)
                query = bq.get('blocked_query', 'N/A')
                if query != 'N/A' and len(query) > 100:
                    query = query[:100] + "..."
                result_text.append(f"  Query: {query}")
                
                result_text.append(f"\nBlocking Session: {blocking_id}")
                result_text.append(f"  User: {bq.get('blocking_user', 'N/A')}")
                result_text.append(f"  Application: {bq.get('blocking_application', 'N/A')}")
                result_text.append(f"  State: {bq.get('blocking_state', 'N/A')}")
                result_text.append(f"  Query started: {bq.get('blocking_query_start', 'N/A')}")
                
                # Add blocking query snippet (truncated)
                query = bq.get('blocking_query', 'N/A')
                if query != 'N/A' and len(query) > 100:
                    query = query[:100] + "..."
                result_text.append(f"  Query: {query}")
            
            return "\n".join(result_text)
        except Exception as e:
            logger.error(f"Error getting blocked queries: {e}")
            return f"Error getting blocked queries: {e}"
