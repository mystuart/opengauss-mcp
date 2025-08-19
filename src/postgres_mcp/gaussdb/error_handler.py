"""
GaussDB-specific error handling and message mapping.

This module provides error handling utilities for GaussDB databases,
including error message translation, user-friendly error reporting,
and fallback strategies for unsupported features.
"""

import logging
import re
from enum import Enum
from typing import Any
from typing import Dict
from typing import Optional
from typing import Tuple

logger = logging.getLogger(__name__)


class ErrorCategory(str, Enum):
    """Categories of database errors for better handling."""
    CONNECTION = "connection"
    AUTHENTICATION = "authentication"
    SYNTAX = "syntax"
    FEATURE_NOT_SUPPORTED = "feature_not_supported"
    PERMISSION = "permission"
    RESOURCE = "resource"
    DATA = "data"
    CONSTRAINT = "constraint"
    UNKNOWN = "unknown"


class GaussDbErrorHandler:
    """
    Error handler for GaussDB-specific errors and messages.
    
    This class provides functionality to translate GaussDB error messages
    into user-friendly formats, categorize errors, and suggest appropriate
    actions or workarounds.
    """

    # Common GaussDB error patterns and their mappings
    ERROR_PATTERNS = {
        # Connection errors
        r"connection.*refused": (
            ErrorCategory.CONNECTION,
            "Unable to connect to GaussDB server. Please check if the server is running and accessible."
        ),
        r"authentication.*failed": (
            ErrorCategory.AUTHENTICATION,
            "Authentication failed. Please verify your username and password."
        ),
        r"database.*does not exist": (
            ErrorCategory.CONNECTION,
            "The specified database does not exist. Please check the database name."
        ),
        r"role.*does not exist": (
            ErrorCategory.AUTHENTICATION,
            "The specified user role does not exist. Please check the username."
        ),

        # Feature support errors
        r"extension.*does not exist": (
            ErrorCategory.FEATURE_NOT_SUPPORTED,
            "The requested extension is not available in GaussDB. Consider using alternative approaches."
        ),
        r"function.*does not exist": (
            ErrorCategory.FEATURE_NOT_SUPPORTED,
            "The requested function is not available in this GaussDB version."
        ),
        r"hypopg|hypothetical.*index": (
            ErrorCategory.FEATURE_NOT_SUPPORTED,
            "Hypothetical indexes (hypopg) are not supported in GaussDB. Use EXPLAIN to analyze query performance instead."
        ),

        # Syntax errors
        r"syntax error": (
            ErrorCategory.SYNTAX,
            "SQL syntax error. The query may contain PostgreSQL-specific syntax not supported in GaussDB."
        ),
        r"column.*does not exist": (
            ErrorCategory.SYNTAX,
            "The specified column does not exist. This may be due to differences in system view schemas between PostgreSQL and GaussDB."
        ),
        r"relation.*does not exist": (
            ErrorCategory.SYNTAX,
            "The specified table or view does not exist. Check if the object name is correct for GaussDB."
        ),

        # Permission errors
        r"permission denied": (
            ErrorCategory.PERMISSION,
            "Permission denied. The user may not have sufficient privileges for this operation."
        ),
        r"must be.*owner": (
            ErrorCategory.PERMISSION,
            "This operation requires object ownership or superuser privileges."
        ),

        # Resource errors
        r"out of memory": (
            ErrorCategory.RESOURCE,
            "Insufficient memory to complete the operation. Consider reducing query complexity or increasing available memory."
        ),
        r"too many connections": (
            ErrorCategory.RESOURCE,
            "Maximum number of connections reached. Please try again later or increase connection limits."
        ),

        # Data errors
        r"duplicate key": (
            ErrorCategory.CONSTRAINT,
            "Duplicate key violation. The operation would create duplicate values in a unique constraint."
        ),
        r"foreign key": (
            ErrorCategory.CONSTRAINT,
            "Foreign key constraint violation. The referenced record may not exist."
        ),
        r"check constraint": (
            ErrorCategory.CONSTRAINT,
            "Check constraint violation. The data does not meet the defined constraints."
        ),
        r"not-null constraint": (
            ErrorCategory.CONSTRAINT,
            "Not-null constraint violation. A required field is missing a value."
        ),
    }

    # Specific GaussDB error codes and messages
    GAUSSDB_ERROR_CODES = {
        "42P01": "Relation does not exist",
        "42703": "Column does not exist",
        "42883": "Function does not exist",
        "42P02": "Parameter does not exist",
        "08001": "Connection failure",
        "08006": "Connection failure",
        "28000": "Authentication failure",
        "28P01": "Invalid password",
        "3D000": "Database does not exist",
        "42501": "Insufficient privilege",
        "53300": "Too many connections",
        "53200": "Out of memory",
        "23505": "Unique violation",
        "23503": "Foreign key violation",
        "23514": "Check violation",
        "23502": "Not null violation",
    }

    def __init__(self, compatibility_config=None):
        """
        Initialize the error handler.
        
        Args:
            compatibility_config: GaussDB compatibility configuration
        """
        self.compatibility_config = compatibility_config
        self._custom_error_mappings: Dict[str, str] = {}

        # Load custom error mappings from config if available
        if compatibility_config and hasattr(compatibility_config, 'error_mappings'):
            self._custom_error_mappings.update(compatibility_config.error_mappings)

    def handle_error(self, error: Exception, context: Optional[Dict[str, Any]] = None) -> Tuple[str, ErrorCategory, Optional[str]]:
        """
        Handle and categorize a database error.
        
        Args:
            error: The exception that occurred
            context: Optional context information (query, operation, etc.)
            
        Returns:
            Tuple of (user_friendly_message, error_category, suggested_action)
        """
        error_str = str(error).lower()
        error_category = ErrorCategory.UNKNOWN
        user_message = str(error)
        suggested_action = None

        try:
            # First check custom error mappings from config
            for error_key, custom_message in self._custom_error_mappings.items():
                if error_key.lower() in error_str:
                    return custom_message, ErrorCategory.FEATURE_NOT_SUPPORTED, None

            # Check against known error patterns
            for pattern, (category, message) in self.ERROR_PATTERNS.items():
                if re.search(pattern, error_str, re.IGNORECASE):
                    error_category = category
                    user_message = message
                    suggested_action = self._get_suggested_action(category, error_str, context)
                    break

            # Check for specific error codes if available
            error_code = self._extract_error_code(str(error))
            if error_code and error_code in self.GAUSSDB_ERROR_CODES:
                user_message = f"{self.GAUSSDB_ERROR_CODES[error_code]}: {user_message}"

            # Add context-specific information
            if context:
                user_message = self._add_context_info(user_message, context)

            logger.debug(f"Error handled: {error_category.value} - {user_message}")

        except Exception as e:
            logger.error(f"Error in error handler: {e}")
            # Fallback to original error
            user_message = str(error)
            error_category = ErrorCategory.UNKNOWN

        return user_message, error_category, suggested_action

    def _extract_error_code(self, error_str: str) -> Optional[str]:
        """
        Extract PostgreSQL/GaussDB error code from error message.
        
        Args:
            error_str: Error message string
            
        Returns:
            Error code if found, None otherwise
        """
        # Look for standard PostgreSQL error code format
        code_match = re.search(r'\b([0-9A-Z]{5})\b', error_str)
        if code_match:
            return code_match.group(1)

        return None

    def _get_suggested_action(self, category: ErrorCategory, error_str: str, context: Optional[Dict[str, Any]]) -> Optional[str]:
        """
        Get suggested action based on error category and context.
        
        Args:
            category: Error category
            error_str: Error message string
            context: Optional context information
            
        Returns:
            Suggested action string or None
        """
        suggestions = {
            ErrorCategory.CONNECTION: [
                "Check if GaussDB server is running",
                "Verify connection parameters (host, port, database name)",
                "Check network connectivity and firewall settings"
            ],
            ErrorCategory.AUTHENTICATION: [
                "Verify username and password",
                "Check if user exists and has login privileges",
                "Ensure proper authentication method is configured"
            ],
            ErrorCategory.FEATURE_NOT_SUPPORTED: [
                "Check GaussDB documentation for supported features",
                "Consider using alternative approaches",
                "Update to a newer GaussDB version if available"
            ],
            ErrorCategory.SYNTAX: [
                "Review query syntax for GaussDB compatibility",
                "Check system view and column names",
                "Consult GaussDB SQL reference documentation"
            ],
            ErrorCategory.PERMISSION: [
                "Grant necessary privileges to the user",
                "Contact database administrator",
                "Use a user with appropriate permissions"
            ],
            ErrorCategory.RESOURCE: [
                "Reduce query complexity or data size",
                "Increase available system resources",
                "Optimize query performance"
            ]
        }

        category_suggestions = suggestions.get(category, [])
        if category_suggestions:
            return "; ".join(category_suggestions)

        return None

    def _add_context_info(self, message: str, context: Dict[str, Any]) -> str:
        """
        Add context information to error message.
        
        Args:
            message: Base error message
            context: Context information
            
        Returns:
            Enhanced error message with context
        """
        context_parts = []

        if "query" in context:
            query = context["query"]
            if len(query) > 100:
                query = query[:100] + "..."
            context_parts.append(f"Query: {query}")

        if "operation" in context:
            context_parts.append(f"Operation: {context['operation']}")

        if "table" in context:
            context_parts.append(f"Table: {context['table']}")

        if context_parts:
            return f"{message} (Context: {'; '.join(context_parts)})"

        return message

    def is_retryable_error(self, error: Exception) -> bool:
        """
        Determine if an error is potentially retryable.
        
        Args:
            error: The exception to check
            
        Returns:
            True if error might be retryable, False otherwise
        """
        error_str = str(error).lower()

        # Connection-related errors that might be temporary
        retryable_patterns = [
            r"connection.*refused",
            r"connection.*reset",
            r"connection.*timeout",
            r"server.*closed.*connection",
            r"too many connections",
            r"temporary.*failure",
            r"resource.*temporarily.*unavailable"
        ]

        for pattern in retryable_patterns:
            if re.search(pattern, error_str, re.IGNORECASE):
                return True

        return False

    def should_fallback_to_postgresql(self, error: Exception) -> bool:
        """
        Determine if we should fallback to PostgreSQL-compatible query.
        
        Args:
            error: The exception to check
            
        Returns:
            True if fallback is recommended, False otherwise
        """
        error_str = str(error).lower()

        # Errors that suggest GaussDB-specific adaptation issues
        fallback_patterns = [
            r"column.*does not exist",
            r"relation.*does not exist",
            r"function.*does not exist",
            r"syntax error.*near",
            r"operator.*does not exist"
        ]

        for pattern in fallback_patterns:
            if re.search(pattern, error_str, re.IGNORECASE):
                return True

        return False

    def get_feature_alternative(self, feature: str) -> Optional[str]:
        """
        Get alternative approach for unsupported features.
        
        Args:
            feature: Feature name that's not supported
            
        Returns:
            Alternative approach description or None
        """
        alternatives = {
            "hypopg": "Use EXPLAIN ANALYZE to test query performance with different index configurations",
            "pg_stat_statements": "Use GaussDB's built-in query monitoring views or enable query logging",
            "pg_buffercache": "Use GaussDB-specific buffer pool monitoring views",
            "pg_stat_progress_vacuum": "Monitor vacuum operations through GaussDB system views",
            "pg_stat_progress_create_index": "Monitor index creation through GaussDB activity views"
        }

        return alternatives.get(feature.lower())

    def format_error_for_user(self, error: Exception, context: Optional[Dict[str, Any]] = None) -> str:
        """
        Format error message for end-user display.
        
        Args:
            error: The exception to format
            context: Optional context information
            
        Returns:
            Formatted error message suitable for user display
        """
        user_message, category, suggested_action = self.handle_error(error, context)

        formatted_parts = [f"Error: {user_message}"]

        if category != ErrorCategory.UNKNOWN:
            formatted_parts.append(f"Category: {category.value.replace('_', ' ').title()}")

        if suggested_action:
            formatted_parts.append(f"Suggestions: {suggested_action}")

        return "\n".join(formatted_parts)

    def add_custom_error_mapping(self, error_pattern: str, user_message: str) -> None:
        """
        Add a custom error mapping.
        
        Args:
            error_pattern: Error pattern to match
            user_message: User-friendly message to display
        """
        self._custom_error_mappings[error_pattern] = user_message
        logger.debug(f"Added custom error mapping: {error_pattern} -> {user_message}")

    def remove_custom_error_mapping(self, error_pattern: str) -> bool:
        """
        Remove a custom error mapping.
        
        Args:
            error_pattern: Error pattern to remove
            
        Returns:
            True if mapping was removed, False if not found
        """
        if error_pattern in self._custom_error_mappings:
            del self._custom_error_mappings[error_pattern]
            logger.debug(f"Removed custom error mapping: {error_pattern}")
            return True
        return False

    def get_error_statistics(self) -> Dict[str, int]:
        """
        Get statistics about handled errors.
        
        Returns:
            Dictionary with error statistics
        """
        # This could be enhanced to track error counts over time
        return {
            "total_patterns": len(self.ERROR_PATTERNS),
            "custom_mappings": len(self._custom_error_mappings),
            "error_codes": len(self.GAUSSDB_ERROR_CODES)
        }
