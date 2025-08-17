"""
Unit tests for GaussDB index tuning base adapter.

This module tests the GaussDB-specific extensions to index tuning functionality,
including cost model adjustments, index type filtering, and recommendation optimization.
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Set

from src.postgres_mcp.gaussdb.index_tuning_base_adapter import (
    GaussDbIndexTuningMixin,
    GaussDbIndexCostModel,
)
from src.postgres_mcp.gaussdb.sql_driver_adapter import GaussDbSqlDriver
from src.postgres_mcp.index.index_opt_base import IndexRecommendation
from src.postgres_mcp.sql import SqlDriver


class MockIndexTuningClass(GaussDbIndexTuningMixin):
    """Mock class for testing the mixin functionality."""
    
    def __init__(self, sql_driver):
        self.sql_driver = sql_driver
        super().__init__()
    
    async def _evaluate_configuration_cost(self, query_weights, indexes):
        """Mock cost evaluation."""
        return 100.0


@pytest_asyncio.fixture
async def mock_sql_driver():
    """Create a mock SQL driver for testing."""
    driver = AsyncMock(spec=SqlDriver)
    driver.get_database_type.return_value = "gaussdb"
    driver.get_database_version.return_value = "8.1.0"
    driver.execute_query.return_value = []
    return driver


@pytest_asyncio.fixture
async def mock_gaussdb_driver(mock_sql_driver):
    """Create a mock GaussDB driver for testing."""
    driver = AsyncMock(spec=GaussDbSqlDriver)
    driver.base_driver = mock_sql_driver
    driver.execute_query.return_value = []
    driver.get_database_version.return_value = "8.1.0"
    return driver


@pytest_asyncio.fixture
async def mixin_instance(mock_sql_driver):
    """Create a mixin instance for testing."""
    return MockIndexTuningClass(mock_sql_driver)


class TestGaussDbIndexCostModel:
    """Test cases for GaussDbIndexCostModel."""
    
    def test_default_cost_model(self):
        """Test default cost model parameters."""
        model = GaussDbIndexCostModel()
        
        assert model.btree_creation_cost_factor == 1.0
        assert model.hash_creation_cost_factor == 1.2
        assert model.gin_creation_cost_factor == 1.5
        assert model.gist_creation_cost_factor == 1.3
        
        assert model.btree_maintenance_cost_factor == 1.0
        assert model.hash_maintenance_cost_factor == 1.1
        
        assert model.index_scan_cost_factor == 1.0
        assert model.bitmap_scan_cost_factor == 1.1
        
        assert model.storage_cost_factor == 1.0
        assert model.distributed_index_overhead == 1.2
        assert model.replication_factor == 1
    
    def test_custom_cost_model(self):
        """Test custom cost model parameters."""
        model = GaussDbIndexCostModel(
            btree_creation_cost_factor=1.5,
            hash_creation_cost_factor=2.0,
            distributed_index_overhead=1.5,
            replication_factor=3
        )
        
        assert model.btree_creation_cost_factor == 1.5
        assert model.hash_creation_cost_factor == 2.0
        assert model.distributed_index_overhead == 1.5
        assert model.replication_factor == 3


class TestGaussDbIndexTuningMixin:
    """Test cases for GaussDbIndexTuningMixin."""
    
    def test_mixin_initialization(self, mixin_instance):
        """Test mixin initialization."""
        assert hasattr(mixin_instance, 'gaussdb_driver')
        assert hasattr(mixin_instance, 'feature_checker')
        assert hasattr(mixin_instance, 'gaussdb_cost_model')
        assert isinstance(mixin_instance.gaussdb_cost_model, GaussDbIndexCostModel)
    
    @pytest.mark.asyncio
    async def test_get_gaussdb_supported_index_types_success(self, mixin_instance):
        """Test successful retrieval of supported index types."""
        # Mock query result
        mock_result = [
            MagicMock(cells={'amname': 'btree'}),
            MagicMock(cells={'amname': 'hash'}),
            MagicMock(cells={'amname': 'gin'}),
        ]
        
        with patch.object(mixin_instance.gaussdb_driver, 'execute_query', return_value=mock_result):
            result = await mixin_instance._get_gaussdb_supported_index_types()
            
            assert result == {'btree', 'hash', 'gin'}
            assert mixin_instance._gaussdb_supported_index_types == {'btree', 'hash', 'gin'}
    
    @pytest.mark.asyncio
    async def test_get_gaussdb_supported_index_types_fallback(self, mixin_instance):
        """Test fallback when query fails."""
        with patch.object(mixin_instance.gaussdb_driver, 'execute_query', side_effect=Exception("Query failed")):
            result = await mixin_instance._get_gaussdb_supported_index_types()
            
            assert result == {'btree', 'hash'}  # Conservative default
    
    @pytest.mark.asyncio
    async def test_get_gaussdb_index_limitations_success(self, mixin_instance):
        """Test successful retrieval of index limitations."""
        with patch.object(mixin_instance.gaussdb_driver, 'get_database_version', return_value="8.1.0"):
            result = await mixin_instance._get_gaussdb_index_limitations()
            
            assert 'max_index_columns' in result
            assert 'supported_column_types' in result
            assert 'version' in result
            assert result['version'] == "8.1.0"
            assert 'partial_indexes_on_expressions' in result['unsupported_features']
    
    @pytest.mark.asyncio
    async def test_get_gaussdb_index_limitations_fallback(self, mixin_instance):
        """Test fallback when version query fails."""
        with patch.object(mixin_instance.gaussdb_driver, 'get_database_version', side_effect=Exception("Version query failed")):
            result = await mixin_instance._get_gaussdb_index_limitations()
            
            assert result['max_index_columns'] == 16  # Conservative limit
            assert result['version'] == 'unknown'
            assert 'gin' in result['unsupported_features']
    
    @pytest.mark.asyncio
    async def test_filter_recommendations_for_gaussdb(self, mixin_instance):
        """Test filtering recommendations for GaussDB compatibility."""
        # Mock supported types and limitations
        with patch.object(mixin_instance, '_get_gaussdb_supported_index_types', return_value={'btree', 'hash'}):
            with patch.object(mixin_instance, '_get_gaussdb_index_limitations', return_value={
                'max_index_columns': 3,
                'max_index_name_length': 63,
                'supported_column_types': {
                    'btree': ['integer', 'text'],
                    'hash': ['integer', 'text']
                }
            }):
                with patch.object(mixin_instance, '_check_column_type_compatibility', return_value=True):
                    
                    recommendations = {
                        IndexRecommendation('users', ('id',), 'btree'),
                        IndexRecommendation('users', ('email',), 'gin'),  # Unsupported type
                        IndexRecommendation('users', ('a', 'b', 'c', 'd'), 'btree'),  # Too many columns
                    }
                    
                    with patch.object(mixin_instance, '_convert_to_supported_index_type', 
                                    return_value=IndexRecommendation('users', ('email',), 'btree')):
                        
                        result = await mixin_instance._filter_recommendations_for_gaussdb(recommendations)
                        
                        # Should have 2 recommendations: original btree + converted gin->btree
                        assert len(result) == 2
                        # Check that all results use supported index types
                        for rec in result:
                            assert rec.using in {'btree', 'hash'}
    
    @pytest.mark.asyncio
    async def test_convert_to_supported_index_type(self, mixin_instance):
        """Test conversion of unsupported index types."""
        original_rec = IndexRecommendation('users', ('content',), 'gin')
        supported_types = {'btree', 'hash'}
        
        result = await mixin_instance._convert_to_supported_index_type(original_rec, supported_types)
        
        assert result is not None
        assert result.using == 'btree'
        assert result.table == 'users'
        assert result.columns == ('content',)
        assert result.potential_problematic_reason == 'converted_from_gin'
    
    @pytest.mark.asyncio
    async def test_convert_to_supported_index_type_no_conversion(self, mixin_instance):
        """Test when no conversion is possible."""
        original_rec = IndexRecommendation('users', ('geometry',), 'unsupported_type')
        supported_types = {'btree', 'hash'}
        
        result = await mixin_instance._convert_to_supported_index_type(original_rec, supported_types)
        
        assert result is None
    
    @pytest.mark.asyncio
    async def test_check_column_type_compatibility_success(self, mixin_instance):
        """Test successful column type compatibility check."""
        recommendation = IndexRecommendation('users', ('id', 'email'), 'btree')
        limitations = {
            'supported_column_types': {
                'btree': ['integer', 'text', 'varchar']
            }
        }
        
        # Mock query result
        mock_result = [
            MagicMock(cells={'column_name': 'id', 'data_type': 'integer'}),
            MagicMock(cells={'column_name': 'email', 'data_type': 'varchar'}),
        ]
        
        with patch.object(mixin_instance.gaussdb_driver, 'execute_query', return_value=mock_result):
            result = await mixin_instance._check_column_type_compatibility(recommendation, limitations)
            
            assert result is True
    
    @pytest.mark.asyncio
    async def test_check_column_type_compatibility_failure(self, mixin_instance):
        """Test column type compatibility check failure."""
        recommendation = IndexRecommendation('users', ('data',), 'btree')
        limitations = {
            'supported_column_types': {
                'btree': ['integer', 'text']
            }
        }
        
        # Mock query result with unsupported type
        mock_result = [
            MagicMock(cells={'column_name': 'data', 'data_type': 'jsonb'}),
        ]
        
        with patch.object(mixin_instance.gaussdb_driver, 'execute_query', return_value=mock_result):
            result = await mixin_instance._check_column_type_compatibility(recommendation, limitations)
            
            assert result is False
    
    @pytest.mark.asyncio
    async def test_adjust_cost_for_gaussdb(self, mixin_instance):
        """Test cost adjustment for GaussDB."""
        recommendation = IndexRecommendation('users', ('email',), 'hash')
        base_cost = 100.0
        
        # Mock distributed environment check
        with patch.object(mixin_instance, '_is_distributed_environment', return_value=True):
            result = await mixin_instance._adjust_cost_for_gaussdb(base_cost, recommendation)
            
            # Should apply hash cost factor (1.2) * storage factor (1.0) * distributed overhead (1.2)
            expected_cost = 100.0 * 1.2 * 1.0 * 1.2  # 144.0
            assert result == expected_cost
    
    @pytest.mark.asyncio
    async def test_is_distributed_environment_true(self, mixin_instance):
        """Test distributed environment detection - positive case."""
        mock_result = [MagicMock(cells={'is_distributed': True})]
        with patch.object(mixin_instance.gaussdb_driver, 'execute_query', return_value=mock_result):
            result = await mixin_instance._is_distributed_environment()
            
            assert result is True
    
    @pytest.mark.asyncio
    async def test_is_distributed_environment_false(self, mixin_instance):
        """Test distributed environment detection - negative case."""
        mock_result = [MagicMock(cells={'is_distributed': False})]
        with patch.object(mixin_instance.gaussdb_driver, 'execute_query', return_value=mock_result):
            result = await mixin_instance._is_distributed_environment()
            
            assert result is False
    
    @pytest.mark.asyncio
    async def test_is_distributed_environment_error(self, mixin_instance):
        """Test distributed environment detection - error case."""
        with patch.object(mixin_instance.gaussdb_driver, 'execute_query', side_effect=Exception("Query failed")):
            result = await mixin_instance._is_distributed_environment()
            
            assert result is False  # Default to non-distributed on error
    
    @pytest.mark.asyncio
    async def test_estimate_gaussdb_index_benefit(self, mixin_instance):
        """Test GaussDB index benefit estimation."""
        recommendation = IndexRecommendation('users', ('email',), 'btree')
        query_workload = [("SELECT * FROM users WHERE email = 'test'", None, 1.0)]
        
        # Mock cost evaluation
        with patch.object(mixin_instance, '_evaluate_configuration_cost', side_effect=[150.0, 100.0]):  # baseline, with_index
            with patch.object(mixin_instance, '_adjust_benefit_for_gaussdb', return_value=60.0):
                
                result = await mixin_instance._estimate_gaussdb_index_benefit(recommendation, query_workload)
                
                assert result == 60.0
    
    @pytest.mark.asyncio
    async def test_adjust_benefit_for_gaussdb(self, mixin_instance):
        """Test benefit adjustment for GaussDB."""
        recommendation = IndexRecommendation('users', ('email',), 'gin')
        query_workload = [("SELECT * FROM users WHERE email LIKE '%test%'", None, 1.0)]
        raw_benefit = 50.0
        
        # Mock selectivity calculation and distributed environment check
        with patch.object(mixin_instance, '_calculate_gaussdb_selectivity_bonus', return_value=0.2):
            with patch.object(mixin_instance, '_is_distributed_environment', return_value=True):
                
                result = await mixin_instance._adjust_benefit_for_gaussdb(
                    raw_benefit, recommendation, query_workload
                )
                
                # Should apply: 50.0 * 1.2 (gin efficiency) * 1.2 (selectivity) * 0.9 (distributed penalty)
                expected = 50.0 * 1.2 * 1.2 * 0.9  # 64.8
                assert result == expected
    
    @pytest.mark.asyncio
    async def test_calculate_gaussdb_selectivity_bonus(self, mixin_instance):
        """Test selectivity bonus calculation."""
        recommendation = IndexRecommendation('users', ('email',), 'btree')
        query_workload = []
        
        # Mock statistics query result
        mock_result = [
            MagicMock(cells={
                'attname': 'email',
                'n_distinct': 1000,
                'most_common_vals': None,
                'most_common_freqs': None
            })
        ]
        
        with patch.object(mixin_instance.gaussdb_driver, 'execute_query', return_value=mock_result):
            result = await mixin_instance._calculate_gaussdb_selectivity_bonus(recommendation, query_workload)
            
            # Should calculate selectivity based on n_distinct
            assert result > 0.0
            assert result <= 0.5  # Capped at 50%
    
    @pytest.mark.asyncio
    async def test_generate_gaussdb_specific_recommendations(self, mixin_instance):
        """Test generation of GaussDB-specific recommendations."""
        query_workload = [
            ("SELECT * FROM users WHERE id = 1", None, 1.0),
            ("SELECT * FROM users WHERE name LIKE '%test%'", None, 0.5),
        ]
        
        # Mock pattern analysis
        patterns = [
            {'type': 'frequent_equality', 'table': 'users', 'columns': ['id'], 'weight': 1.0},
            {'type': 'text_search', 'table': 'users', 'columns': ['name'], 'weight': 0.5},
        ]
        
        with patch.object(mixin_instance, '_analyze_gaussdb_query_patterns', return_value=patterns):
            with patch.object(mixin_instance, '_get_gaussdb_supported_index_types', return_value={'btree', 'hash', 'gin'}):
                
                result = await mixin_instance._generate_gaussdb_specific_recommendations(query_workload)
                
                assert len(result) == 2
                # Check that recommendations match patterns
                rec_list = list(result)
                assert any(rec.using == 'hash' and rec.columns == ('id',) for rec in rec_list)
                assert any(rec.using == 'gin' and rec.columns == ('name',) for rec in rec_list)
    
    @pytest.mark.asyncio
    async def test_analyze_gaussdb_query_patterns(self, mixin_instance):
        """Test analysis of query patterns for GaussDB optimization."""
        # Mock query workload with parsed statements
        from pglast.ast import SelectStmt
        query_workload = [
            ("SELECT * FROM users WHERE id = 1", SelectStmt(), 1.0),
            ("SELECT * FROM users WHERE name > 'A' ORDER BY name", SelectStmt(), 0.8),
            ("SELECT * FROM users WHERE description LIKE '%test%'", SelectStmt(), 0.6),
        ]
        
        # Mock table and column visitors
        with patch('src.postgres_mcp.sql.TableAliasVisitor') as mock_table_visitor:
            with patch('src.postgres_mcp.sql.ColumnCollector') as mock_column_collector:
                
                # Setup mock visitors
                mock_table_instance = MagicMock()
                mock_table_instance.tables = ['users']
                mock_table_visitor.return_value = mock_table_instance
                
                mock_column_instance = MagicMock()
                mock_column_instance.columns = {'users': ['id', 'name', 'description']}
                mock_column_collector.return_value = mock_column_instance
                
                result = await mixin_instance._analyze_gaussdb_query_patterns(query_workload)
                
                assert len(result) > 0
                # Check that different pattern types are identified
                pattern_types = {pattern['type'] for pattern in result}
                assert 'frequent_equality' in pattern_types or 'range_queries' in pattern_types or 'text_search' in pattern_types


class TestIntegration:
    """Integration tests for GaussDB index tuning base adapter."""
    
    @pytest.mark.asyncio
    async def test_mixin_with_mock_tuning_class(self, mock_sql_driver):
        """Test that the mixin works correctly with a mock tuning class."""
        instance = MockIndexTuningClass(mock_sql_driver)
        
        # Test that all mixin methods are available
        assert hasattr(instance, '_get_gaussdb_supported_index_types')
        assert hasattr(instance, '_filter_recommendations_for_gaussdb')
        assert hasattr(instance, '_adjust_cost_for_gaussdb')
        assert hasattr(instance, '_generate_gaussdb_specific_recommendations')
        
        # Test that the cost model is initialized
        assert isinstance(instance.gaussdb_cost_model, GaussDbIndexCostModel)
    
    @pytest.mark.asyncio
    async def test_end_to_end_recommendation_filtering(self, mock_sql_driver):
        """Test end-to-end recommendation filtering process."""
        instance = MockIndexTuningClass(mock_sql_driver)
        
        # Create test recommendations
        recommendations = {
            IndexRecommendation('users', ('id',), 'btree'),
            IndexRecommendation('users', ('content',), 'gin'),
            IndexRecommendation('users', ('a', 'b', 'c', 'd', 'e'), 'btree'),  # Too many columns
        }
        
        # Mock all the dependencies
        with patch.object(instance, '_get_gaussdb_supported_index_types', return_value={'btree', 'hash'}):
            with patch.object(instance, '_get_gaussdb_index_limitations', return_value={
                'max_index_columns': 3,
                'max_index_name_length': 63,
                'supported_column_types': {'btree': ['integer', 'text'], 'hash': ['integer', 'text']}
            }):
                with patch.object(instance, '_check_column_type_compatibility', return_value=True):
                    with patch.object(instance, '_convert_to_supported_index_type', 
                                    return_value=IndexRecommendation('users', ('content',), 'btree')):
                        
                        result = await instance._filter_recommendations_for_gaussdb(recommendations)
                        
                        # Should filter out the index with too many columns
                        # Should convert gin to btree
                        # Should keep the original btree index
                        assert len(result) == 2
                        
                        # All results should use supported types
                        for rec in result:
                            assert rec.using in {'btree', 'hash'}
                            assert len(rec.columns) <= 3