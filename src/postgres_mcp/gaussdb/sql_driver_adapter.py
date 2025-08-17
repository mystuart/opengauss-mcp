"""
GaussDB SQL driver adapter for PostgreSQL compatibility.

This module provides the GaussDbSqlDriver class that adapts PostgreSQL queries
and functionality to work with GaussDB databases, handling differences in
system views, query syntax, and feature availability.
"""

import logging
import re
import time
from typing import Any, Dict, List, Optional, Union, Tuple
from typing_extensions import LiteralString

from ..sql.sql_driver import SqlDriver
from .config import GaussDbCompatibilityConfig
from .config_loader import ConfigLoader
from .error_handler import GaussDbErrorHandler, ErrorCategory

logger = logging.getLogger(__name__)


class QueryAdaptationCache:
    """
    Cache for adapted queries to improve performance.
    
    This class provides a simple LRU-style cache for storing adapted queries
    to avoid repeated regex processing for the same queries.
    """
    
    def __init__(self, max_size: int = 1000):
        """
        Initialize the query cache.
        
        Args:
            max_size: Maximum number of queries to cache
        """
        self.max_size = max_size
        self._cache: Dict[str, str] = {}
        self._access_times: Dict[str, float] = {}
    
    def get(self, original_query: str) -> Optional[str]:
        """
        Get adapted query from cache.
        
        Args:
            original_query: Original PostgreSQL query
            
        Returns:
            Adapted query if found in cache, None otherwise
        """
        if original_query in self._cache:
            self._access_times[original_query] = time.time()
            return self._cache[original_query]
        return None
    
    def put(self, original_query: str, adapted_query: str) -> None:
        """
        Store adapted query in cache.
        
        Args:
            original_query: Original PostgreSQL query
            adapted_query: Adapted GaussDB query
        """
        # If cache is full, remove least recently used item
        if len(self._cache) >= self.max_size:
            self._evict_lru()
        
        self._cache[original_query] = adapted_query
        self._access_times[original_query] = time.time()
    
    def _evict_lru(self) -> None:
        """Remove the least recently used item from cache."""
        if not self._access_times:
            return
        
        lru_key = min(self._access_times.keys(), key=lambda k: self._access_times[k])
        del self._cache[lru_key]
        del self._access_times[lru_key]
    
    def clear(self) -> None:
        """Clear all cached queries."""
        self._cache.clear()
        self._access_times.clear()
    
    def size(self) -> int:
        """Get current cache size."""
        return len(self._cache)


