import json
import logging
import math
import os
from dataclasses import dataclass
from typing import Any
from typing import override
from typing_extensions import LiteralString
from typing import cast

from zai import ZhipuAiClient  # type: ignore
from pglast.ast import SelectStmt
from pydantic import BaseModel

from opengauss_mcp.artifacts import ErrorResult
from opengauss_mcp.explain.explain_plan import ExplainPlanTool
from opengauss_mcp.sql import TableAliasVisitor

from ..sql import IndexDefinition
from ..sql import SqlDriver
from .index_opt_base import IndexRecommendation
from .index_opt_base import IndexTuningBase

logger = logging.getLogger(__name__)


# We introduce a Pydantic index class to facilitate communication with the LLM
# via the instructor library.
class Index(BaseModel):
    table_name: str
    columns: tuple[str, ...]

    def __hash__(self):
        return hash((self.table_name, self.columns))

    def __eq__(self, other):
        if not isinstance(other, Index):
            return False
        return self.table_name == other.table_name and self.columns == other.columns

    def to_index_recommendation(self) -> IndexRecommendation:
        return IndexRecommendation(table=self.table_name, columns=self.columns)

    def to_index_definition(self) -> IndexDefinition:
        return IndexDefinition(table=self.table_name, columns=self.columns)


class IndexingAlternative(BaseModel):
    alternatives: list[set[Index]]


@dataclass
class ScoredIndexes:
    indexes: set[Index]
    execution_cost: float
    index_size: float
    objective_score: float


