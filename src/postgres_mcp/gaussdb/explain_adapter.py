"""
GaussDB EXPLAIN plan adapter for PostgreSQL compatibility.

This module provides the GaussDbExplainPlanTool class that adapts PostgreSQL
EXPLAIN functionality to work with GaussDB databases, handling differences in
EXPLAIN syntax, output format, and feature availability.
"""

import logging
import re
from typing import Any, Dict, List, Optional, Union, TYPE_CHECKING

from ..artifacts import ErrorResult, ExplainPlanArtifact
from ..explain.explain_plan import ExplainPlanTool
from ..sql import IndexDefinition, SafeSqlDriver
from .config import GaussDbCompatibilityConfig
from .error_handler import GaussDbErrorHandler

if TYPE_CHECKING:
    from .sql_driver_adapter import GaussDbSqlDriver

logger = logging.getLogger(__name__)


class GaussDbExplainPlanTool(ExplainPlanTool):
    """
    GaussDB-compatible EXPLAIN plan tool.
    
    This class extends the PostgreSQL ExplainPlanTool to provide GaussDB
    compatibility by adapting EXPLAIN syntax, parsing GaussDB-specific
    output formats, and handling feature differences.
    """
    
    def __init__(self, sql_driver: "GaussDbSqlDriver"):
        """
        Initialize the GaussDB EXPLAIN plan tool.
        
        Args:
            sql_driver: GaussDbSqlDriver instance
        """
        # Initialize parent with the base driver
        super().__init__(sql_driver.base_driver)
        self.gaussdb_driver = sql_driver
        self._compatibility_config: Optional[GaussDbCompatibilityConfig] = None
        self._error_handler: Optional[GaussDbErrorHandler] = None
        
        logger.info("GaussDbExplainPlanTool initialized")
    
    async def _ensure_config_loaded(self) -> None:
        """Ensure compatibility configuration is loaded."""
        if self._compatibility_config is not None:
            return
        
        # Get config from the GaussDB driver
        await self.gaussdb_driver._ensure_config_loaded()
        self._compatibility_config = self.gaussdb_driver.compatibility_config
        
        if self._compatibility_config:
            self._error_handler = GaussDbErrorHandler(self._compatibility_config)
            logger.debug("GaussDB EXPLAIN adapter configuration loaded")
        else:
            logger.warning("No GaussDB compatibility config available")
    
    async def explain(self, sql_query: str, do_analyze: bool = False) -> ExplainPlanArtifact | ErrorResult:
        """
        Generate an EXPLAIN plan for a SQL query with GaussDB compatibility.
        
        Args:
            sql_query: The SQL query to explain
            do_analyze: Whether to include ANALYZE option
            
        Returns:
            ExplainPlanArtifact or ErrorResult
        """
        await self._ensure_config_loaded()
        
        try:
            # Check if EXPLAIN ANALYZE is supported
            if do_analyze and not self._is_explain_analyze_supported():
                return ErrorResult(
                    "EXPLAIN ANALYZE is not supported in this GaussDB version. "
                    "Try using EXPLAIN without ANALYZE option."
                )
            
            # Adapt the query for GaussDB if needed
            adapted_query = await self.gaussdb_driver.adapt_query(sql_query)
            
            # Handle bind parameters
            modified_query, use_generic_plan = await self.replace_query_parameters_if_needed(adapted_query)
            
            # Execute EXPLAIN with GaussDB-specific handling
            return await self._run_gaussdb_explain_query(
                modified_query, 
                analyze=do_analyze, 
                generic_plan=use_generic_plan
            )
            
        except Exception as e:
            if self._error_handler:
                user_message, _, suggested_action = self._error_handler.handle_error(e, {
                    "operation": "explain",
                    "query": sql_query,
                    "analyze": do_analyze
                })
                error_msg = user_message
                if suggested_action:
                    error_msg += f"\nSuggestion: {suggested_action}"
                return ErrorResult(error_msg)
            else:
                return ErrorResult(f"Error generating EXPLAIN plan: {e}")
    
    async def explain_analyze(self, sql_query: str) -> ExplainPlanArtifact | ErrorResult:
        """
        Generate an EXPLAIN ANALYZE plan for a SQL query.
        
        Args:
            sql_query: The SQL query to explain and analyze
            
        Returns:
            ExplainPlanArtifact or ErrorResult
        """
        return await self.explain(sql_query, do_analyze=True)
    
    async def explain_with_hypothetical_indexes(
        self, sql_query: str, hypothetical_indexes: list[dict[str, Any]]
    ) -> ExplainPlanArtifact | ErrorResult:
        """
        Generate an explain plan for a query as if certain indexes existed.
        
        This method checks for hypothetical index support in GaussDB and
        provides appropriate fallback behavior.
        
        Args:
            sql_query: The SQL query to explain
            hypothetical_indexes: List of index definitions as dictionaries
            
        Returns:
            ExplainPlanArtifact or ErrorResult
        """
        await self._ensure_config_loaded()
        
        try:
            # Check if hypothetical indexes are supported
            if not self._is_hypopg_supported():
                return ErrorResult(
                    "Hypothetical indexes (hypopg) are not supported in this GaussDB version. "
                    "Consider creating actual indexes for testing or use a PostgreSQL instance "
                    "with hypopg extension for index analysis."
                )
            
            # Validate index definitions
            validation_result = self._validate_index_definitions(hypothetical_indexes)
            if isinstance(validation_result, ErrorResult):
                return validation_result
            
            # Convert to IndexDefinition objects
            indexes = frozenset(
                IndexDefinition(
                    table=idx["table"],
                    columns=tuple(idx["columns"]),
                    using=idx.get("using", "btree"),
                )
                for idx in hypothetical_indexes
            )
            
            # Adapt the query for GaussDB
            adapted_query = await self.gaussdb_driver.adapt_query(sql_query)
            
            # Handle bind parameters
            modified_query, use_generic_plan = await self.replace_query_parameters_if_needed(adapted_query)
            
            # Generate the explain plan with hypothetical indexes
            plan_data = await self._generate_gaussdb_explain_plan_with_hypothetical_indexes(
                modified_query, indexes, use_generic_plan
            )
            
            # Validate and convert the plan data
            if not plan_data or not isinstance(plan_data, dict) or "Plan" not in plan_data:
                return ErrorResult("Failed to generate a valid explain plan with the hypothetical indexes")
            
            return ExplainPlanArtifact.from_json_data(plan_data)
            
        except Exception as e:
            if self._error_handler:
                user_message, _, suggested_action = self._error_handler.handle_error(e, {
                    "operation": "explain_with_hypothetical_indexes",
                    "query": sql_query,
                    "index_count": len(hypothetical_indexes)
                })
                error_msg = user_message
                if suggested_action:
                    error_msg += f"\nSuggestion: {suggested_action}"
                return ErrorResult(error_msg)
            else:
                return ErrorResult(f"Error generating explain plan with hypothetical indexes: {e}")
    
    def _validate_index_definitions(self, hypothetical_indexes: list[dict[str, Any]]) -> Optional[ErrorResult]:
        """
        Validate hypothetical index definitions.
        
        Args:
            hypothetical_indexes: List of index definitions
            
        Returns:
            ErrorResult if validation fails, None if valid
        """
        if not isinstance(hypothetical_indexes, list):
            return ErrorResult(f"Expected list of index definitions, got {type(hypothetical_indexes)}")
        
        for i, idx in enumerate(hypothetical_indexes):
            if not isinstance(idx, dict):
                return ErrorResult(f"Index definition {i} must be a dictionary, got {type(idx)}")
            
            if "table" not in idx:
                return ErrorResult(f"Index definition {i} missing required 'table' field")
            
            if "columns" not in idx:
                return ErrorResult(f"Index definition {i} missing required 'columns' field")
            
            if not isinstance(idx["columns"], list):
                try:
                    idx["columns"] = list(idx["columns"]) if hasattr(idx["columns"], "__iter__") else [idx["columns"]]
                except Exception as e:
                    return ErrorResult(f"Index definition {i} 'columns' must be a list: {e}")
            
            # Validate index type if specified
            if "using" in idx:
                valid_types = ["btree", "hash", "gin", "gist", "spgist", "brin"]
                if idx["using"].lower() not in valid_types:
                    logger.warning(f"Index type '{idx['using']}' may not be supported in GaussDB")
        
        return None
    
    async def _run_gaussdb_explain_query(
        self, query: str, analyze: bool = False, generic_plan: bool = False
    ) -> ExplainPlanArtifact | ErrorResult:
        """
        Execute EXPLAIN query with GaussDB-specific handling.
        
        Args:
            query: SQL query to explain
            analyze: Whether to include ANALYZE
            generic_plan: Whether to use generic plan
            
        Returns:
            ExplainPlanArtifact or ErrorResult
        """
        try:
            # Build EXPLAIN options for GaussDB
            explain_options = self._build_gaussdb_explain_options(analyze, generic_plan)
            
            explain_query = f"EXPLAIN ({', '.join(explain_options)}) {query}"
            logger.debug(f"Executing GaussDB EXPLAIN query: {explain_query}")
            
            # Execute through the GaussDB driver
            rows = await self.gaussdb_driver.execute_query(explain_query)
            
            if not rows:
                return ErrorResult("No results returned from EXPLAIN")
            
            # Parse GaussDB EXPLAIN output
            return self._parse_gaussdb_explain_output(rows)
            
        except Exception as e:
            logger.error(f"Error executing GaussDB EXPLAIN query: {e}")
            
            # Try fallback to basic EXPLAIN if enhanced options failed
            if analyze or generic_plan:
                logger.info("Attempting fallback to basic EXPLAIN")
                try:
                    basic_explain = f"EXPLAIN (FORMAT JSON) {query}"
                    rows = await self.gaussdb_driver.execute_query(basic_explain)
                    if rows:
                        return self._parse_gaussdb_explain_output(rows)
                except Exception as fallback_e:
                    logger.warning(f"Fallback EXPLAIN also failed: {fallback_e}")
            
            return ErrorResult(f"Error executing explain plan: {e}")
    
    def _build_gaussdb_explain_options(self, analyze: bool, generic_plan: bool) -> List[str]:
        """
        Build EXPLAIN options compatible with GaussDB.
        
        Args:
            analyze: Whether to include ANALYZE
            generic_plan: Whether to use generic plan
            
        Returns:
            List of EXPLAIN options
        """
        options = ["FORMAT JSON"]
        
        if analyze and self._is_explain_analyze_supported():
            options.append("ANALYZE")
        
        # GaussDB may not support GENERIC_PLAN option
        if generic_plan and self._is_generic_plan_supported():
            options.append("GENERIC_PLAN")
        
        # Add other GaussDB-compatible options
        if self._compatibility_config:
            # Check for GaussDB-specific EXPLAIN options
            if self._compatibility_config.is_feature_supported("explain_costs"):
                options.append("COSTS TRUE")
            
            if self._compatibility_config.is_feature_supported("explain_verbose"):
                # Only add VERBOSE if explicitly supported
                pass
        
        return options
    
    def _parse_gaussdb_explain_output(self, rows) -> ExplainPlanArtifact | ErrorResult:
        """
        Parse GaussDB EXPLAIN output into ExplainPlanArtifact.
        
        Args:
            rows: Query result rows from EXPLAIN
            
        Returns:
            ExplainPlanArtifact or ErrorResult
        """
        try:
            if not rows or len(rows) == 0:
                return ErrorResult("Empty EXPLAIN result")
            
            # Get the query plan data
            query_plan_data = rows[0].cells.get("QUERY PLAN")
            
            if query_plan_data is None:
                # Try alternative column names that GaussDB might use
                for col_name in ["query plan", "Query Plan", "PLAN"]:
                    query_plan_data = rows[0].cells.get(col_name)
                    if query_plan_data is not None:
                        break
            
            if query_plan_data is None:
                return ErrorResult("No QUERY PLAN column found in EXPLAIN result")
            
            if not isinstance(query_plan_data, list):
                return ErrorResult(f"Expected list from EXPLAIN, got {type(query_plan_data)}")
            
            if len(query_plan_data) == 0:
                return ErrorResult("Empty EXPLAIN result list")
            
            plan_dict = query_plan_data[0]
            if not isinstance(plan_dict, dict):
                return ErrorResult(f"Expected dict in EXPLAIN result, got {type(plan_dict)}")
            
            # Adapt the plan structure if needed for GaussDB differences
            adapted_plan = self._adapt_gaussdb_plan_structure(plan_dict)
            
            return ExplainPlanArtifact.from_json_data(adapted_plan)
            
        except Exception as e:
            logger.error(f"Error parsing GaussDB EXPLAIN output: {e}")
            return ErrorResult(f"Error parsing explain plan output: {e}")
    
    def _adapt_gaussdb_plan_structure(self, plan_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        Adapt GaussDB plan structure to match PostgreSQL format.
        
        Args:
            plan_dict: Original plan dictionary from GaussDB
            
        Returns:
            Adapted plan dictionary
        """
        # GaussDB might have slightly different field names or structures
        # This method normalizes them to match PostgreSQL format
        
        adapted_plan = plan_dict.copy()
        
        # Handle potential field name differences
        field_mappings = {
            # GaussDB field -> PostgreSQL field
            "execution_time": "Execution Time",
            "planning_time": "Planning Time",
            "total_cost": "Total Cost",
            "startup_cost": "Startup Cost",
        }
        
        for gaussdb_field, pg_field in field_mappings.items():
            if gaussdb_field in adapted_plan and pg_field not in adapted_plan:
                adapted_plan[pg_field] = adapted_plan[gaussdb_field]
        
        # Recursively adapt nested plan nodes
        if "Plan" in adapted_plan and isinstance(adapted_plan["Plan"], dict):
            adapted_plan["Plan"] = self._adapt_plan_node(adapted_plan["Plan"])
        
        return adapted_plan
    
    def _adapt_plan_node(self, node: Dict[str, Any]) -> Dict[str, Any]:
        """
        Adapt individual plan node structure.
        
        Args:
            node: Plan node dictionary
            
        Returns:
            Adapted plan node
        """
        adapted_node = node.copy()
        
        # Handle field name differences at node level
        field_mappings = {
            # GaussDB field -> PostgreSQL field
            "execution_time": "Execution Time",
            "planning_time": "Planning Time",
            "total_cost": "Total Cost",
            "startup_cost": "Startup Cost",
        }
        
        for gaussdb_field, pg_field in field_mappings.items():
            if gaussdb_field in adapted_node and pg_field not in adapted_node:
                adapted_node[pg_field] = adapted_node[gaussdb_field]
        
        # Handle node type differences
        node_type_mappings = {
            # GaussDB node type -> PostgreSQL node type
            "SeqScan": "Seq Scan",
            "IndexScan": "Index Scan",
            "BitmapIndexScan": "Bitmap Index Scan",
            "BitmapHeapScan": "Bitmap Heap Scan",
        }
        
        if "Node Type" in adapted_node:
            node_type = adapted_node["Node Type"]
            if node_type in node_type_mappings:
                adapted_node["Node Type"] = node_type_mappings[node_type]
        
        # Recursively adapt child plans
        if "Plans" in adapted_node and isinstance(adapted_node["Plans"], list):
            adapted_node["Plans"] = [
                self._adapt_plan_node(child) for child in adapted_node["Plans"]
            ]
        
        return adapted_node
    
    async def _generate_gaussdb_explain_plan_with_hypothetical_indexes(
        self,
        query_text: str,
        indexes: frozenset[IndexDefinition],
        use_generic_plan: bool = False,
    ) -> Dict[str, Any]:
        """
        Generate explain plan with hypothetical indexes for GaussDB.
        
        Args:
            query_text: SQL query to explain
            indexes: Set of hypothetical indexes
            use_generic_plan: Whether to use generic plan
            
        Returns:
            Plan dictionary
        """
        try:
            # Check if hypopg is available
            if not self._is_hypopg_supported():
                raise Exception("Hypothetical indexes not supported in this GaussDB version")
            
            # Create the indexes query - GaussDB might use different hypopg functions
            create_indexes_query = await self._build_gaussdb_hypopg_query(indexes)
            
            # Build explain options
            explain_options = ["FORMAT JSON"]
            if use_generic_plan and self._is_generic_plan_supported():
                explain_options.append("GENERIC_PLAN")
            if indexes:
                explain_options.append("COSTS TRUE")
            
            # Execute explain with hypothetical indexes
            explain_plan_query = f"{create_indexes_query}EXPLAIN ({', '.join(explain_options)}) {query_text}"
            plan_result = await self.gaussdb_driver.execute_query(explain_plan_query)
            
            # Extract and adapt the plan
            if plan_result and plan_result[0].cells.get("QUERY PLAN"):
                plan_data = plan_result[0].cells.get("QUERY PLAN")
                if isinstance(plan_data, list) and len(plan_data) > 0:
                    return self._adapt_gaussdb_plan_structure(plan_data[0])
            
            # Return empty plan if no result
            return {"Plan": {"Total Cost": float("inf")}}
            
        except Exception as e:
            logger.error(f"Error generating GaussDB explain plan with hypothetical indexes: {e}")
            raise e
    
    async def _build_gaussdb_hypopg_query(self, indexes: frozenset[IndexDefinition]) -> str:
        """
        Build hypopg query for GaussDB.
        
        Args:
            indexes: Set of index definitions
            
        Returns:
            SQL query to create hypothetical indexes
        """
        # Reset any existing hypothetical indexes
        reset_query = "SELECT hypopg_reset();"
        
        if not indexes:
            return reset_query
        
        # GaussDB might have different hypopg function names or syntax
        create_queries = []
        for idx in indexes:
            # Build index definition string
            index_def = idx.definition
            
            # GaussDB might require different syntax for hypopg_create_index
            create_queries.append(f"SELECT hypopg_create_index('{index_def}');")
        
        return reset_query + "".join(create_queries)
    
    def _is_explain_analyze_supported(self) -> bool:
        """Check if EXPLAIN ANALYZE is supported in current GaussDB version."""
        if not self._compatibility_config:
            return True  # Assume supported if no config
        
        return self._compatibility_config.is_feature_supported("explain_analyze")
    
    def _is_hypopg_supported(self) -> bool:
        """Check if hypothetical indexes (hypopg) are supported."""
        if not self._compatibility_config:
            return False  # Conservative default
        
        return self._compatibility_config.supports_hypopg
    
    def _is_generic_plan_supported(self) -> bool:
        """Check if GENERIC_PLAN option is supported."""
        if not self._compatibility_config:
            return False  # Conservative default
        
        return self._compatibility_config.is_feature_supported("generic_plan")
    
    async def check_feature_availability(self) -> Dict[str, bool]:
        """
        Check availability of EXPLAIN-related features in GaussDB.
        
        Returns:
            Dictionary with feature availability status
        """
        await self._ensure_config_loaded()
        
        features = {
            "explain_analyze": self._is_explain_analyze_supported(),
            "hypopg": self._is_hypopg_supported(),
            "generic_plan": self._is_generic_plan_supported(),
            "json_format": True,  # Assume JSON format is supported
        }
        
        # Test actual feature availability if possible
        try:
            # Test basic EXPLAIN
            test_result = await self.gaussdb_driver.execute_query(
                "EXPLAIN (FORMAT JSON) SELECT 1", 
                skip_adaptation=True
            )
            features["basic_explain"] = test_result is not None
        except Exception:
            features["basic_explain"] = False
        
        return features
    
    async def get_explain_capabilities(self) -> Dict[str, Any]:
        """
        Get comprehensive information about EXPLAIN capabilities.
        
        Returns:
            Dictionary with capability information
        """
        await self._ensure_config_loaded()
        
        capabilities = {
            "database_type": "gaussdb",
            "version": self._compatibility_config.version if self._compatibility_config else "unknown",
            "features": await self.check_feature_availability(),
            "supported_formats": ["JSON"],  # GaussDB typically supports JSON format
            "supported_options": [],
        }
        
        # Add supported EXPLAIN options
        if self._is_explain_analyze_supported():
            capabilities["supported_options"].append("ANALYZE")
        
        if self._is_generic_plan_supported():
            capabilities["supported_options"].append("GENERIC_PLAN")
        
        capabilities["supported_options"].extend(["COSTS", "FORMAT"])
        
        return capabilities