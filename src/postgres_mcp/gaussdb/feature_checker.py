"""
GaussDB feature availability checker.

This module provides the FeatureAvailabilityChecker class that checks
for the availability of specific features in GaussDB databases, including
hypothetical indexes, query statistics, and other PostgreSQL extensions.
"""

import logging
from typing import TYPE_CHECKING
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple

from typing_extensions import LiteralString

from .config import GaussDbCompatibilityConfig
from .error_handler import GaussDbErrorHandler

if TYPE_CHECKING:
    from .sql_driver_adapter import GaussDbSqlDriver

logger = logging.getLogger(__name__)


class FeatureAvailabilityChecker:
    """
    Checker for GaussDB feature availability and compatibility.
    
    This class provides methods to check if specific PostgreSQL features
    and extensions are available in the current GaussDB version, and
    provides appropriate fallback suggestions when features are not supported.
    """

    def __init__(self, sql_driver: "GaussDbSqlDriver"):
        """
        Initialize the feature availability checker.
        
        Args:
            sql_driver: GaussDbSqlDriver instance
        """
        self.sql_driver = sql_driver
        self._compatibility_config: Optional[GaussDbCompatibilityConfig] = None
        self._error_handler: Optional[GaussDbErrorHandler] = None
        self._feature_cache: Dict[str, bool] = {}
        self._checked_extensions: Dict[str, bool] = {}

        logger.info("FeatureAvailabilityChecker initialized")

    async def _ensure_config_loaded(self) -> None:
        """Ensure compatibility configuration is loaded."""
        if self._compatibility_config is not None:
            return

        # Get config from the GaussDB driver
        await self.sql_driver._ensure_config_loaded()
        self._compatibility_config = self.sql_driver.compatibility_config

        if self._compatibility_config:
            self._error_handler = GaussDbErrorHandler(self._compatibility_config)
            logger.debug("Feature checker configuration loaded")
        else:
            logger.warning("No GaussDB compatibility config available")

    async def check_hypopg_support(self) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Check if hypothetical indexes (hypopg) are supported in GaussDB.
        
        Returns:
            Tuple of (is_supported, error_message, suggested_alternative)
            - is_supported: True if hypopg is available and working
            - error_message: Error message if not supported
            - suggested_alternative: Alternative approach if not supported
        """
        await self._ensure_config_loaded()

        # Check cache first
        if "hypopg" in self._feature_cache:
            is_supported = self._feature_cache["hypopg"]
            if not is_supported:
                return False, self._get_hypopg_error_message(), self._get_hypopg_alternative()
            return True, None, None

        try:
            # First check configuration
            if self._compatibility_config and not self._compatibility_config.supports_hypopg:
                self._feature_cache["hypopg"] = False
                return False, self._get_hypopg_error_message(), self._get_hypopg_alternative()

            # Test if hypopg extension exists
            extension_check_query: LiteralString = """
                SELECT EXISTS (
                    SELECT 1 FROM pg_extension 
                    WHERE extname = 'hypopg'
                ) as has_hypopg
            """

            result = await self.sql_driver.execute_query(extension_check_query, skip_adaptation=True)

            if not result or not result[0].cells.get('has_hypopg'):
                self._feature_cache["hypopg"] = False
                return False, self._get_hypopg_error_message(), self._get_hypopg_alternative()

            # Test if hypopg functions are available and working
            test_queries = [
                "SELECT hypopg_reset()",
                "SELECT hypopg_create_index('btree_test_idx ON pg_class (oid)')",
                "SELECT hypopg_reset()"
            ]

            for test_query in test_queries:
                try:
                    await self.sql_driver.execute_query(test_query, skip_adaptation=True)
                except Exception as e:
                    logger.debug(f"hypopg test query failed: {test_query} - {e}")
                    self._feature_cache["hypopg"] = False
                    return False, self._get_hypopg_error_message(), self._get_hypopg_alternative()

            # All tests passed
            self._feature_cache["hypopg"] = True
            logger.info("hypopg extension is available and working")
            return True, None, None

        except Exception as e:
            logger.warning(f"Error checking hypopg support: {e}")
            self._feature_cache["hypopg"] = False
            return False, self._get_hypopg_error_message(), self._get_hypopg_alternative()

    def _get_hypopg_error_message(self) -> str:
        """Get user-friendly error message for missing hypopg support."""
        if self._compatibility_config:
            version = self._compatibility_config.version
            return (
                f"Hypothetical indexes (hypopg extension) are not supported in GaussDB {version}. "
                "This feature is required for index recommendation analysis with 'what-if' scenarios."
            )
        else:
            return (
                "Hypothetical indexes (hypopg extension) are not available in this GaussDB instance. "
                "This feature is required for advanced index analysis."
            )

    def _get_hypopg_alternative(self) -> str:
        """Get suggested alternative when hypopg is not supported."""
        return (
            "Consider these alternatives: "
            "1) Create actual test indexes in a development environment, "
            "2) Use PostgreSQL with hypopg extension for index analysis, "
            "3) Analyze query execution plans without hypothetical indexes to identify potential improvements."
        )

    async def check_pg_stat_statements_support(self) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Check if pg_stat_statements or equivalent is supported.
        
        Returns:
            Tuple of (is_supported, error_message, suggested_alternative)
        """
        await self._ensure_config_loaded()

        # Check cache first
        if "pg_stat_statements" in self._feature_cache:
            is_supported = self._feature_cache["pg_stat_statements"]
            if not is_supported:
                return False, self._get_pg_stat_statements_error(), self._get_pg_stat_statements_alternative()
            return True, None, None

        try:
            # Check configuration first
            if (self._compatibility_config and
                not self._compatibility_config.supports_pg_stat_statements):
                self._feature_cache["pg_stat_statements"] = False
                return False, self._get_pg_stat_statements_error(), self._get_pg_stat_statements_alternative()

            # Test if pg_stat_statements view exists and is accessible
            test_queries = [
                # Standard pg_stat_statements
                "SELECT COUNT(*) FROM pg_stat_statements LIMIT 1",
                # GaussDB might have alternative views
                "SELECT COUNT(*) FROM pg_stat_user_statements LIMIT 1",
                "SELECT COUNT(*) FROM dbe_perf.statement LIMIT 1"
            ]

            for test_query in test_queries:
                try:
                    result = await self.sql_driver.execute_query(test_query, skip_adaptation=True)
                    if result is not None:
                        self._feature_cache["pg_stat_statements"] = True
                        logger.info(f"Query statistics available via: {test_query}")
                        return True, None, None
                except Exception as e:
                    logger.debug(f"Query statistics test failed: {test_query} - {e}")
                    continue

            # None of the queries worked
            self._feature_cache["pg_stat_statements"] = False
            return False, self._get_pg_stat_statements_error(), self._get_pg_stat_statements_alternative()

        except Exception as e:
            logger.warning(f"Error checking pg_stat_statements support: {e}")
            self._feature_cache["pg_stat_statements"] = False
            return False, self._get_pg_stat_statements_error(), self._get_pg_stat_statements_alternative()

    def _get_pg_stat_statements_error(self) -> str:
        """Get error message for missing pg_stat_statements support."""
        return (
            "Query statistics (pg_stat_statements or equivalent) are not available. "
            "This feature is required for workload analysis and query performance monitoring."
        )

    def _get_pg_stat_statements_alternative(self) -> str:
        """Get alternative suggestions for pg_stat_statements."""
        return (
            "Consider these alternatives: "
            "1) Enable query statistics collection in GaussDB configuration, "
            "2) Use database logs for query analysis, "
            "3) Monitor queries manually during performance testing."
        )

    async def check_explain_analyze_support(self) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Check if EXPLAIN ANALYZE is supported.
        
        Returns:
            Tuple of (is_supported, error_message, suggested_alternative)
        """
        await self._ensure_config_loaded()

        # Check cache first
        if "explain_analyze" in self._feature_cache:
            is_supported = self._feature_cache["explain_analyze"]
            if not is_supported:
                return False, self._get_explain_analyze_error(), self._get_explain_analyze_alternative()
            return True, None, None

        try:
            # Test EXPLAIN ANALYZE with a simple query
            test_query = "EXPLAIN (ANALYZE, FORMAT JSON) SELECT 1"

            result = await self.sql_driver.execute_query(test_query, skip_adaptation=True)

            if result and result[0].cells.get("QUERY PLAN"):
                self._feature_cache["explain_analyze"] = True
                logger.info("EXPLAIN ANALYZE is supported")
                return True, None, None
            else:
                self._feature_cache["explain_analyze"] = False
                return False, self._get_explain_analyze_error(), self._get_explain_analyze_alternative()

        except Exception as e:
            logger.debug(f"EXPLAIN ANALYZE test failed: {e}")

            # Try fallback to basic EXPLAIN
            try:
                fallback_query = "EXPLAIN (FORMAT JSON) SELECT 1"
                result = await self.sql_driver.execute_query(fallback_query, skip_adaptation=True)

                if result:
                    # Basic EXPLAIN works, but ANALYZE might not
                    self._feature_cache["explain_analyze"] = False
                    return False, self._get_explain_analyze_error(), self._get_explain_analyze_alternative()

            except Exception as fallback_e:
                logger.warning(f"Even basic EXPLAIN failed: {fallback_e}")

            self._feature_cache["explain_analyze"] = False
            return False, self._get_explain_analyze_error(), self._get_explain_analyze_alternative()

    def _get_explain_analyze_error(self) -> str:
        """Get error message for missing EXPLAIN ANALYZE support."""
        return (
            "EXPLAIN ANALYZE is not supported in this GaussDB version. "
            "This feature provides actual execution statistics for query plans."
        )

    def _get_explain_analyze_alternative(self) -> str:
        """Get alternative suggestions for EXPLAIN ANALYZE."""
        return (
            "Use EXPLAIN (without ANALYZE) to get estimated query plans, "
            "or monitor query performance through database logs and system statistics."
        )

    async def check_extension_availability(self, extension_name: str) -> Tuple[bool, Optional[str]]:
        """
        Check if a specific PostgreSQL extension is available in GaussDB.
        
        Args:
            extension_name: Name of the extension to check
            
        Returns:
            Tuple of (is_available, error_message)
        """
        # Check cache first
        if extension_name in self._checked_extensions:
            is_available = self._checked_extensions[extension_name]
            if not is_available:
                return False, f"Extension '{extension_name}' is not available in this GaussDB instance"
            return True, None

        try:
            # Check if extension is installed
            extension_query: LiteralString = """
                SELECT EXISTS (
                    SELECT 1 FROM pg_extension 
                    WHERE extname = %s
                ) as has_extension
            """

            result = await self.sql_driver.execute_query(
                extension_query,
                params=[extension_name],
                skip_adaptation=True
            )

            if result and result[0].cells.get('has_extension'):
                self._checked_extensions[extension_name] = True
                logger.info(f"Extension '{extension_name}' is available")
                return True, None
            else:
                self._checked_extensions[extension_name] = False
                return False, f"Extension '{extension_name}' is not installed or available"

        except Exception as e:
            logger.warning(f"Error checking extension '{extension_name}': {e}")
            self._checked_extensions[extension_name] = False
            return False, f"Error checking extension '{extension_name}': {e}"

    async def get_comprehensive_feature_report(self) -> Dict[str, Any]:
        """
        Get a comprehensive report of feature availability.
        
        Returns:
            Dictionary with detailed feature availability information
        """
        await self._ensure_config_loaded()

        report = {
            "database_info": {
                "type": "gaussdb",
                "version": self._compatibility_config.version if self._compatibility_config else "unknown"
            },
            "core_features": {},
            "extensions": {},
            "recommendations": []
        }

        # Check core features
        core_features = [
            ("hypopg", self.check_hypopg_support),
            ("pg_stat_statements", self.check_pg_stat_statements_support),
            ("explain_analyze", self.check_explain_analyze_support)
        ]

        for feature_name, check_method in core_features:
            try:
                is_supported, error_msg, alternative = await check_method()
                report["core_features"][feature_name] = {
                    "supported": is_supported,
                    "error_message": error_msg,
                    "alternative": alternative
                }

                if not is_supported and alternative:
                    report["recommendations"].append(f"{feature_name}: {alternative}")

            except Exception as e:
                report["core_features"][feature_name] = {
                    "supported": False,
                    "error_message": f"Error checking feature: {e}",
                    "alternative": None
                }

        # Check common extensions
        common_extensions = [
            "hypopg", "pg_stat_statements", "btree_gin", "btree_gist",
            "pg_trgm", "uuid-ossp", "pgcrypto"
        ]

        for ext_name in common_extensions:
            try:
                is_available, error_msg = await self.check_extension_availability(ext_name)
                report["extensions"][ext_name] = {
                    "available": is_available,
                    "error_message": error_msg
                }
            except Exception as e:
                report["extensions"][ext_name] = {
                    "available": False,
                    "error_message": f"Error checking extension: {e}"
                }

        # Add general recommendations
        if not report["core_features"].get("hypopg", {}).get("supported", False):
            report["recommendations"].append(
                "Consider using PostgreSQL with hypopg extension for advanced index analysis"
            )

        if not report["core_features"].get("pg_stat_statements", {}).get("supported", False):
            report["recommendations"].append(
                "Enable query statistics collection for better workload analysis"
            )

        return report

    async def validate_required_features(self, required_features: List[str]) -> Tuple[bool, List[str]]:
        """
        Validate that all required features are available.
        
        Args:
            required_features: List of feature names that are required
            
        Returns:
            Tuple of (all_available, missing_features)
        """
        missing_features = []

        feature_checkers = {
            "hypopg": self.check_hypopg_support,
            "pg_stat_statements": self.check_pg_stat_statements_support,
            "explain_analyze": self.check_explain_analyze_support
        }

        for feature in required_features:
            if feature in feature_checkers:
                try:
                    is_supported, _, _ = await feature_checkers[feature]()
                    if not is_supported:
                        missing_features.append(feature)
                except Exception as e:
                    logger.error(f"Error checking required feature '{feature}': {e}")
                    missing_features.append(feature)
            else:
                # Check as extension
                try:
                    is_available, _ = await self.check_extension_availability(feature)
                    if not is_available:
                        missing_features.append(feature)
                except Exception as e:
                    logger.error(f"Error checking required extension '{feature}': {e}")
                    missing_features.append(feature)

        return len(missing_features) == 0, missing_features

    def clear_cache(self) -> None:
        """Clear the feature availability cache."""
        self._feature_cache.clear()
        self._checked_extensions.clear()
        logger.info("Feature availability cache cleared")

    def get_cache_info(self) -> Dict[str, Any]:
        """
        Get information about the current cache state.
        
        Returns:
            Dictionary with cache information
        """
        return {
            "cached_features": list(self._feature_cache.keys()),
            "cached_extensions": list(self._checked_extensions.keys()),
            "feature_cache_size": len(self._feature_cache),
            "extension_cache_size": len(self._checked_extensions)
        }


async def check_hypopg_installation_status(sql_driver: "GaussDbSqlDriver") -> Dict[str, Any]:
    """
    Check hypopg installation status with GaussDB compatibility.
    
    This function provides a comprehensive check of hypopg availability
    and installation status, with GaussDB-specific handling and suggestions.
    
    Args:
        sql_driver: GaussDbSqlDriver instance
        
    Returns:
        Dictionary with installation status information
    """
    checker = FeatureAvailabilityChecker(sql_driver)

    try:
        is_supported, error_msg, alternative = await checker.check_hypopg_support()

        status = {
            "installed": is_supported,
            "available": is_supported,
            "error_message": error_msg,
            "suggested_alternative": alternative,
            "database_type": "gaussdb"
        }

        if is_supported:
            status["status"] = "hypopg extension is available and working"
            status["functions_available"] = [
                "hypopg_create_index", "hypopg_drop_index",
                "hypopg_list_indexes", "hypopg_reset"
            ]
        else:
            status["status"] = "hypopg extension is not available"
            status["functions_available"] = []

            # Add GaussDB-specific guidance
            status["gaussdb_guidance"] = (
                "GaussDB may not support the hypopg extension. "
                "Consider using actual indexes in a test environment "
                "or PostgreSQL with hypopg for index analysis."
            )

        # Add version information if available
        try:
            db_version = await sql_driver.get_database_version()
            status["database_version"] = db_version
        except Exception as e:
            logger.debug(f"Could not get database version: {e}")
            status["database_version"] = "unknown"

        return status

    except Exception as e:
        logger.error(f"Error checking hypopg installation status: {e}")
        return {
            "installed": False,
            "available": False,
            "error_message": f"Error checking hypopg status: {e}",
            "status": "error",
            "database_type": "gaussdb",
            "database_version": "unknown"
        }