class LLMOptimizerTool(IndexTuningBase):
    def __init__(
        self,
        sql_driver: SqlDriver,
        max_no_progress_attempts: int = 5,
        pareto_alpha: float = 2.0,
        api_key: str | None = None,
    ):
        super().__init__(sql_driver)
        self.sql_driver = sql_driver
        self.max_no_progress_attempts = max_no_progress_attempts
        self.pareto_alpha = pareto_alpha

        # Initialize ZhipuAiClient with API key
        self.api_key = api_key or os.getenv("ZAI_API_KEY")
        if not self.api_key:
            raise ValueError(
                "ZhipuAiClient API key is required. Set ZAI_API_KEY environment variable or pass api_key parameter."
            )

        logger.info("Initialized LLMOptimizerTool with max_no_progress_attempts=%d", max_no_progress_attempts)

    def score(self, execution_cost: float, index_size: float) -> float:
        return math.log(execution_cost) + self.pareto_alpha * math.log(index_size)

    @override
    async def _generate_recommendations(self, query_weights: list[tuple[str, SelectStmt, float]]) -> tuple[set[IndexRecommendation], float]:
        """Generate index tuning queries using optimization by LLM."""
        # For now we support only one table at a time
        if len(query_weights) > 1:
            logger.error("LLM optimization currently supports only one query at a time")
            raise ValueError("Optimization by LLM supports only one query at a time.")

        query = query_weights[0][0]
        parsed_query = query_weights[0][1]
        logger.info("Generating index recommendations for query: %s", query)

        # Extract tables from the parsed query
        table_visitor = TableAliasVisitor()
        table_visitor(parsed_query)
        tables = table_visitor.tables
        logger.info("Extracted tables from query: %s", tables)

        # Get the size of the tables
        table_sizes = {}
        for table in tables:
            table_sizes[table] = await self._get_table_size(table)
        total_table_size = sum(table_sizes.values())
        logger.info("Total table size: %s", total_table_size)

        # Generate explain plan for the query
        explain_tool = ExplainPlanTool(self.sql_driver)
        explain_result = await explain_tool.explain(query)
        if isinstance(explain_result, ErrorResult):
            logger.error("Failed to generate explain plan: %s", explain_result.to_text())
            raise ValueError(f"Failed to generate explain plan: {explain_result.to_text()}")

        # Get the explain plan JSON
        explain_plan_json = explain_result.value
        logger.debug("Generated explain plan: %s", explain_plan_json)

        # Extract indexes used in the explain plan
        indexes_used: set[Index] = await self._extract_indexes_from_explain_plan_with_columns(explain_plan_json)

        # Get the current cost
        original_cost = await self._evaluate_configuration_cost(query_weights, frozenset())
        logger.info("Original query cost: %f", original_cost)

        original_config = ScoredIndexes(
            indexes=indexes_used,
            execution_cost=original_cost,
            index_size=total_table_size,
            objective_score=self.score(original_cost, total_table_size),
        )

        best_config = original_config

        # Initialize attempt history for this run
        attempt_history: list[ScoredIndexes] = [original_config]

        no_progress_count = 0

        try:
            client = ZhipuAiClient(api_key=self.api_key)
        except Exception as e:
            logger.error("Failed to initialize ZhipuAiClient: %s", str(e))
            raise ValueError(f"Failed to initialize ZhipuAiClient: {str(e)}. Please check your API key and network connection.")

        # Starting cost
        # TODO should include the size of the starting indexes
        score = self.score(original_cost, total_table_size)
        logger.info("Starting score: %f", score)

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

            try:
                response = client.chat.completions.create(
                    model="glm-4.5-flash",
                    temperature=1.2,
                    messages=[
                        {"role": "system", "content": "You are a helpful assistant that generates index recommendations for a given workload. Respond with JSON only."},
                        {
                            "role": "user",
                            "content": f"Here is the query we are optimizing: {query}\n"
                            f"Here is the explain plan: {explain_plan_json}\n"
                            f"Here are the existing indexes: {';'.join(idx.to_index_definition().definition for idx in indexes_used)}\n"
                            f"{history_prompt}\n"
                            "Each indexing suggestion that you provide is a combination of indexes. You can provide multiple alternative suggestions. "
                            "We will evaluate each alternative using virtual indexes to see how the optimizer will behave with those indexes in place. "
                            "The overall score is based on a combination of execution cost and index size. In all cases, lower is better. "
                            "Prefer fewer indexes to more indexes. Prefer indexes with fewer columns to indexes with more columns. "
                            f"{remaining_attempts_prompt}\n\n"
                            "Respond with JSON in this format:\n"
                            '{\n'
                            '  "alternatives": [\n'
                            '    [\n'
                            '      {"table_name": "table1", "columns": ["col1", "col2"]},\n'
                            '      {"table_name": "table2", "columns": ["col3"]}\n'
                            '    ]\n'
                            '  ]\n'
                            '}',
                        },
                    ],
                )
            except Exception as e:
                # Check if it's an API status error from zai
                if "APIStatusError" in str(type(e).__name__):
                    logger.error("ZhipuAiClient API status error: %s", str(e))
                    # If we've made progress already, we can continue with current best config
                    if best_config != original_config:
                        logger.warning("Using best configuration found so far due to API status error")
                        break
                    else:
                        logger.error("No improvements found and API status error occurred")
                        raise ValueError(f"API status error from ZhipuAiClient: {str(e)}")
                # Check if it's an API timeout error from zai
                elif "APITimeoutError" in str(type(e).__name__):
                    logger.error("ZhipuAiClient API timeout: %s", str(e))
                    if best_config != original_config:
                        logger.warning("Using best configuration found so far due to API timeout")
                        break
                    else:
                        logger.error("No improvements found and API timeout occurred")
                        raise ValueError(f"API timeout from ZhipuAiClient: {str(e)}")
                else:
                    logger.error("Failed to get response from ZhipuAiClient: %s", str(e))
                    # If we've made progress already, we can continue with current best config
                    if best_config != original_config:
                        logger.warning("Using best configuration found so far due to API error")
                        break
                    else:
                        logger.error("No improvements found and API call failed")
                        raise ValueError(f"Failed to get recommendations from ZhipuAiClient: {str(e)}")

            # Parse the response content
            response_content = None  # Initialize to ensure it's defined in exception handlers
            try:
                response_content = response.choices[0].message.content
                logger.debug("Raw response from ZhipuAiClient: %s", response_content)

                # Clean up response content - remove markdown code blocks if present
                if response_content.startswith("```json"):
                    response_content = response_content.replace("```json", "").replace("```", "").strip()
                elif response_content.startswith("```"):
                    response_content = response_content.replace("```", "").strip()

                # Parse JSON response
                response_data = json.loads(response_content)

                # Convert to our format
                index_alternatives: list[set[Index]] = []
                for alt in response_data.get("alternatives", []):
                    index_set = set()
                    for idx_data in alt:
                        if isinstance(idx_data, dict) and "table_name" in idx_data and "columns" in idx_data:
                            index_set.add(Index(
                                table_name=idx_data["table_name"],
                                columns=tuple(idx_data["columns"])
                            ))
                    if index_set:
                        index_alternatives.append(index_set)

                logger.info("Received %d alternative index configurations from LLM", len(index_alternatives))

            except json.JSONDecodeError as e:
                logger.error("Failed to parse JSON response from ZhipuAiClient: %s", str(e))
                if response_content is not None:
                    logger.error("Response content: %s", response_content)
                else:
                    logger.error("Response content was not available")
                # If we've made progress already, we can continue with current best config
                if best_config != original_config:
                    logger.warning("Using best configuration found so far due to JSON parsing error")
                    break
                else:
                    logger.error("No improvements found and JSON parsing failed")
                    raise ValueError(f"Failed to parse JSON response: {str(e)}")
            except Exception as e:
                logger.error("Error processing response from ZhipuAiClient: %s", str(e))
                if best_config != original_config:
                    logger.warning("Using best configuration found so far due to response processing error")
                    break
                else:
                    logger.error("No improvements found and response processing failed")
                    raise ValueError(f"Failed to process response: {str(e)}")

            # If no alternatives were generated, break the loop
            if not index_alternatives:
                logger.warning("No index alternatives were generated by the LLM")
                break

            # Try each alternative
            found_improvement = False
            for i, index_set in enumerate(index_alternatives):
                try:
                    logger.info("Evaluating alternative %d/%d with %d indexes", i + 1, len(index_alternatives), len(index_set))
                    # Evaluate this index configuration
                    execution_cost_estimate = await self._evaluate_configuration_cost(
                        query_weights, frozenset({index.to_index_definition() for index in index_set})
                    )
                    logger.info(
                        "Alternative %d cost: %f (reduction: %.2f%%)",
                        i + 1,
                        execution_cost_estimate,
                        ((best_config.execution_cost - execution_cost_estimate) / best_config.execution_cost) * 100,
                    )

                    # Estimate the size of the indexes
                    index_size_estimate = await self._estimate_index_size_2({index.to_index_definition() for index in index_set}, 1024 * 1024)
                    logger.info("Estimated index size: %f", index_size_estimate)

                    # Score based on a balance of size and performance
                    score = math.log(execution_cost_estimate) + self.pareto_alpha * math.log(total_table_size + index_size_estimate)

                    # Record this attempt in history
                    latest_config = ScoredIndexes(
                        indexes={Index(table_name=index.table_name, columns=index.columns) for index in index_set},
                        execution_cost=execution_cost_estimate,
                        index_size=index_size_estimate,
                        objective_score=score,
                    )
                    attempt_history.append(latest_config)
                    logger.info("Latest config: %s", latest_config)

                    # If this is better than what we've seen so far, update our best
                    # Minimum 2% improvement required
                    if latest_config.objective_score < best_config.objective_score:
                        best_config = latest_config
                        found_improvement = True
                except Exception as e:
                    # We discard the alternative. We are seeing this happen due to invalid index definitions.
                    logger.error("Error evaluating alternative %d/%d: %s", i + 1, len(index_alternatives), str(e))

            # Keep only the 5 best results in the attempt history
            attempt_history.sort(key=lambda x: x.objective_score)
            attempt_history = attempt_history[:5]

            if found_improvement:
                no_progress_count = 0
            else:
                no_progress_count += 1
                logger.info(
                    "No improvement found in this iteration. Attempts without progress: %d/%d", no_progress_count, self.max_no_progress_attempts
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

        # Convert Index objects to IndexConfig objects for return
        best_index_config_set = {index.to_index_recommendation() for index in best_config.indexes}
        
        # Clean up all virtual indexes after optimization
        await self.reset_all_virtual_indexes()
        
        return (best_index_config_set, best_config.execution_cost)

    async def _estimate_index_size_2(self, index_set: set[IndexDefinition], min_size_penalty: float = 1024 * 1024) -> float:
        """
        Estimate the size of a set of indexes using openGauss hypopg virtual indexes.

        Args:
            index_set: Set of IndexConfig objects representing the indexes to estimate

        Returns:
            Total estimated size of all indexes in bytes
        """
        if not index_set:
            return 0.0

        total_size = 0.0

        for index_config in index_set:
            try:
                # Create a virtual index using hypopg_create_index
                index_definition = f"{index_config.table}({','.join(index_config.columns)})"
                
                # Use hypopg_create_index to create a virtual index
                create_index_query = cast(LiteralString, f"SELECT * FROM hypopg_create_index('{index_definition}')")
                result = await self.sql_driver.execute_query(create_index_query)
                
                if result and len(result) > 0:
                    # Get the index ID from the result
                    index_id = result[0].cells.get("indexrelid")
                    
                    if index_id:
                        # Use hypopg_estimate_size to estimate the index size
                        size_query = cast(LiteralString, f"SELECT * FROM hypopg_estimate_size({index_id})")
                        size_result = await self.sql_driver.execute_query(size_query)
                        
                        if size_result and len(size_result) > 0:
                            # Extract the size from the result
                            size = size_result[0].cells.get("hypopg_estimate_size", 0)
                            total_size += max(float(size), min_size_penalty)
                            logger.debug(f"Estimated size for index {index_config.name}: {size} bytes")
                        else:
                            logger.warning(f"Failed to estimate size for index {index_config.name}")
                        
                        # Clean up the virtual index using hypopg_drop_index
                        await self.sql_driver.execute_query(cast(LiteralString, f"SELECT * FROM hypopg_drop_index({index_id})"))
                    else:
                        logger.warning(f"Failed to create virtual index for {index_config.name}")
                else:
                    logger.warning(f"Failed to create virtual index for {index_config.name}")

            except Exception as e:
                logger.error(f"Error estimating size for index {index_config.name}: {e!s}")

        return total_size
    
    async def reset_all_virtual_indexes(self) -> None:
        """
        Reset all virtual indexes using hypopg_reset_index.
        This should be called after completing the index optimization process.
        """
        try:
            # Use hypopg_reset_index to clean up all virtual indexes
            reset_query = cast(LiteralString, "SELECT * FROM hypopg_reset_index()")
            await self.sql_driver.execute_query(reset_query)
            logger.info("Successfully reset all virtual indexes")
        except Exception as e:
            logger.error(f"Error resetting virtual indexes: {e!s}")

    def _extract_indexes_from_explain_plan(self, explain_plan_json: Any) -> set[tuple[str, str]]:
        """
        Extract indexes used in the explain plan JSON.

        Args:
            explain_plan_json: The explain plan JSON from PostgreSQL

        Returns:
            A set of tuples (table_name, index_name) representing the indexes used in the plan
        """
        indexes_used = set()
        if isinstance(explain_plan_json, dict):
            plan_data = explain_plan_json.get("Plan")
            if plan_data is not None:

                def extract_indexes_from_node(node):
                    # Check if this is an index scan node
                    if node.get("Node Type") in ["Index Scan", "Index Only Scan", "Bitmap Index Scan"]:
                        if "Index Name" in node and "Relation Name" in node:
                            # Add the table name and index name
                            indexes_used.add((node["Relation Name"], node["Index Name"]))

                    # Recursively process child plans
                    if "Plans" in node:
                        for child in node["Plans"]:
                            extract_indexes_from_node(child)

                # Start extraction from the root plan
                extract_indexes_from_node(plan_data)
                logger.info("Extracted %d indexes from explain plan", len(indexes_used))

        return indexes_used

    async def _extract_indexes_from_explain_plan_with_columns(self, explain_plan_json: Any) -> set[Index]:
        """
        Extract indexes used in the explain plan JSON and populate their columns.

        Args:
            explain_plan_json: The explain plan JSON from PostgreSQL

        Returns:
            A set of Index objects representing the indexes used in the plan with their columns
        """
        # First extract the indexes without columns
        index_tuples = self._extract_indexes_from_explain_plan(explain_plan_json)

        # Now populate the columns for each index
        indexes_with_columns = set()
        for table_name, index_name in index_tuples:
            # Get the columns for this index
            columns = await self._get_index_columns(index_name)

            # Create a new Index object with the columns
            index_with_columns = Index(table_name=table_name, columns=columns)
            indexes_with_columns.add(index_with_columns)

        return indexes_with_columns

    async def _get_index_columns(self, index_name: str) -> tuple[str, ...]:
        """
        Get the columns for a specific index by querying the database.

        Args:
            index_name: The name of the index

        Returns:
            A tuple of column names in the index
        """
        try:
            # Query to get index columns
            query = """
            SELECT a.attname
            FROM pg_index i
            JOIN pg_class c ON c.oid = i.indexrelid
            JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
            WHERE c.relname = %s
            ORDER BY array_position(i.indkey, a.attnum)
            """

            result = await self.sql_driver.execute_query(query, [index_name])

            if result and len(result) > 0:
                # Extract column names from the result
                columns = [row.cells.get("attname", "") for row in result if row.cells.get("attname")]
                return tuple(columns)
            else:
                logger.warning(f"No columns found for index {index_name}")
                return tuple()

        except Exception as e:
            logger.error(f"Error getting columns for index {index_name}: {e!s}")
            return tuple()
