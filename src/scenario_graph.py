from collections import defaultdict
from .models import (
    ProcessingScenario, ColumnMapping, TableLineage, TableDependency,
    ScenarioDataFlowNode, ScenarioDataFlowEdge, ScenarioChain, LineageResult,
)
from .scenario_detector import ScenarioDetector


class ScenarioDataFlowGraph:
    def __init__(self):
        self.nodes: dict[str, ScenarioDataFlowNode] = {}
        self.edges: list[ScenarioDataFlowEdge] = []
        self.scenario_map: dict[str, list[ProcessingScenario]] = defaultdict(list)

    def build(
        self,
        table_lineage_map: dict[str, list[TableLineage]],
        column_mapping_map: dict[str, list[ColumnMapping]],
        file_results: dict[str, LineageResult],
        detector: ScenarioDetector,
    ):
        sql_scenarios: dict[str, ProcessingScenario] = {}

        for sql_file, result in file_results.items():
            scenario = detector.detect_scenario_for_sql(
                result.target_table, result.mappings, result.table_lineages
            )
            sql_scenarios[sql_file] = scenario

            target_node = self._get_or_create_node(result.target_table, scenario)

            for tl in result.table_lineages:
                source_table = f"{tl.source_schema}.{tl.source_table}" if tl.source_schema else tl.source_table
                source_scenario = self._infer_source_scenario(
                    source_table, tl, detector, scenario
                )
                source_node = self._get_or_create_node(source_table, source_scenario)
                self.edges.append(ScenarioDataFlowEdge(
                    source=source_node,
                    target=target_node,
                    filter_condition=tl.filter_condition,
                ))

            table_name = result.target_table
            if scenario.discriminator_value:
                self.scenario_map[table_name].append(scenario)

    def _get_or_create_node(self, table_name: str, scenario: ProcessingScenario) -> ScenarioDataFlowNode:
        node = ScenarioDataFlowNode(table_name=table_name, scenario=scenario)
        if node.node_id not in self.nodes:
            self.nodes[node.node_id] = node
        return self.nodes[node.node_id]

    def _infer_source_scenario(
        self,
        source_table: str,
        tl: TableLineage,
        detector: ScenarioDetector,
        writer_scenario: ProcessingScenario,
    ) -> ProcessingScenario:
        if tl.filter_condition:
            for table_key, fields in detector.discriminator_fields.items():
                table_matches = (
                    table_key == source_table
                    or table_key.endswith(f".{source_table}")
                    or source_table.endswith(f".{table_key}")
                    or table_key == tl.source_table
                )
                if not table_matches:
                    continue
                for field_name in fields:
                    value = detector._extract_equality_value(
                        tl.filter_condition, field_name, tl.source_alias
                    )
                    if value:
                        return ProcessingScenario(
                            discriminator_field=field_name,
                            discriminator_value=value,
                        )

        if writer_scenario.discriminator_value:
            for table_key in detector.discriminator_fields:
                table_matches = (
                    table_key == source_table
                    or table_key.endswith(f".{source_table}")
                    or source_table.endswith(f".{table_key}")
                )
                if table_matches:
                    return ProcessingScenario(
                        discriminator_field=writer_scenario.discriminator_field,
                        discriminator_value=writer_scenario.discriminator_value,
                    )

        return ProcessingScenario(is_shared=True)

    def get_scenario_chains(self, temp_tables: set[str]) -> list[ScenarioChain]:
        final_targets = set(self._get_all_targets()) - temp_tables
        chains: list[ScenarioChain] = []

        for target in final_targets:
            target_scenarios = self._get_scenarios_for_table(target)
            if not target_scenarios:
                target_scenarios = [ProcessingScenario(is_shared=True)]

            for scenario in target_scenarios:
                chain = self._trace_chain(target, scenario, temp_tables)
                if chain:
                    chains.append(chain)

        return chains

    def get_shared_nodes(self) -> list[ScenarioDataFlowNode]:
        return [n for n in self.nodes.values() if n.scenario.is_shared]

    def _trace_chain(
        self, target_table: str, scenario: ProcessingScenario, temp_tables: set[str]
    ) -> ScenarioChain | None:
        chain = ScenarioChain(scenario=scenario, target_tables=[target_table])
        visited = set()
        self._trace_upstream(target_table, scenario, temp_tables, chain, visited)
        return chain

    def _trace_upstream(
        self,
        table: str,
        scenario: ProcessingScenario,
        temp_tables: set[str],
        chain: ScenarioChain,
        visited: set[str],
    ):
        node_id = ScenarioDataFlowNode(table_name=table, scenario=scenario).node_id
        if node_id in visited:
            return
        visited.add(node_id)

        incoming = [e for e in self.edges if e.target.node_id == node_id]
        if not incoming and scenario.discriminator_value:
            shared_node_id = ScenarioDataFlowNode(
                table_name=table, scenario=ProcessingScenario(is_shared=True)
            ).node_id
            incoming = [e for e in self.edges if e.target.node_id == shared_node_id]

        for edge in incoming:
            source_name = edge.source.table_name
            source_scenario = edge.source.scenario

            if source_name in temp_tables:
                if source_name not in chain.intermediate_tables:
                    chain.intermediate_tables.append(source_name)
                self._trace_upstream(source_name, source_scenario, temp_tables, chain, visited)
            else:
                if source_name not in chain.source_tables:
                    chain.source_tables.append(source_name)

    def _get_all_targets(self) -> set[str]:
        targets = set()
        for edge in self.edges:
            targets.add(edge.target.table_name)
        return targets

    def _get_scenarios_for_table(self, table: str) -> list[ProcessingScenario]:
        scenarios = []
        seen_values = set()
        for node in self.nodes.values():
            if node.table_name == table and node.scenario.discriminator_value:
                key = (node.scenario.discriminator_field, node.scenario.discriminator_value)
                if key not in seen_values:
                    seen_values.add(key)
                    scenarios.append(node.scenario)
        return scenarios