class GaussDbSqlDriver:
    """
    GaussDB SQL driver adapter that wraps a PostgreSQL SqlDriver.
    
    This class provides GaussDB compatibility by adapting PostgreSQL queries
    and handling GaussDB-specific differences in system views, syntax, and
    feature availability.
    """
    
    def __init__(self, base_driver: SqlDriver, config_loader: Optional[ConfigLoader] = None):
        """
        Initialize the GaussDB SQL driver adapter.
        
        Args:
            base_driver: The underlying PostgreSQL SqlDriver
            config_loader: Optional config loader, creates default if None
        """
        self.base_driver = base_driver
        self.config_loader = config_loader or ConfigLoader()
        self._compatibility_config: Optional[GaussDbCompatibilityConfig] = None
        self._error_handler: Optional[GaussDbErrorHandler] = None
        self._query_cache = QueryAdaptationCache()
        self._fallback_mode = False
        self._retry_count = 0
        self._max_retries = 3
        
        logger.info("GaussDbSqlDriver initialized")
    
    async def _ensure_config_loaded(self) -> None:
        """
        Ensure compatibility configuration is loaded.
        
        This method loads the appropriate configuration based on the
        detected GaussDB version.
        """
        if self._compatibility_config is not None:
            return
        
        try:
            # Get database version from base driver
            db_version = await self.base_driver.get_database_version()
            
            # Load configuration for this version
            self._compatibility_config = self.config_loader.load_config_for_version(db_version)
            
            # Initialize error handler with the loaded config
            self._error_handler = GaussDbErrorHandler(self._compatibility_config)
            
            logger.info(f"Loaded GaussDB compatibility config for version {db_version}")
            
        except Exception as e:
            logger.warning(f"Failed to load GaussDB config, using default: {e}")
            # Create minimal default config
            self._compatibility_config = GaussDbCompatibilityConfig(version="unknown")
            self._error_handler = GaussDbErrorHandler(self._compatibility_config)
    
    @property
    def compatibility_config(self) -> Optional[GaussDbCompatibilityConfig]:
        """Get the current compatibility configuration."""
        return self._compatibility_config
    
    async def adapt_query(self, query: str) -> str:
        """
        Adapt a PostgreSQL query for GaussDB compatibility.
        
        This method applies various transformation rules to convert PostgreSQL
        queries to GaussDB-compatible format, including system view mappings
        and syntax adaptations.
        
        Args:
            query: Original PostgreSQL query
            
        Returns:
            Adapted query for GaussDB
        """
        # Check cache first
        cached_result = self._query_cache.get(query)
        if cached_result is not None:
            logger.debug("Using cached adapted query")
            return cached_result
        
        # Ensure configuration is loaded
        await self._ensure_config_loaded()
        
        if not self._compatibility_config:
            logger.warning("No compatibility config available, returning original query")
            return query
        
        adapted_query = query
        
        try:
            # Apply system view mappings
            adapted_query = self._adapt_system_views(adapted_query)
            
            # Apply query adaptation rules
            adapted_query = self._apply_query_adaptations(adapted_query)
            
            # Cache the result
            self._query_cache.put(query, adapted_query)
            
            if adapted_query != query:
                logger.debug(f"Query adapted: {query[:100]}... -> {adapted_query[:100]}...")
            
            return adapted_query
            
        except Exception as e:
            logger.error(f"Error adapting query: {e}")
            # Return original query as fallback
            return query
    
    def _adapt_system_views(self, query: str) -> str:
        """
        Adapt PostgreSQL system views to GaussDB equivalents.
        
        Args:
            query: Query to adapt
            
        Returns:
            Query with adapted system views
        """
        if not self._compatibility_config:
            return query
        
        adapted_query = query
        
        # Apply system view mappings
        for pg_view, mapping in self._compatibility_config.system_views.items():
            if pg_view in adapted_query:
                # Simple view name replacement
                if mapping.gaussdb_view != pg_view:
                    adapted_query = adapted_query.replace(pg_view, mapping.gaussdb_view)
                
                # Apply column mappings if needed
                if mapping.column_mappings:
                    for pg_col, gaussdb_col in mapping.column_mappings.items():
                        if pg_col != gaussdb_col:
                            # Use word boundaries to avoid partial matches
                            pattern = r'\b' + re.escape(pg_col) + r'\b'
                            adapted_query = re.sub(pattern, gaussdb_col, adapted_query)
        
        return adapted_query
    
    def _apply_query_adaptations(self, query: str) -> str:
        """
        Apply query adaptation rules to transform PostgreSQL syntax.
        
        Args:
            query: Query to adapt
            
        Returns:
            Query with applied adaptations
        """
        if not self._compatibility_config:
            return query
        
        adapted_query = query
        
        # Apply adaptation rules in priority order
        for rule in self._compatibility_config.get_query_adaptations_by_priority():
            try:
                # Check if conditions are met (if any)
                if rule.conditions and not self._check_rule_conditions(rule.conditions, adapted_query):
                    continue
                
                # Apply the transformation
                if rule.pattern and rule.replacement is not None:
                    adapted_query = re.sub(rule.pattern, rule.replacement, adapted_query, flags=re.IGNORECASE)
                
            except re.error as e:
                logger.warning(f"Invalid regex pattern in rule '{rule.name}': {e}")
                continue
            except Exception as e:
                logger.warning(f"Error applying adaptation rule '{rule.name}': {e}")
                continue
        
        return adapted_query
    
    def _check_rule_conditions(self, conditions: Dict[str, Any], query: str) -> bool:
        """
        Check if rule conditions are satisfied.
        
        Args:
            conditions: Rule conditions to check
            query: Query to check against
            
        Returns:
            True if conditions are satisfied, False otherwise
        """
        # Simple condition checking - can be extended as needed
        for condition_type, condition_value in conditions.items():
            if condition_type == "contains":
                if condition_value not in query:
                    return False
            elif condition_type == "not_contains":
                if condition_value in query:
                    return False
            elif condition_type == "regex_match":
                if not re.search(condition_value, query, re.IGNORECASE):
                    return False
        
        return True
    
    async def execute_query(
        self,
        query: LiteralString,
        params: Optional[List[Any]] = None,
        force_readonly: bool = False,
        skip_adaptation: bool = False,
        retry_count: int = 0,
    ) -> Optional[List[SqlDriver.RowResult]]:
        """
        Execute a query with GaussDB adaptation and enhanced error handling.
        
        This method adapts the query for GaussDB compatibility and then
        executes it using the base driver, with comprehensive fallback 
        handling and retry logic for transient failures.
        
        Args:
            query: SQL query to execute
            params: Query parameters
            force_readonly: Whether to enforce read-only mode
            skip_adaptation: Skip query adaptation (for internal use)
            retry_count: Current retry attempt (for internal use)
            
        Returns:
            List of RowResult objects or None on error
        """
        context = {
            "query": query,
            "operation": "execute_query",
            "retry_count": retry_count
        }
        
        try:
            # Ensure configuration and error handler are loaded
            await self._ensure_config_loaded()
            
            # Adapt query unless skipped or in fallback mode
            if not skip_adaptation and not self._fallback_mode:
                adapted_query = await self.adapt_query(query)
                context["adapted"] = True
            else:
                adapted_query = query
                context["adapted"] = False
            
            # Execute the query
            result = await self.base_driver.execute_query(
                adapted_query, params, force_readonly
            )
            
            # Reset retry count on success
            self._retry_count = 0
            return result
            
        except Exception as e:
            return await self._handle_query_error(e, query, params, force_readonly, 
                                                skip_adaptation, retry_count, context)
    
    async def _handle_query_error(
        self,
        error: Exception,
        query: LiteralString,
        params: Optional[List[Any]],
        force_readonly: bool,
        skip_adaptation: bool,
        retry_count: int,
        context: Dict[str, Any]
    ) -> Optional[List[SqlDriver.RowResult]]:
        """
        Handle query execution errors with fallback and retry logic.
        
        Args:
            error: The exception that occurred
            query: Original query
            params: Query parameters
            force_readonly: Read-only flag
            skip_adaptation: Skip adaptation flag
            retry_count: Current retry count
            context: Execution context
            
        Returns:
            Query results or raises exception
        """
        if not self._error_handler:
            # No error handler available, re-raise original error
            raise error
        
        # Get error information
        user_message, error_category, suggested_action = self._error_handler.handle_error(error, context)
        
        logger.error(f"Query execution error: {user_message}")
        if suggested_action:
            logger.info(f"Suggested action: {suggested_action}")
        
        # Try fallback strategies based on error type
        
        # Strategy 1: Fallback to original query if adaptation was attempted
        if (not skip_adaptation and not self._fallback_mode and 
            self._error_handler.should_fallback_to_postgresql(error)):
            
            logger.info("Attempting fallback with original PostgreSQL query")
            try:
                return await self.base_driver.execute_query(query, params, force_readonly)
            except Exception as fallback_error:
                logger.warning(f"Fallback query also failed: {fallback_error}")
                # Continue to other strategies
        
        # Strategy 2: Retry for transient errors
        if (self._error_handler.is_retryable_error(error) and 
            retry_count < self._max_retries):
            
            retry_delay = min(2 ** retry_count, 10)  # Exponential backoff, max 10 seconds
            logger.info(f"Retrying query in {retry_delay} seconds (attempt {retry_count + 1}/{self._max_retries})")
            
            # Simple delay simulation (in real implementation, you'd use asyncio.sleep)
            import asyncio
            await asyncio.sleep(retry_delay)
            
            return await self.execute_query(query, params, force_readonly, skip_adaptation, retry_count + 1)
        
        # Strategy 3: Enable fallback mode for future queries if this looks like a systematic issue
        if (error_category in [ErrorCategory.FEATURE_NOT_SUPPORTED, ErrorCategory.SYNTAX] and 
            not self._fallback_mode):
            
            logger.warning("Enabling fallback mode due to repeated compatibility issues")
            self.enable_fallback_mode()
        
        # Strategy 4: Provide enhanced error message
        enhanced_error = self._create_enhanced_error(error, user_message, suggested_action, context)
        raise enhanced_error
    
    def _create_enhanced_error(
        self, 
        original_error: Exception, 
        user_message: str, 
        suggested_action: Optional[str],
        context: Dict[str, Any]
    ) -> Exception:
        """
        Create an enhanced error with additional context and suggestions.
        
        Args:
            original_error: Original exception
            user_message: User-friendly error message
            suggested_action: Suggested action if available
            context: Execution context
            
        Returns:
            Enhanced exception
        """
        error_parts = [user_message]
        
        if suggested_action:
            error_parts.append(f"Suggestions: {suggested_action}")
        
        if context.get("adapted"):
            error_parts.append("Note: Query was adapted for GaussDB compatibility")
        
        enhanced_message = "\n".join(error_parts)
        
        # Create new exception with enhanced message but preserve original type
        enhanced_error = type(original_error)(enhanced_message)
        enhanced_error.__cause__ = original_error
        
        return enhanced_error
    
    async def get_database_type(self):
        """Get database type from base driver."""
        return await self.base_driver.get_database_type()
    
    async def get_database_version(self) -> str:
        """Get database version from base driver."""
        return await self.base_driver.get_database_version()
    
    async def is_gaussdb(self) -> bool:
        """Check if connected database is GaussDB."""
        return await self.base_driver.is_gaussdb()
    
    async def is_postgresql(self) -> bool:
        """Check if connected database is PostgreSQL."""
        return await self.base_driver.is_postgresql()
    
    def connect(self):
        """Connect using base driver."""
        return self.base_driver.connect()
    
    async def initialize_database_info(self) -> None:
        """Initialize database info using base driver."""
        await self.base_driver.initialize_database_info()
        # Ensure our config is loaded after database info is available
        await self._ensure_config_loaded()
    
    def enable_fallback_mode(self) -> None:
        """
        Enable fallback mode.
        
        In fallback mode, queries are not adapted and are executed directly
        against the database. This can be useful when adaptation is causing
        issues or for debugging purposes.
        """
        self._fallback_mode = True
        logger.info("GaussDB adapter fallback mode enabled")
    
    def disable_fallback_mode(self) -> None:
        """Disable fallback mode and resume normal adaptation."""
        self._fallback_mode = False
        logger.info("GaussDB adapter fallback mode disabled")
    
    def is_fallback_mode(self) -> bool:
        """Check if fallback mode is enabled."""
        return self._fallback_mode
    
    def clear_query_cache(self) -> None:
        """Clear the query adaptation cache."""
        self._query_cache.clear()
        logger.info("Query adaptation cache cleared")
    
    def get_cache_stats(self) -> Dict[str, int]:
        """
        Get query cache statistics.
        
        Returns:
            Dictionary with cache statistics
        """
        return {
            "cache_size": self._query_cache.size(),
            "max_size": self._query_cache.max_size
        }
    
    async def test_feature_support(self, feature: str) -> bool:
        """
        Test if a specific feature is supported in the current GaussDB version.
        
        Args:
            feature: Feature name to test
            
        Returns:
            True if feature is supported, False otherwise
        """
        await self._ensure_config_loaded()
        
        if not self._compatibility_config:
            return False
        
        return self._compatibility_config.is_feature_supported(feature)
    
    async def get_error_message(self, error_key: str, default: str = "") -> str:
        """
        Get a user-friendly error message for a specific error.
        
        Args:
            error_key: Error key to look up
            default: Default message if key not found
            
        Returns:
            User-friendly error message
        """
        await self._ensure_config_loaded()
        
        if not self._compatibility_config:
            return default
        
        return self._compatibility_config.get_error_message(error_key, default)
    
    async def execute_query_with_fallback(
        self,
        query: LiteralString,
        params: Optional[List[Any]] = None,
        force_readonly: bool = False,
    ) -> Optional[List[SqlDriver.RowResult]]:
        """
        Execute query with automatic fallback to PostgreSQL compatibility.
        
        This method first tries the adapted query, and if it fails with
        compatibility issues, automatically falls back to the original query.
        
        Args:
            query: SQL query to execute
            params: Query parameters
            force_readonly: Whether to enforce read-only mode
            
        Returns:
            List of RowResult objects or None on error
        """
        try:
            # Try adapted query first
            return await self.execute_query(query, params, force_readonly, skip_adaptation=False)
        except Exception as e:
            if self._error_handler and self._error_handler.should_fallback_to_postgresql(e):
                logger.info("Automatic fallback to PostgreSQL-compatible query")
                return await self.execute_query(query, params, force_readonly, skip_adaptation=True)
            else:
                raise e
    
    def set_max_retries(self, max_retries: int) -> None:
        """
        Set the maximum number of retries for transient errors.
        
        Args:
            max_retries: Maximum retry attempts
        """
        self._max_retries = max(0, max_retries)
        logger.info(f"Max retries set to {self._max_retries}")
    
    def get_max_retries(self) -> int:
        """Get the current maximum retry count."""
        return self._max_retries
    
    def add_custom_error_mapping(self, error_pattern: str, user_message: str) -> None:
        """
        Add a custom error mapping to the error handler.
        
        Args:
            error_pattern: Error pattern to match
            user_message: User-friendly message to display
        """
        if self._error_handler:
            self._error_handler.add_custom_error_mapping(error_pattern, user_message)
        else:
            logger.warning("Error handler not initialized, cannot add custom mapping")
    
    def get_error_statistics(self) -> Dict[str, Any]:
        """
        Get comprehensive error handling statistics.
        
        Returns:
            Dictionary with error handling statistics
        """
        stats = {
            "fallback_mode": self._fallback_mode,
            "max_retries": self._max_retries,
            "cache_stats": self.get_cache_stats()
        }
        
        if self._error_handler:
            stats["error_handler_stats"] = self._error_handler.get_error_statistics()
        
        return stats
    
    async def validate_connection(self) -> Tuple[bool, Optional[str]]:
        """
        Validate the database connection and GaussDB compatibility.
        
        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            # Test basic connectivity
            result = await self.execute_query("SELECT 1 as test", skip_adaptation=True)
            if not result:
                return False, "Connection test failed: No result returned"
            
            # Test GaussDB detection
            is_gaussdb = await self.is_gaussdb()
            if not is_gaussdb:
                return False, "Connected database is not GaussDB"
            
            # Test version detection
            version = await self.get_database_version()
            if not version or version == "unknown":
                return False, "Could not determine GaussDB version"
            
            # Test configuration loading
            await self._ensure_config_loaded()
            if not self._compatibility_config:
                return False, "Could not load GaussDB compatibility configuration"
            
            logger.info(f"GaussDB connection validated successfully (version: {version})")
            return True, None
            
        except Exception as e:
            error_msg = f"Connection validation failed: {e}"
            if self._error_handler:
                formatted_error = self._error_handler.format_error_for_user(e)
                error_msg = f"Connection validation failed: {formatted_error}"
            
            logger.error(error_msg)
            return False, error_msg
    
    async def get_feature_support_info(self) -> Dict[str, Any]:
        """
        Get information about supported features in the current GaussDB version.
        
        Returns:
            Dictionary with feature support information
        """
        await self._ensure_config_loaded()
        
        if not self._compatibility_config:
            return {"error": "Configuration not available"}
        
        return {
            "version": self._compatibility_config.version,
            "major_version": self._compatibility_config.major_version,
            "minor_version": self._compatibility_config.minor_version,
            "features": {
                "hypopg": self._compatibility_config.supports_hypopg,
                "pg_stat_statements": self._compatibility_config.supports_pg_stat_statements,
                "explain_analyze": self._compatibility_config.supports_explain_analyze,
                "vacuum_analyze": self._compatibility_config.supports_vacuum_analyze,
                "replication_stats": self._compatibility_config.supports_replication_stats
            },
            "system_views_count": len(self._compatibility_config.system_views),
            "query_adaptations_count": len(self._compatibility_config.query_adaptations),
            "error_mappings_count": len(self._compatibility_config.error_mappings)
        }
    
    def __getattr__(self, name: str) -> Any:
        """
        Delegate unknown attributes to the base driver.
        
        This allows the adapter to act as a transparent wrapper for
        attributes and methods not explicitly overridden.
        
        Args:
            name: Attribute name
            
        Returns:
            Attribute value from base driver
        """
        return getattr(self.base_driver, name)