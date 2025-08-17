"""
GaussDB index tuning base adapter.

This module provides GaussDB-specific extensions to the IndexTuningBase class,
handling differences in index types, cost models, and optimization parameters
between PostgreSQL and GaussDB.
"""

import logging
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from dataclasses import dataclass

from ..index.index_opt_base import IndexRecommendation, IndexTuningBase
from ..sql import SqlDriver
from .sql_driver_adapter import GaussDbSqlDriver
from .feature_checker import FeatureAvailabilityChecker

logger = logging.getLogger(__name__)


@dataclass
class GaussDbIndexCostModel:
    """
    GaussDB-specific index cost model parameters.
    
    This class encapsulates the cost model parameters that differ between
    PostgreSQL and GaussDB for index optimization decisions.
    """
    
    # Index creation costs (relative to PostgreSQL)
    btree_creation_cost_factor: float = 1.0
    hash_creation_cost_factor: float = 1.2  # Hash indexes may be more expensive in GaussDB
    gin_creation_cost_factor: float = 1.5   # GIN indexes may have different costs
    gist_creation_cost_factor: float = 1.3  # GIST indexes may have different costs
    
    # Index maintenance costs (relative to PostgreSQL)
    btree_maintenance_cost_factor: float = 1.0
    hash_maintenance_cost_factor: float = 1.1
    gin_maintenance_cost_factor: float = 1.4
    gist_maintenance_cost_factor: float = 1.2
    
    # Query execution cost factors
    index_scan_cost_factor: float = 1.0
    bitmap_scan_cost_factor: float = 1.1
    
    # Storage cost factors
    storage_cost_factor: float = 1.0
    
    # GaussDB-specific parameters
    distributed_index_overhead: float = 1.2  # Additional overhead for distributed indexes
    replication_factor: int = 1  # Replication factor for distributed environments


