"""
GaussDB index tuning adapters.

This module provides GaussDB-specific adapters for index tuning functionality,
handling differences in query statistics, system views, and index optimization
features between PostgreSQL and GaussDB.
"""

import logging
from typing import Any, Dict, List, Optional, Union, Tuple
from pglast.ast import SelectStmt

from ..index.dta_calc import DatabaseTuningAdvisor
from ..index.llm_opt import LLMOptimizerTool
from ..index.index_opt_base import IndexRecommendation, IndexTuningBase
from ..sql import SafeSqlDriver, SqlDriver
from .sql_driver_adapter import GaussDbSqlDriver
from .feature_checker import FeatureAvailabilityChecker
from .index_tuning_base_adapter import GaussDbIndexTuningMixin

logger = logging.getLogger(__name__)


class GaussDbDatabaseTuningAdvisor(GaussDbIndexTuningMixin, DatabaseTuningAdvisor):
    """
    GaussDB adapter for database tuning advisor.
    
    This class extends the base DatabaseTuningAdvisor to handle GaussDB-specific
    differences in query statistics collection, workload analysis, and index
    recommendation generation.
    """
    
    def __init__(
        self,
        sql_driver: Union[SqlDriver, GaussDbSqlDriver],
        budget_mb: int = -1,
        max_runtime_seconds: int = 30,
        max_index_width: int = 3,
        min_column_usage: int = 1,
        seed_columns_count: int = 3,
        pareto_alpha: float = 2.0,
        min_time_improvement: float = 0.1,
    ):
        """
        Initialize GaussDB database tuning advisor.
        
        Args:
            sql_driver: SQL driver (can be regular SqlDriver or GaussDbSqlDriver)
            budget_mb: Storage budget in MB
            max_runtime_seconds: Time limit for analysis
            max_index_width: Maximum columns in an index
            min_column_usage: Skip columns used in fewer than this many queries
            seed_columns_count: How many single-column seeds to pick
            pareto_alpha: Pareto optimization parameter
            min_time_improvement: Minimum time improvement threshold
        """
        # If we get a regular SqlDriver, wrap it with GaussDbSqlDriver
        if isinstance(sql_driver, GaussDbSqlDriver):
            super().__init__(
                sql_driver.base_driver, budget_mb, max_runtime_seconds,
                max_index_width, min_column_usage, seed_columns_count,
                pareto_alpha, min_time_improvement
            )
            self.gaussdb_driver = sql_driver
        else:
            super().__init__(
                sql_driver, budget_mb, max_runtime_seconds,
                max_index_width, min_column_usage, seed_columns_count,
                pareto_alpha, min_time_improvement
            )
            self.gaussdb_driver = GaussDbSqlDriver(sql_driver)
        
        # Initialize the mixin (this will set up feature_checker)
        super().__init__(
            sql_driver, budget_mb, max_runtime_seconds,
            max_index_width, min_column_usage, seed_columns_count,
            pareto_alpha, min_time_improvement
        )
        logger.debug("GaussDbDatabaseTuningAdvisor initialized")
    
    async def _get_query_stats_direct(
        self, 
        min_calls: int = 50, 
        min_avg_time_ms: float = 5.0, 
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get query statistics from GaussDB with fallback to PostgreSQL.
        
        This method adapts query statistics collection to work with GaussDB's
        equivalent of pg_stat_statements or falls back to PostgreSQL approach.
        
        Args:
            min_calls: Minimum number of calls for a query to be considered
            min_avg_time_ms: Minimum average execution time in ms
            limit: Maximum number of queries to return
            
        Returns:
            List of query statistics dictionaries
        """
        try:
            # Try GaussDB-specific query statistics first
            return await self._gaussdb_get_query_stats(min_calls, min_avg_time_ms, limit)
        except Exception as e:
            logger.warning(f"GaussDB-specific query stats collection failed: {e}")
            # Fallback to PostgreSQL compatible approach
            return await super()._get_query_stats_direct(min_calls, min_avg_time_ms, limit)
    
    async def _gaussdb_get_query_stats(
        self, 
        min_calls: int, 
        min_avg_time_ms: float, 
        limit: int
    ) -> List[Dict[str, Any]]:
        """
        GaussDB-specific query statistics collection.
        
        This method uses GaussDB's equivalent of pg_stat_statements or
        adapted system views to collect query performance statistics.
        
        Args:
            min_calls: Minimum number of calls
            min_avg_time_ms: Minimum average execution time
            limit: Maximum number of queries
            
        Returns:
            List of query statistics
        """
        # Check if GaussDB supports pg_stat_statements equivalent
        supports_stat_statements, _, _ = await self.feature_checker.check_pg_stat_statements_support()
        
        if supports_stat_statements:
            # Use adapted pg_stat_statements query
            query = """
            SELECT queryid, query, calls, total_exec_time/calls as avg_exec_time
            FROM pg_stat_statements
            WHERE calls >= {}
            AND total_exec_time/calls >= {}
            ORDER BY total_exec_time DESC
            LIMIT {}
            """
            
            # Execute through GaussDB adapter for query adaptation
            result = await SafeSqlDriver.execute_param_query(
                self.gaussdb_driver,
                query,
                [min_calls, min_avg_time_ms, limit],
            )
            return [dict(row.cells) for row in result] if result else []
        else:
            # Use alternative GaussDB system views for query statistics
            return await self._gaussdb_get_query_stats_alternative(min_calls, min_avg_time_ms, limit)
    
    async def _gaussdb_get_query_stats_alternative(
        self, 
        min_calls: int, 
        min_avg_time_ms: float, 
        limit: int
    ) -> List[Dict[str, Any]]:
        """
        Alternative method to get query statistics when pg_stat_statements is not available.
        
        This method uses GaussDB-specific system views or log analysis to
        gather query performance information.
        
        Args:
            min_calls: Minimum number of calls
            min_avg_time_ms: Minimum average execution time
            limit: Maximum number of queries
            
        Returns:
            List of query statistics
        """
        logger.info("Using alternative query statistics collection for GaussDB")
        
        # Try to get recent queries from GaussDB system views
        # This is a simplified approach - in practice, you might need to
        # analyze GaussDB logs or use other monitoring views
        query = """
        SELECT 
            md5(query) as queryid,
            query,
            1 as calls,
            1.0 as avg_exec_time
        FROM pg_stat_activity 
        WHERE state = 'active' 
        AND query NOT LIKE '%pg_stat_activity%'
        AND query NOT LIKE '%EXPLAIN%'
        LIMIT {}
        """
        
        result = await SafeSqlDriver.execute_param_query(
            self.gaussdb_driver,
            query,
            [limit],
        )
        
        if result:
            return [dict(row.cells) for row in result]
        else:
            logger.warning("No query statistics available from alternative method")
            return []
    
    async def _get_existing_indexes(self) -> List[Dict[str, Any]]:
        """
        Get existing indexes with GaussDB compatibility.
        
        Returns:
            List of existing index information
        """
        try:
            # Try GaussDB-specific approach first
            return await self._gaussdb_get_existing_indexes()
        except Exception as e:
            logger.warning(f"GaussDB-specific index retrieval failed: {e}")
            # Fallback to PostgreSQL compatible approach
            return await super()._get_existing_indexes()
    
    async def _gaussdb_get_existing_indexes(self) -> List[Dict[str, Any]]:
        """GaussDB-specific method to get existing indexes."""
        query = """
        SELECT schemaname as schema,
               tablename as table,
               indexname as name,
               indexdef as definition
        FROM pg_indexes
        WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
        ORDER BY schemaname, tablename, indexname
        """
        
        # Execute through GaussDB adapter for query adaptation
        result = await self.gaussdb_driver.execute_query(query)
        if result is not None:
            return [dict(row.cells) for row in result]
        return []
    
    async def _estimate_index_size(self, table: str, columns: List[str]) -> int:
        """
        Estimate index size with GaussDB compatibility.
        
        Args:
            table: Table name
            columns: List of column names
            
        Returns:
            Estimated index size in bytes
        """
        try:
            # Try GaussDB-specific approach first
            return await self._gaussdb_estimate_index_size(table, columns)
        except Exception as e:
            logger.warning(f"GaussDB-specific index size estimation failed: {e}")
            # Fallback to PostgreSQL compatible approach
            return await super()._estimate_index_size(table, columns)
    
    async def _gaussdb_estimate_index_size(self, table: str, columns: List[str]) -> int:
        """GaussDB-specific index size estimation."""
        # Create a hashable key for the cache
        cache_key = (table, frozenset(columns))
        
        # Check if we already have a cached result
        if cache_key in self._size_estimate_cache:
            return self._size_estimate_cache[cache_key]
        
        try:
            # Use GaussDB-adapted query for statistics
            stats_query = """
            SELECT COALESCE(SUM(avg_width), 0) AS total_width,
                   COALESCE(SUM(n_distinct), 0) AS total_distinct
            FROM pg_stats
            WHERE tablename = {} AND attname = ANY({})
            """
            
            result = await SafeSqlDriver.execute_param_query(
                self.gaussdb_driver,
                stats_query,
                [table, columns],
            )
            
            if result and result[0].cells:
                size_estimate = self._estimate_index_size_internal(dict(result[0].cells))
                
                # Cache the result
                self._size_estimate_cache[cache_key] = size_estimate
                return size_estimate
            return 0
        except Exception as e:
            raise ValueError("Error estimating index size in GaussDB") from e
    
    async def _get_table_size(self, table: str) -> int:
        """
        Get table size with GaussDB compatibility.
        
        Args:
            table: Table name
            
        Returns:
            Table size in bytes
        """
        try:
            # Try GaussDB-specific approach first
            return await self._gaussdb_get_table_size(table)
        except Exception as e:
            logger.warning(f"GaussDB-specific table size retrieval failed: {e}")
            # Fallback to PostgreSQL compatible approach
            return await super()._get_table_size(table)
    
    async def _gaussdb_get_table_size(self, table: str) -> int:
        """GaussDB-specific table size retrieval."""
        # Check if we have a cached result
        if table in self._table_size_cache:
            return self._table_size_cache[table]
        
        try:
            # Use GaussDB-adapted query for table size
            query = "SELECT pg_total_relation_size(quote_ident({})) as rel_size"
            result = await SafeSqlDriver.execute_param_query(
                self.gaussdb_driver, 
                query, 
                [table]
            )
            
            if result and len(result) > 0 and len(result[0].cells) > 0:
                size = int(result[0].cells["rel_size"])
                # Cache the result
                self._table_size_cache[table] = size
                return size
            else:
                # If query fails, use our estimation method
                size = await self._estimate_table_size(table)
                self._table_size_cache[table] = size
                return size
        except Exception as e:
            logger.warning(f"Error getting table size for {table} in GaussDB: {e}")
            # Use estimation method
            size = await self._estimate_table_size(table)
            self._table_size_cache[table] = size
            return size
    
    async def _generate_recommendations(self, query_weights: List[Tuple[str, SelectStmt, float]]) -> Tuple[set[IndexRecommendation], float]:
        """
        Generate index recommendations with GaussDB-specific filtering and optimization.
        
        This method extends the base recommendation generation to apply GaussDB-specific
        filtering, cost adjustments, and optimization strategies.
        
        Args:
            query_weights: List of (query, parsed_stmt, weight) tuples
            
        Returns:
            Tuple of (recommended_indexes, final_cost)
        """
        try:
            # First get recommendations from the base class
            base_recommendations, base_cost = await super()._generate_recommendations(query_weights)
            
            # Apply GaussDB-specific filtering
            filtered_recommendations = await self._filter_recommendations_for_gaussdb(base_recommendations)
            
            # Generate additional GaussDB-specific recommendations
            gaussdb_specific = await self._generate_gaussdb_specific_recommendations(query_weights)
            
            # Combine and deduplicate recommendations
            all_recommendations = filtered_recommendations | gaussdb_specific
            
            # Re-evaluate cost with GaussDB-adjusted recommendations
            if all_recommendations:
                adjusted_cost = await self._evaluate_configuration_cost(
                    query_weights, 
                    frozenset(rec.index_definition for rec in all_recommendations)
                )
                # Apply GaussDB cost adjustments
                cost_adjustments = []
                for rec in all_recommendations:
                    adjusted_rec_cost = await self._adjust_cost_for_gaussdb(adjusted_cost / len(all_recommendations), rec)
                    cost_adjustments.append(adjusted_rec_cost)
                final_cost = sum(cost_adjustments)
            else:
                final_cost = base_cost
            
            logger.info(f"GaussDB recommendation generation: {len(base_recommendations)} -> {len(all_recommendations)} recommendations")
            return all_recommendations, final_cost
            
        except Exception as e:
            logger.warning(f"Error in GaussDB recommendation generation: {e}")
            # Fallback to base class implementation
            return await super()._generate_recommendations(query_weights)


class GaussDbLLMOptimizerTool(GaussDbIndexTuningMixin, LLMOptimizerTool):
    """
    GaussDB adapter for LLM-based index optimization.
    
    This class extends the base LLMOptimizerTool to handle GaussDB-specific
    differences in query execution plans, index creation, and cost estimation.
    """
    
    def __init__(
        self,
        sql_driver: Union[SqlDriver, GaussDbSqlDriver],
        max_no_progress_attempts: int = 5,
        pareto_alpha: float = 2.0,
    ):
        """
        Initialize GaussDB LLM optimizer tool.
        
        Args:
            sql_driver: SQL driver (can be regular SqlDriver or GaussDbSqlDriver)
            max_no_progress_attempts: Maximum attempts without progress
            pareto_alpha: Pareto optimization parameter
        """
        # If we get a regular SqlDriver, wrap it with GaussDbSqlDriver
        if isinstance(sql_driver, GaussDbSqlDriver):
            super().__init__(sql_driver.base_driver, max_no_progress_attempts, pareto_alpha)
            self.gaussdb_driver = sql_driver
        else:
            super().__init__(sql_driver, max_no_progress_attempts, pareto_alpha)
            self.gaussdb_driver = GaussDbSqlDriver(sql_driver)
        
        # Initialize the mixin (this will set up feature_checker)
        super().__init__(sql_driver, max_no_progress_attempts, pareto_alpha)
        logger.debug("GaussDbLLMOptimizerTool initialized")
    
    async def _generate_recommendations(
        self, 
        query_weights: List[Tuple[str, SelectStmt, float]]
    ) -> Tuple[set[IndexRecommendation], float]:
        """
        Generate index recommendations with GaussDB compatibility.
        
        This method adapts the LLM-based optimization process to work with
        GaussDB's query execution plans and cost models.
        
        Args:
            query_weights: List of (query, parsed_stmt, weight) tuples
            
        Returns:
            Tuple of (recommended_indexes, final_cost)
        """
        try:
            # Check if GaussDB supports hypothetical indexes (hypopg equivalent)
            supports_hypopg, _, _ = await self.feature_checker.check_hypopg_support()
            
            if not supports_hypopg:
                logger.warning("GaussDB does not support hypothetical indexes, using alternative approach")
                return await self._generate_recommendations_without_hypopg(query_weights)
            
            # Use adapted approach with GaussDB-specific considerations
            return await self._gaussdb_generate_recommendations(query_weights)
            
        except Exception as e:
            logger.warning(f"GaussDB-specific recommendation generation failed: {e}")
            # Fallback to PostgreSQL compatible approach
            return await super()._generate_recommendations(query_weights)
    
    async def _gaussdb_generate_recommendations(
        self, 
        query_weights: List[Tuple[str, SelectStmt, float]]
    ) -> Tuple[set[IndexRecommendation], float]:
        """
        GaussDB-specific recommendation generation with hypothetical indexes.
        
        Args:
            query_weights: List of query weights
            
        Returns:
            Tuple of recommended indexes and cost
        """
        # For now we support only one table at a time (same as base class)
        if len(query_weights) > 1:
            logger.error("LLM optimization currently supports only one query at a time")
            raise ValueError("Optimization by LLM supports only one query at a time.")
        
        query = query_weights[0][0]
        parsed_query = query_weights[0][1]
        logger.info("Generating GaussDB index recommendations for query: %s", query)
        
        # Extract tables from the parsed query
        from ..sql import TableAliasVisitor
        table_visitor = TableAliasVisitor()
        table_visitor(parsed_query)
        tables = table_visitor.tables
        logger.info("Extracted tables from query: %s", tables)
        
        # Get the size of the tables using GaussDB adapter
        table_sizes = {}
        for table in tables:
            table_sizes[table] = await self._gaussdb_get_table_size(table)
        total_table_size = sum(table_sizes.values())
        logger.info("Total table size: %s", total_table_size)
        
        # Generate explain plan for the query using GaussDB adapter
        from ..explain.explain_plan import ExplainPlanTool
        explain_tool = ExplainPlanTool(self.gaussdb_driver)
        explain_result = await explain_tool.explain(query)
        
        if hasattr(explain_result, 'to_text') and 'error' in explain_result.to_text().lower():
            logger.error("Failed to generate explain plan: %s", explain_result.to_text())
            raise ValueError(f"Failed to generate explain plan: {explain_result.to_text()}")
        
        # Get the explain plan JSON
        explain_plan_json = explain_result.value
        logger.debug("Generated explain plan: %s", explain_plan_json)
        
        # Extract indexes used in the explain plan
        indexes_used = await self._extract_indexes_from_explain_plan_with_columns(explain_plan_json)
        
        # Get the current cost
        original_cost = await self._evaluate_configuration_cost(query_weights, frozenset())
        logger.info("Original query cost: %f", original_cost)
        
        # Continue with the same logic as the base class but using GaussDB-adapted methods
        from ..index.llm_opt import ScoredIndexes
        original_config = ScoredIndexes(
            indexes=indexes_used,
            execution_cost=original_cost,
            index_size=total_table_size,
            objective_score=self.score(original_cost, total_table_size),
        )
        
        best_config = original_config
        attempt_history = [original_config]
        no_progress_count = 0
        
        # Use the same LLM-based optimization loop as the base class
        # but with GaussDB-adapted cost evaluation
        import instructor
        from openai import OpenAI
        from ..index.llm_opt import IndexingAlternative
        
        client = instructor.from_openai(OpenAI())
        
        while no_progress_count < self.max_no_progress_attempts:
            logger.info("Requesting index recommendations from LLM")
            
            # Build history of past attempts
            history_prompt = ""
            if attempt_history:
                history_prompt = "\nPrevious attempts and their costs:\n"
                for attempt in attempt_history:
                    indexes_str = ";".join(idx.to_index_definition().definition for idx in attempt.indexes)
                    history_prompt += f"- Indexes: {indexes_str}, Cost: {attempt.execution_cost}, Index Size: {attempt.index_size}, "
                    history_prompt += f"Objective Score: {attempt.objective_score}\n"
            
            if no_progress_count > 0:
                remaining_attempts_prompt = f"You have made {no_progress_count} attempts without progress. "
                if self.max_no_progress_attempts - no_progress_count < self.max_no_progress_attempts / 2:
                    remaining_attempts_prompt += "Get creative and suggest indexes that are not obvious."
            else:
                remaining_attempts_prompt = ""
            
            response = client.chat.completions.create(
                model="gpt-4o",
                response_model=IndexingAlternative,
                temperature=1.2,
                messages=[
                    {"role": "system", "content": "You are a helpful assistant that generates index recommendations for a GaussDB database workload."},
                    {
                        "role": "user",
                        "content": f"Here is the query we are optimizing for GaussDB: {query}\n"
                        f"Here is the explain plan: {explain_plan_json}\n"
                        f"Here are the existing indexes: {';'.join(idx.to_index_definition().definition for idx in indexes_used)}\n"
                        f"{history_prompt}\n"
                        "Each indexing suggestion that you provide is a combination of indexes. You can provide multiple alternative suggestions. "
                        "We will evaluate each alternative using GaussDB's query optimizer to see how it will behave with those indexes in place. "
                        "The overall score is based on a combination of execution cost and index size. In all cases, lower is better. "
                        "Prefer fewer indexes to more indexes. Prefer indexes with fewer columns to indexes with more columns. "
                        "Consider GaussDB-specific index types and limitations when making recommendations. "
                        f"{remaining_attempts_prompt}",
                    },
                ],
            )
            
            # Convert the response to IndexConfig objects
            index_alternatives = response.alternatives
            logger.info("Received %d alternative index configurations from LLM", len(index_alternatives))
            
            # If no alternatives were generated, break the loop
            if not index_alternatives:
                logger.warning("No index alternatives were generated by the LLM")
                break
            
            # Try each alternative using GaussDB-adapted evaluation
            found_improvement = False
            for i, index_set in enumerate(index_alternatives):
                try:
                    logger.info("Evaluating alternative %d/%d with %d indexes", i + 1, len(index_alternatives), len(index_set))
                    
                    # Evaluate this index configuration using GaussDB adapter
                    execution_cost_estimate = await self._evaluate_configuration_cost(
                        query_weights, frozenset({index.to_index_definition() for index in index_set})
                    )
                    logger.info(
                        "Alternative %d cost: %f (reduction: %.2f%%)",
                        i + 1,
                        execution_cost_estimate,
                        ((best_config.execution_cost - execution_cost_estimate) / best_config.execution_cost) * 100,
                    )
                    
                    # Estimate the size of the indexes using GaussDB adapter
                    index_size_estimate = await self._gaussdb_estimate_index_size_2(
                        {index.to_index_definition() for index in index_set}, 1024 * 1024
                    )
                    logger.info("Estimated index size: %f", index_size_estimate)
                    
                    # Score based on a balance of size and performance
                    import math
                    score = math.log(execution_cost_estimate) + self.pareto_alpha * math.log(total_table_size + index_size_estimate)
                    
                    # Record this attempt in history
                    from ..index.llm_opt import Index
                    latest_config = ScoredIndexes(
                        indexes={Index(table_name=index.table_name, columns=index.columns) for index in index_set},
                        execution_cost=execution_cost_estimate,
                        index_size=index_size_estimate,
                        objective_score=score,
                    )
                    attempt_history.append(latest_config)
                    logger.info("Latest config: %s", latest_config)
                    
                    # If this is better than what we've seen so far, update our best
                    if latest_config.objective_score < best_config.objective_score:
                        best_config = latest_config
                        found_improvement = True
                        
                except Exception as e:
                    logger.error("Error evaluating alternative %d/%d: %s", i + 1, len(index_alternatives), str(e))
            
            # Keep only the 5 best results in the attempt history
            attempt_history.sort(key=lambda x: x.objective_score)
            attempt_history = attempt_history[:5]
            
            if found_improvement:
                no_progress_count = 0
            else:
                no_progress_count += 1
                logger.info(
                    "No improvement found in this iteration. Attempts without progress: %d/%d", 
                    no_progress_count, self.max_no_progress_attempts
                )
        
        if best_config != original_config:
            logger.info(
                "Selected best index configuration with %d indexes, cost reduction: %.2f%%, indexes: %s",
                len(best_config.indexes),
                ((original_cost - best_config.execution_cost) / original_cost) * 100,
                ", ".join(f"{idx.table_name}.({','.join(idx.columns)})" for idx in best_config.indexes),
            )
        else:
            logger.info("No better index configuration found")
        
        # Convert Index objects to IndexRecommendation objects for return
        best_index_config_set = {index.to_index_recommendation() for index in best_config.indexes}
        return (best_index_config_set, best_config.execution_cost)
    
    async def _generate_recommendations_without_hypopg(
        self, 
        query_weights: List[Tuple[str, SelectStmt, float]]
    ) -> Tuple[set[IndexRecommendation], float]:
        """
        Generate recommendations when hypothetical indexes are not supported.
        
        This method provides alternative index recommendation logic for GaussDB
        versions that don't support hypothetical indexes.
        
        Args:
            query_weights: List of query weights
            
        Returns:
            Tuple of recommended indexes and cost
        """
        logger.info("Generating index recommendations without hypothetical index support")
        
        # Simplified approach: analyze query patterns and suggest common index types
        recommendations = set()
        
        for query, parsed_query, weight in query_weights:
            # Extract columns from WHERE clauses and JOIN conditions
            from ..sql import ColumnCollector
            collector = ColumnCollector()
            collector(parsed_query)
            
            # Create simple single-column indexes for frequently used columns
            for table, columns in collector.columns.items():
                for column in list(columns)[:3]:  # Limit to top 3 columns per table
                    recommendations.add(IndexRecommendation(
                        table=table,
                        columns=(column,),
                        using="btree"
                    ))
        
        # Return recommendations with estimated cost (simplified)
        original_cost = 1000.0  # Placeholder cost
        return recommendations, original_cost * 0.8  # Assume 20% improvement
    
    async def _gaussdb_get_table_size(self, table: str) -> int:
        """Get table size using GaussDB adapter."""
        try:
            query = "SELECT pg_total_relation_size(quote_ident({})) as rel_size"
            result = await SafeSqlDriver.execute_param_query(
                self.gaussdb_driver, 
                query, 
                [table]
            )
            
            if result and len(result) > 0 and len(result[0].cells) > 0:
                return int(result[0].cells["rel_size"])
            else:
                # Default size if we can't get it
                return 10 * 1024 * 1024  # 10MB default
        except Exception as e:
            logger.warning(f"Error getting table size for {table} in GaussDB: {e}")
            return 10 * 1024 * 1024  # 10MB default
    
    async def _gaussdb_estimate_index_size_2(
        self, 
        index_set: set, 
        min_size_penalty: float = 1024 * 1024
    ) -> float:
        """
        Estimate index size using GaussDB-adapted approach.
        
        Args:
            index_set: Set of index definitions
            min_size_penalty: Minimum size penalty
            
        Returns:
            Total estimated size of all indexes in bytes
        """
        if not index_set:
            return 0.0
        
        total_size = 0.0
        
        for index_config in index_set:
            try:
                # Check if GaussDB supports hypothetical indexes
                supports_hypopg, _, _ = await self.feature_checker.check_hypopg_support()
                
                if supports_hypopg:
                    # Use hypothetical index approach
                    create_index_query = (
                        "WITH hypo_index AS (SELECT indexrelid FROM hypopg_create_index(%s)) "
                        "SELECT hypopg_relation_size(indexrelid) as size, hypopg_drop_index(indexrelid) FROM hypo_index;"
                    )
                    
                    result = await self.gaussdb_driver.execute_query(create_index_query, params=[index_config.definition])
                    
                    if result and len(result) > 0:
                        size = result[0].cells.get("size", 0)
                        total_size += max(float(size), min_size_penalty)
                        logger.debug(f"Estimated size for index {index_config.name}: {size} bytes")
                    else:
                        logger.warning(f"Failed to estimate size for index {index_config.name}")
                        total_size += min_size_penalty
                else:
                    # Use alternative size estimation
                    estimated_size = await self._estimate_index_size_alternative(index_config)
                    total_size += max(estimated_size, min_size_penalty)
                    
            except Exception as e:
                logger.error(f"Error estimating size for index {index_config.name}: {e!s}")
                total_size += min_size_penalty
        
        return total_size
    
    async def _estimate_index_size_alternative(self, index_config) -> float:
        """
        Alternative index size estimation when hypothetical indexes are not available.
        
        Args:
            index_config: Index configuration
            
        Returns:
            Estimated index size in bytes
        """
        try:
            # Get table statistics to estimate index size
            stats_query = """
            SELECT COALESCE(SUM(avg_width), 0) AS total_width,
                   COALESCE(MAX(n_distinct), 1) AS max_distinct
            FROM pg_stats
            WHERE tablename = {} AND attname = ANY({})
            """
            
            result = await SafeSqlDriver.execute_param_query(
                self.gaussdb_driver,
                stats_query,
                [index_config.table, list(index_config.columns)],
            )
            
            if result and result[0].cells:
                width = (result[0].cells["total_width"] or 0) + 8  # 8 bytes for heap TID
                ndistinct = result[0].cells["max_distinct"] or 1.0
                ndistinct = ndistinct if ndistinct > 0 else 1.0
                # Simplified formula
                size_estimate = int(width * ndistinct * 2.0)
                return float(size_estimate)
            
            # Default estimate if no statistics available
            return 1024 * 1024  # 1MB default
            
        except Exception as e:
            logger.warning(f"Error in alternative index size estimation: {e}")
            return 1024 * 1024  # 1MB default
    
    async def _generate_recommendations(self, query_weights: List[Tuple[str, SelectStmt, float]]) -> Tuple[set[IndexRecommendation], float]:
        """
        Generate index recommendations with GaussDB-specific filtering and LLM optimization.
        
        This method extends the base LLM recommendation generation to apply GaussDB-specific
        filtering, cost adjustments, and optimization strategies.
        
        Args:
            query_weights: List of (query, parsed_stmt, weight) tuples
            
        Returns:
            Tuple of (recommended_indexes, final_cost)
        """
        try:
            # Check if GaussDB supports hypothetical indexes (hypopg equivalent)
            supports_hypopg, _, _ = await self.feature_checker.check_hypopg_support()
            
            if not supports_hypopg:
                logger.warning("GaussDB does not support hypothetical indexes, using alternative approach")
                base_recommendations, base_cost = await self._generate_recommendations_without_hypopg(query_weights)
            else:
                # Use adapted approach with GaussDB-specific considerations
                base_recommendations, base_cost = await self._gaussdb_generate_recommendations(query_weights)
            
            # Apply GaussDB-specific filtering to LLM-generated recommendations
            filtered_recommendations = await self._filter_recommendations_for_gaussdb(base_recommendations)
            
            # Generate additional GaussDB-specific recommendations
            gaussdb_specific = await self._generate_gaussdb_specific_recommendations(query_weights)
            
            # Combine recommendations
            all_recommendations = filtered_recommendations | gaussdb_specific
            
            # Re-evaluate cost with GaussDB adjustments
            if all_recommendations:
                adjusted_cost = await self._evaluate_configuration_cost(
                    query_weights, 
                    frozenset(rec.index_definition for rec in all_recommendations)
                )
                # Apply GaussDB cost adjustments
                cost_adjustments = []
                for rec in all_recommendations:
                    adjusted_rec_cost = await self._adjust_cost_for_gaussdb(adjusted_cost / len(all_recommendations), rec)
                    cost_adjustments.append(adjusted_rec_cost)
                final_cost = sum(cost_adjustments)
            else:
                final_cost = base_cost
            
            logger.info(f"GaussDB LLM recommendation generation: {len(base_recommendations)} -> {len(all_recommendations)} recommendations")
            return all_recommendations, final_cost
            
        except Exception as e:
            logger.warning(f"Error in GaussDB LLM recommendation generation: {e}")
            # Fallback to base class implementation
            return await super()._generate_recommendations(query_weights)