class GaussDbIndexTuningMixin:
    """
    Mixin class that provides GaussDB-specific index tuning capabilities.
    
    This mixin can be used with IndexTuningBase subclasses to add GaussDB-specific
    functionality for index recommendation generation and cost estimation.
    """
    
    def __init__(self, *args, **kwargs):
        """Initialize the GaussDB index tuning mixin."""
        super().__init__(*args, **kwargs)
        
        # Initialize GaussDB-specific attributes
        if hasattr(self, 'gaussdb_driver'):
            self.feature_checker = FeatureAvailabilityChecker(self.gaussdb_driver)
        else:
            # Create a GaussDB driver wrapper if not already present
            self.gaussdb_driver = GaussDbSqlDriver(self.sql_driver)
            self.feature_checker = FeatureAvailabilityChecker(self.gaussdb_driver)
        
        self.gaussdb_cost_model = GaussDbIndexCostModel()
        self._gaussdb_supported_index_types: Optional[Set[str]] = None
        self._gaussdb_index_limitations: Optional[Dict[str, Any]] = None
        
        logger.debug("GaussDbIndexTuningMixin initialized")
    
    async def _get_gaussdb_supported_index_types(self) -> Set[str]:
        """
        Get the set of index types supported by the current GaussDB version.
        
        Returns:
            Set of supported index type names
        """
        if self._gaussdb_supported_index_types is not None:
            return self._gaussdb_supported_index_types
        
        try:
            # Query GaussDB for supported index access methods
            query = """
                SELECT amname 
                FROM pg_am 
                WHERE amtype = 'i'  -- Index access methods only
                ORDER BY amname
            """
            
            result = await self.gaussdb_driver.execute_query(query)
            
            if result:
                supported_types = {row.cells['amname'] for row in result}
                logger.info(f"GaussDB supported index types: {supported_types}")
            else:
                # Default supported types if query fails
                supported_types = {'btree', 'hash', 'gin', 'gist'}
                logger.warning("Could not query GaussDB index types, using defaults")
            
            self._gaussdb_supported_index_types = supported_types
            return supported_types
            
        except Exception as e:
            logger.warning(f"Error querying GaussDB index types: {e}")
            # Return conservative default set
            self._gaussdb_supported_index_types = {'btree', 'hash'}
            return self._gaussdb_supported_index_types
    
    async def _get_gaussdb_index_limitations(self) -> Dict[str, Any]:
        """
        Get GaussDB-specific index limitations and constraints.
        
        Returns:
            Dictionary of index limitations and constraints
        """
        if self._gaussdb_index_limitations is not None:
            return self._gaussdb_index_limitations
        
        try:
            # Get GaussDB version and configuration
            version = await self.gaussdb_driver.get_database_version()
            
            # Define limitations based on GaussDB version and configuration
            limitations = {
                'max_index_columns': 32,  # GaussDB may have different limits
                'max_index_name_length': 63,
                'max_expression_index_complexity': 100,
                'supported_column_types': {
                    'btree': ['integer', 'bigint', 'text', 'varchar', 'timestamp', 'date', 'numeric'],
                    'hash': ['integer', 'bigint', 'text', 'varchar'],
                    'gin': ['text', 'varchar', 'jsonb', 'tsvector'],
                    'gist': ['geometry', 'text', 'varchar']
                },
                'unsupported_features': [],
                'version': version
            }
            
            # Add version-specific limitations
            if version.startswith('8.1'):
                limitations['unsupported_features'].extend(['partial_indexes_on_expressions'])
            
            self._gaussdb_index_limitations = limitations
            return limitations
            
        except Exception as e:
            logger.warning(f"Error getting GaussDB index limitations: {e}")
            # Return conservative defaults
            self._gaussdb_index_limitations = {
                'max_index_columns': 16,  # Conservative limit
                'max_index_name_length': 63,
                'supported_column_types': {
                    'btree': ['integer', 'bigint', 'text', 'varchar', 'timestamp', 'date'],
                    'hash': ['integer', 'bigint', 'text', 'varchar']
                },
                'unsupported_features': ['gin', 'gist', 'partial_indexes'],
                'version': 'unknown'
            }
            return self._gaussdb_index_limitations
    
    async def _filter_recommendations_for_gaussdb(
        self, 
        recommendations: Set[IndexRecommendation]
    ) -> Set[IndexRecommendation]:
        """
        Filter index recommendations based on GaussDB capabilities and limitations.
        
        Args:
            recommendations: Set of index recommendations to filter
            
        Returns:
            Filtered set of recommendations compatible with GaussDB
        """
        if not recommendations:
            return recommendations
        
        supported_types = await self._get_gaussdb_supported_index_types()
        limitations = await self._get_gaussdb_index_limitations()
        
        filtered_recommendations = set()
        
        for rec in recommendations:
            # Check if index type is supported
            if rec.using not in supported_types:
                logger.debug(f"Filtering out unsupported index type: {rec.using}")
                # Try to convert to a supported type
                converted_rec = await self._convert_to_supported_index_type(rec, supported_types)
                if converted_rec:
                    filtered_recommendations.add(converted_rec)
                continue
            
            # Check column count limitations
            if len(rec.columns) > limitations['max_index_columns']:
                logger.debug(f"Filtering out index with too many columns: {len(rec.columns)}")
                continue
            
            # Check column type compatibility
            if not await self._check_column_type_compatibility(rec, limitations):
                logger.debug(f"Filtering out index with incompatible column types: {rec.columns}")
                continue
            
            # Check index name length
            if len(rec.name) > limitations['max_index_name_length']:
                logger.debug(f"Filtering out index with name too long: {rec.name}")
                continue
            
            # Add the recommendation if it passes all checks
            filtered_recommendations.add(rec)
        
        logger.info(f"Filtered {len(recommendations)} recommendations to {len(filtered_recommendations)} GaussDB-compatible ones")
        return filtered_recommendations
    
    async def _convert_to_supported_index_type(
        self, 
        recommendation: IndexRecommendation, 
        supported_types: Set[str]
    ) -> Optional[IndexRecommendation]:
        """
        Convert an unsupported index type to a supported alternative.
        
        Args:
            recommendation: Original index recommendation
            supported_types: Set of supported index types
            
        Returns:
            Converted recommendation or None if no conversion possible
        """
        original_type = recommendation.using
        
        # Define conversion mappings
        conversions = {
            'gin': 'btree',      # GIN to B-tree for text search
            'gist': 'btree',     # GIST to B-tree for geometric data
            'spgist': 'btree',   # SP-GIST to B-tree
            'brin': 'btree',     # BRIN to B-tree
        }
        
        if original_type in conversions and conversions[original_type] in supported_types:
            new_type = conversions[original_type]
            logger.info(f"Converting index type from {original_type} to {new_type}")
            
            return IndexRecommendation(
                table=recommendation.table,
                columns=recommendation.columns,
                using=new_type,
                estimated_size_bytes=recommendation.estimated_size_bytes,
                potential_problematic_reason=f"converted_from_{original_type}"
            )
        
        return None
    
    async def _check_column_type_compatibility(
        self, 
        recommendation: IndexRecommendation, 
        limitations: Dict[str, Any]
    ) -> bool:
        """
        Check if the columns in an index recommendation are compatible with the index type.
        
        Args:
            recommendation: Index recommendation to check
            limitations: GaussDB limitations dictionary
            
        Returns:
            True if columns are compatible, False otherwise
        """
        try:
            # Get column types for the table
            column_types_query = """
                SELECT column_name, data_type 
                FROM information_schema.columns 
                WHERE table_name = {}
                AND column_name = ANY({})
            """
            
            result = await self.gaussdb_driver.execute_query(
                column_types_query, 
                [recommendation.table, list(recommendation.columns)]
            )
            
            if not result:
                logger.warning(f"Could not get column types for {recommendation.table}")
                return True  # Assume compatible if we can't check
            
            # Check each column type against supported types for the index method
            supported_column_types = limitations['supported_column_types'].get(recommendation.using, [])
            
            for row in result:
                column_type = row.cells['data_type']
                if column_type not in supported_column_types:
                    logger.debug(f"Column type {column_type} not supported for {recommendation.using} index")
                    return False
            
            return True
            
        except Exception as e:
            logger.warning(f"Error checking column type compatibility: {e}")
            return True  # Assume compatible if we can't check
    
    async def _adjust_cost_for_gaussdb(
        self, 
        base_cost: float, 
        recommendation: IndexRecommendation
    ) -> float:
        """
        Adjust index cost estimation for GaussDB-specific factors.
        
        Args:
            base_cost: Base cost from PostgreSQL estimation
            recommendation: Index recommendation
            
        Returns:
            Adjusted cost for GaussDB
        """
        cost_model = self.gaussdb_cost_model
        index_type = recommendation.using
        
        # Apply index type specific cost factors
        type_factors = {
            'btree': cost_model.btree_creation_cost_factor,
            'hash': cost_model.hash_creation_cost_factor,
            'gin': cost_model.gin_creation_cost_factor,
            'gist': cost_model.gist_creation_cost_factor,
        }
        
        type_factor = type_factors.get(index_type, 1.0)
        adjusted_cost = base_cost * type_factor
        
        # Apply storage cost factor
        adjusted_cost *= cost_model.storage_cost_factor
        
        # Apply distributed index overhead if applicable
        if await self._is_distributed_environment():
            adjusted_cost *= cost_model.distributed_index_overhead
        
        logger.debug(f"Adjusted cost for {index_type} index: {base_cost} -> {adjusted_cost}")
        return adjusted_cost
    
    async def _is_distributed_environment(self) -> bool:
        """
        Check if GaussDB is running in a distributed environment.
        
        Returns:
            True if distributed, False otherwise
        """
        try:
            # Check for GaussDB distributed features
            # This is a simplified check - in practice, you'd query GaussDB-specific views
            query = """
                SELECT EXISTS (
                    SELECT 1 FROM pg_settings 
                    WHERE name LIKE '%distributed%' OR name LIKE '%cluster%'
                ) as is_distributed
            """
            
            result = await self.gaussdb_driver.execute_query(query)
            
            if result and result[0].cells.get('is_distributed'):
                return True
            
            return False
            
        except Exception as e:
            logger.debug(f"Error checking distributed environment: {e}")
            return False  # Assume non-distributed if we can't check
    
    async def _estimate_gaussdb_index_benefit(
        self, 
        recommendation: IndexRecommendation,
        query_workload: List[Tuple[str, Any, float]]
    ) -> float:
        """
        Estimate the benefit of an index recommendation in GaussDB.
        
        This method considers GaussDB-specific query optimization patterns
        and execution characteristics.
        
        Args:
            recommendation: Index recommendation to evaluate
            query_workload: List of (query, parsed_stmt, weight) tuples
            
        Returns:
            Estimated benefit score (higher is better)
        """
        try:
            # Get baseline cost without the index
            baseline_cost = await self._evaluate_configuration_cost(
                query_workload, frozenset()
            )
            
            # Get cost with the index
            with_index_cost = await self._evaluate_configuration_cost(
                query_workload, frozenset([recommendation.index_definition])
            )
            
            # Calculate raw benefit
            raw_benefit = max(0, baseline_cost - with_index_cost)
            
            # Apply GaussDB-specific adjustments
            adjusted_benefit = await self._adjust_benefit_for_gaussdb(
                raw_benefit, recommendation, query_workload
            )
            
            return adjusted_benefit
            
        except Exception as e:
            logger.warning(f"Error estimating GaussDB index benefit: {e}")
            return 0.0
    
    async def _adjust_benefit_for_gaussdb(
        self, 
        raw_benefit: float, 
        recommendation: IndexRecommendation,
        query_workload: List[Tuple[str, Any, float]]
    ) -> float:
        """
        Apply GaussDB-specific adjustments to index benefit estimation.
        
        Args:
            raw_benefit: Raw benefit calculation
            recommendation: Index recommendation
            query_workload: Query workload
            
        Returns:
            Adjusted benefit score
        """
        adjusted_benefit = raw_benefit
        
        # Adjust for index type efficiency in GaussDB
        type_efficiency = {
            'btree': 1.0,
            'hash': 0.9,   # Hash indexes may be less efficient for range queries
            'gin': 1.2,    # GIN indexes may be more efficient for text search
            'gist': 1.1,   # GIST indexes may have moderate efficiency
        }
        
        efficiency_factor = type_efficiency.get(recommendation.using, 1.0)
        adjusted_benefit *= efficiency_factor
        
        # Adjust for column selectivity in GaussDB
        selectivity_bonus = await self._calculate_gaussdb_selectivity_bonus(
            recommendation, query_workload
        )
        adjusted_benefit *= (1.0 + selectivity_bonus)
        
        # Penalize for maintenance overhead in distributed environments
        if await self._is_distributed_environment():
            maintenance_penalty = 0.1  # 10% penalty for distributed maintenance
            adjusted_benefit *= (1.0 - maintenance_penalty)
        
        return adjusted_benefit
    
    async def _calculate_gaussdb_selectivity_bonus(
        self, 
        recommendation: IndexRecommendation,
        query_workload: List[Tuple[str, Any, float]]
    ) -> float:
        """
        Calculate selectivity bonus for GaussDB index recommendations.
        
        Args:
            recommendation: Index recommendation
            query_workload: Query workload
            
        Returns:
            Selectivity bonus factor (0.0 to 0.5)
        """
        try:
            # Get column statistics for selectivity estimation
            stats_query = """
                SELECT 
                    attname,
                    n_distinct,
                    most_common_vals,
                    most_common_freqs
                FROM pg_stats 
                WHERE tablename = {} 
                AND attname = ANY({})
            """
            
            result = await self.gaussdb_driver.execute_query(
                stats_query, 
                [recommendation.table, list(recommendation.columns)]
            )
            
            if not result:
                return 0.0
            
            # Calculate selectivity based on column statistics
            total_selectivity = 0.0
            for row in result:
                n_distinct = row.cells.get('n_distinct', 1)
                if n_distinct > 0:
                    # Higher distinctness = better selectivity
                    selectivity = min(0.1, 1.0 / max(1, n_distinct))
                    total_selectivity += selectivity
            
            # Cap the bonus at 50%
            return min(0.5, total_selectivity)
            
        except Exception as e:
            logger.debug(f"Error calculating selectivity bonus: {e}")
            return 0.0
    
    async def _generate_gaussdb_specific_recommendations(
        self, 
        query_workload: List[Tuple[str, Any, float]]
    ) -> Set[IndexRecommendation]:
        """
        Generate GaussDB-specific index recommendations.
        
        This method creates recommendations that take advantage of GaussDB-specific
        features and optimization patterns.
        
        Args:
            query_workload: List of (query, parsed_stmt, weight) tuples
            
        Returns:
            Set of GaussDB-specific index recommendations
        """
        recommendations = set()
        
        try:
            # Analyze query patterns for GaussDB-specific optimizations
            patterns = await self._analyze_gaussdb_query_patterns(query_workload)
            
            # Generate recommendations based on patterns
            for pattern in patterns:
                if pattern['type'] == 'frequent_equality':
                    # Create hash index for frequent equality checks
                    rec = IndexRecommendation(
                        table=pattern['table'],
                        columns=tuple(pattern['columns']),
                        using='hash'
                    )
                    recommendations.add(rec)
                
                elif pattern['type'] == 'range_queries':
                    # Create B-tree index for range queries
                    rec = IndexRecommendation(
                        table=pattern['table'],
                        columns=tuple(pattern['columns']),
                        using='btree'
                    )
                    recommendations.add(rec)
                
                elif pattern['type'] == 'text_search':
                    # Create GIN index for text search if supported
                    supported_types = await self._get_gaussdb_supported_index_types()
                    index_type = 'gin' if 'gin' in supported_types else 'btree'
                    
                    rec = IndexRecommendation(
                        table=pattern['table'],
                        columns=tuple(pattern['columns']),
                        using=index_type
                    )
                    recommendations.add(rec)
            
            logger.info(f"Generated {len(recommendations)} GaussDB-specific recommendations")
            return recommendations
            
        except Exception as e:
            logger.warning(f"Error generating GaussDB-specific recommendations: {e}")
            return set()
    
    async def _analyze_gaussdb_query_patterns(
        self, 
        query_workload: List[Tuple[str, Any, float]]
    ) -> List[Dict[str, Any]]:
        """
        Analyze query workload for GaussDB-specific optimization patterns.
        
        Args:
            query_workload: List of (query, parsed_stmt, weight) tuples
            
        Returns:
            List of identified patterns
        """
        patterns = []
        
        try:
            # Analyze each query for patterns
            for query_text, parsed_stmt, weight in query_workload:
                # Extract table and column usage patterns
                from ..sql import ColumnCollector, TableAliasVisitor
                
                table_visitor = TableAliasVisitor()
                table_visitor(parsed_stmt)
                
                column_collector = ColumnCollector()
                column_collector(parsed_stmt)
                
                # Identify patterns based on query structure
                for table in table_visitor.tables:
                    if table in column_collector.columns:
                        columns = list(column_collector.columns[table])
                        
                        # Check for equality patterns
                        if 'WHERE' in query_text.upper() and '=' in query_text:
                            patterns.append({
                                'type': 'frequent_equality',
                                'table': table,
                                'columns': columns[:2],  # Limit to 2 columns
                                'weight': weight
                            })
                        
                        # Check for range patterns
                        if any(op in query_text.upper() for op in ['>', '<', 'BETWEEN', 'ORDER BY']):
                            patterns.append({
                                'type': 'range_queries',
                                'table': table,
                                'columns': columns[:1],  # Single column for range
                                'weight': weight
                            })
                        
                        # Check for text search patterns
                        if any(op in query_text.upper() for op in ['LIKE', 'ILIKE', '@@', 'SIMILAR TO']):
                            patterns.append({
                                'type': 'text_search',
                                'table': table,
                                'columns': columns[:1],  # Single column for text search
                                'weight': weight
                            })
            
            # Deduplicate and sort patterns by weight
            unique_patterns = {}
            for pattern in patterns:
                key = (pattern['type'], pattern['table'], tuple(pattern['columns']))
                if key not in unique_patterns or unique_patterns[key]['weight'] < pattern['weight']:
                    unique_patterns[key] = pattern
            
            return list(unique_patterns.values())
            
        except Exception as e:
            logger.warning(f"Error analyzing query patterns: {e}")
            return []