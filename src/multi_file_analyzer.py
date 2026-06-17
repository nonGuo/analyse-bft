import os
import re
from typing import Optional
import sqlglot
from sqlglot import exp
from .models import (
    ColumnMapping, TableDependency, LineageResult, TableLineage, ParseResult,
    ProcessingScenario,
)
from .preprocessor import preprocess_sql
from .lineage_analyzer import LineageAnalyzer
from .metadata_provider import MetadataProvider
from .ai_rewriter import AIRewriter, AIRewriterConfig
from .scenario_detector import ScenarioDetector
from .scenario_graph import ScenarioDataFlowGraph


class MultiFileAnalyzer:
    def __init__(self, metadata_provider: Optional[MetadataProvider] = None,
                 enable_ai: bool = False, ai_config_file: str = "ai_config.json"):
        self.metadata_provider = metadata_provider
        self.analyzer = LineageAnalyzer(metadata_provider)
        self.all_results: list[tuple[str, LineageResult]] = []
        self.table_lineage_map = {}
        self.column_mapping_map = {}
        self.scenario_annotations: dict[str, list[ProcessingScenario]] = {}

        self.ai_config = AIRewriterConfig(ai_config_file)
        if enable_ai or self.ai_config.is_enabled():
            self.ai_rewriter = self.ai_config.get_rewriter()
        else:
            self.ai_rewriter = None

    def parse_directory(self, directory: str) -> ParseResult:
        sql_files = self._get_sorted_sql_files(directory)

        if not sql_files:
            return ParseResult(errors=[f"No SQL files found in {directory}"])

        for sql_file in sql_files:
            self._parse_single_file(sql_file)

        detector = ScenarioDetector()
        detector.discover_discriminator_fields(self.column_mapping_map)
        self.detector = detector

        file_results_map = {}
        for sql_file, result in self.all_results:
            file_results_map[f"{sql_file}::{result.target_table}"] = result

        self.scenario_graph = ScenarioDataFlowGraph()
        self.scenario_graph.build(
            self.table_lineage_map, self.column_mapping_map,
            file_results_map, detector,
        )

        merged_result = self._merge_lineage_with_scenarios(detector)
        return merged_result

    def _get_sorted_sql_files(self, directory: str) -> list[str]:
        sql_files = []
        for filename in os.listdir(directory):
            if filename.endswith('.sql'):
                match = re.match(r'^(\d+)_(.+)\.sql$', filename)
                if match:
                    order = int(match.group(1))
                    sql_files.append((order, os.path.join(directory, filename)))

        sql_files.sort(key=lambda x: x[0])
        return [f[1] for f in sql_files]

    def _parse_single_file(self, sql_file: str):
        try:
            with open(sql_file, 'r', encoding='utf-8') as f:
                sql_content = f.read()

            statements = preprocess_sql(sql_content)

            for stmt in statements:
                result = self.analyzer.parse(stmt)
                if result.target_table:
                    self.all_results.append((sql_file, result))

                    if result.target_table not in self.table_lineage_map:
                        self.table_lineage_map[result.target_table] = []
                    self.table_lineage_map[result.target_table].extend(result.table_lineages)

                    if result.target_table not in self.column_mapping_map:
                        self.column_mapping_map[result.target_table] = []
                    self.column_mapping_map[result.target_table].extend(result.mappings)
        except Exception as e:
            print(f"Error parsing {sql_file}: {e}")

    def _merge_lineage_with_scenarios(self, detector: ScenarioDetector) -> ParseResult:
        temp_tables = self._identify_temp_tables()

        self._annotate_scenarios(detector)

        scenario_groups: dict[str, list[ColumnMapping]] = {}
        scenario_tl_groups: dict[str, list[TableLineage]] = {}

        for target_table, mappings in self.column_mapping_map.items():
            for mapping in mappings:
                key = self._scenario_group_key(target_table, mapping.scenario)
                if key not in scenario_groups:
                    scenario_groups[key] = []
                scenario_groups[key].append(mapping)

        for target_table, lineages in self.table_lineage_map.items():
            for tl in lineages:
                key = self._scenario_group_key(target_table, tl.scenario)
                if key not in scenario_tl_groups:
                    scenario_tl_groups[key] = []
                scenario_tl_groups[key].append(tl)

        merged_mappings = []
        merged_table_lineages = []
        merged_dependencies = []

        processed_targets = set()

        for group_key, mappings in scenario_groups.items():
            target_table = group_key.split("::")[0]
            if target_table in temp_tables:
                continue

            merged_column_mappings = self._merge_column_mappings(mappings, temp_tables)
            merged_mappings.extend(merged_column_mappings)
            processed_targets.add(group_key)

        for group_key, lineages in scenario_tl_groups.items():
            target_table = group_key.split("::")[0]
            if target_table in temp_tables:
                continue

            merged_tl_list = self._merge_table_lineages(lineages, temp_tables)
            merged_table_lineages.extend(merged_tl_list)

            for tl in merged_tl_list:
                full_source = f"{tl.source_schema}.{tl.source_table}" if tl.source_schema else tl.source_table
                full_target = f"{tl.target_schema}.{tl.target_table}" if tl.target_schema else tl.target_table
                dep = TableDependency(source_table=full_source, target_table=full_target)
                if dep not in merged_dependencies:
                    merged_dependencies.append(dep)

        lineage_result = LineageResult(
            target_table="",
            mappings=merged_mappings,
            dependencies=merged_dependencies,
            table_lineages=merged_table_lineages,
            warnings=[]
        )

        return ParseResult(lineage_results=[lineage_result])

    def _scenario_group_key(self, target_table: str, scenario: ProcessingScenario) -> str:
        if scenario.is_shared or not scenario.discriminator_value:
            return f"{target_table}::shared"
        return f"{target_table}::{scenario.discriminator_field}={scenario.discriminator_value}"

    def _annotate_scenarios(self, detector: ScenarioDetector):
        new_column_mapping_map: dict[str, list[ColumnMapping]] = {}
        new_table_lineage_map: dict[str, list[TableLineage]] = {}

        for sql_file, result in self.all_results:
            scenario = detector.detect_scenario_for_sql(
                result.target_table, result.mappings, result.table_lineages
            )

            annotated_mappings = []
            for mapping in result.mappings:
                annotated = ColumnMapping(
                    target_schema=mapping.target_schema,
                    target_table=mapping.target_table,
                    target_column=mapping.target_column,
                    source_schemas=mapping.source_schemas,
                    source_tables=mapping.source_tables,
                    source_aliases=mapping.source_aliases,
                    source_columns=mapping.source_columns,
                    transformation_rule=mapping.transformation_rule,
                    data_type=mapping.data_type,
                    processing_scenario=mapping.processing_scenario,
                    group_id=mapping.group_id,
                    scenario=scenario,
                )
                annotated_mappings.append(annotated)

            if result.target_table not in new_column_mapping_map:
                new_column_mapping_map[result.target_table] = []
            new_column_mapping_map[result.target_table].extend(annotated_mappings)

            annotated_lineages = []
            for tl in result.table_lineages:
                annotated_tl = TableLineage(
                    target_schema=tl.target_schema,
                    target_table=tl.target_table,
                    source_schema=tl.source_schema,
                    source_table=tl.source_table,
                    source_alias=tl.source_alias,
                    join_type=tl.join_type,
                    join_condition=tl.join_condition,
                    filter_condition=tl.filter_condition,
                    is_cte_resolved=tl.is_cte_resolved,
                    group_id=tl.group_id,
                    scenario=scenario,
                )
                annotated_lineages.append(annotated_tl)

            if result.target_table not in new_table_lineage_map:
                new_table_lineage_map[result.target_table] = []
            new_table_lineage_map[result.target_table].extend(annotated_lineages)

        self.column_mapping_map = new_column_mapping_map
        self.table_lineage_map = new_table_lineage_map

    def _identify_temp_tables(self) -> set[str]:
        target_tables = set(self.table_lineage_map.keys())

        source_tables = set()
        for target_table, table_lineages in self.table_lineage_map.items():
            for tl in table_lineages:
                full_name = f"{tl.source_schema}.{tl.source_table}" if tl.source_schema else tl.source_table
                source_tables.add(full_name)
                source_tables.add(tl.source_table)

        temp_tables = target_tables & source_tables

        temp_table_names = set()
        for temp_table in temp_tables:
            if '.' in temp_table:
                temp_table_names.add(temp_table.split('.')[-1])
            temp_table_names.add(temp_table)

        return temp_table_names

    def _merge_column_mappings(self, mappings: list[ColumnMapping], temp_tables: set[str]) -> list[ColumnMapping]:
        merged_mappings = []

        for mapping in mappings:
            merged_mapping = self._trace_column_through_temp_tables(mapping, temp_tables)
            merged_mappings.append(merged_mapping)

        return merged_mappings

    def _find_temp_mapping_for_scenario(
        self, src_table: str, src_col_name: str, scenario: ProcessingScenario
    ) -> ColumnMapping | None:
        temp_mapping_key = None
        if src_table in self.column_mapping_map:
            temp_mapping_key = src_table
        else:
            table_name = src_table.split('.')[-1] if '.' in src_table else src_table
            for key in self.column_mapping_map.keys():
                if key.endswith(f".{table_name}") or key == table_name:
                    temp_mapping_key = key
                    break

        if not temp_mapping_key:
            return None

        temp_mappings = self.column_mapping_map[temp_mapping_key]

        scenario_matched = [
            m for m in temp_mappings
            if m.target_column == src_col_name
            and m.scenario.discriminator_value == scenario.discriminator_value
            and m.scenario.discriminator_field == scenario.discriminator_field
        ]
        if scenario_matched:
            return scenario_matched[0]

        shared_matched = [
            m for m in temp_mappings
            if m.target_column == src_col_name and m.scenario.is_shared
        ]
        if shared_matched:
            return shared_matched[0]

        for temp_mapping in temp_mappings:
            if temp_mapping.target_column == src_col_name:
                return temp_mapping

        return None

    def _trace_column_through_temp_tables(self, mapping: ColumnMapping, temp_tables: set[str]) -> ColumnMapping:
        current_mapping = mapping

        max_iterations = 10
        iteration = 0

        while iteration < max_iterations:
            has_temp_source = False

            for src_table in current_mapping.source_tables:
                table_name = src_table.split('.')[-1] if '.' in src_table else src_table
                if table_name in temp_tables or src_table in temp_tables:
                    has_temp_source = True
                    break

            if not has_temp_source:
                break

            new_source_tables = []
            new_source_schemas = []
            new_source_columns = []
            new_transformation = current_mapping.transformation_rule

            for idx, src_table in enumerate(current_mapping.source_tables):
                table_name = src_table.split('.')[-1] if '.' in src_table else src_table
                is_temp = table_name in temp_tables or src_table in temp_tables

                if is_temp:
                    src_col_name = None
                    if idx < len(current_mapping.source_columns):
                        src_col = current_mapping.source_columns[idx]
                        if '.' in src_col:
                            src_col_name = src_col.split('.')[-1]
                        else:
                            src_col_name = src_col

                    if src_col_name:
                        temp_mapping = self._find_temp_mapping_for_scenario(
                            src_table, src_col_name, current_mapping.scenario
                        )

                        if temp_mapping:
                            new_source_tables.extend(temp_mapping.source_tables)
                            new_source_schemas.extend(temp_mapping.source_schemas)
                            new_source_columns.extend(temp_mapping.source_columns)

                            pattern_with_alias = r'\b[a-zA-Z_][a-zA-Z0-9_]*\.' + re.escape(src_col_name) + r'\b'
                            pattern_without_alias = r'\b' + re.escape(src_col_name) + r'\b'

                            has_column_ref = (re.search(pattern_with_alias, new_transformation) or
                                             re.search(pattern_without_alias, new_transformation))

                            if has_column_ref and temp_mapping.transformation_rule:
                                if self.ai_rewriter:
                                    try:
                                        new_transformation = self.ai_rewriter.rewrite_column_transformation(
                                            temp_mapping.transformation_rule,
                                            new_transformation,
                                            src_col_name
                                        )
                                    except Exception as e:
                                        print(f"Warning: AI transformation rewrite failed: {e}")
                                        if re.search(pattern_with_alias, new_transformation):
                                            new_transformation = re.sub(pattern_with_alias, temp_mapping.transformation_rule, new_transformation)
                                        elif re.search(pattern_without_alias, new_transformation):
                                            new_transformation = re.sub(pattern_without_alias, temp_mapping.transformation_rule, new_transformation)
                                else:
                                    if re.search(pattern_with_alias, new_transformation):
                                        new_transformation = re.sub(pattern_with_alias, temp_mapping.transformation_rule, new_transformation)
                                    elif re.search(pattern_without_alias, new_transformation):
                                        new_transformation = re.sub(pattern_without_alias, temp_mapping.transformation_rule, new_transformation)
                        else:
                            if src_table not in new_source_tables:
                                new_source_tables.append(src_table)
                            if idx < len(current_mapping.source_columns):
                                col = current_mapping.source_columns[idx]
                                if col not in new_source_columns:
                                    new_source_columns.append(col)
                    else:
                        if src_table not in new_source_tables:
                            new_source_tables.append(src_table)
                        if idx < len(current_mapping.source_columns):
                            col = current_mapping.source_columns[idx]
                            if col not in new_source_columns:
                                new_source_columns.append(col)
                else:
                    if src_table not in new_source_tables:
                        new_source_tables.append(src_table)
                    if idx < len(current_mapping.source_schemas):
                        schema = current_mapping.source_schemas[idx]
                        if schema and schema not in new_source_schemas:
                            new_source_schemas.append(schema)
                    if idx < len(current_mapping.source_columns):
                        col = current_mapping.source_columns[idx]
                        if col not in new_source_columns:
                            new_source_columns.append(col)

            current_mapping = ColumnMapping(
                target_schema=current_mapping.target_schema,
                target_table=current_mapping.target_table,
                target_column=current_mapping.target_column,
                source_schemas=list(dict.fromkeys(new_source_schemas)),
                source_tables=list(dict.fromkeys(new_source_tables)),
                source_aliases=current_mapping.source_aliases,
                source_columns=list(dict.fromkeys(new_source_columns)),
                transformation_rule=new_transformation,
                data_type=current_mapping.data_type,
                processing_scenario=current_mapping.processing_scenario,
                group_id=current_mapping.group_id,
                scenario=current_mapping.scenario,
            )

            iteration += 1

        return current_mapping

    def _merge_table_lineages(self, table_lineages: list[TableLineage], temp_tables: set[str]) -> list[TableLineage]:
        merged_lineages = []

        for tl in table_lineages:
            full_source = f"{tl.source_schema}.{tl.source_table}" if tl.source_schema else tl.source_table
            table_name = tl.source_table.split('.')[-1] if '.' in tl.source_table else tl.source_table

            is_temp = table_name in temp_tables or tl.source_table in temp_tables or full_source in temp_tables

            temp_lineage_key = None
            if tl.source_table in self.table_lineage_map:
                temp_lineage_key = tl.source_table
            else:
                for key in self.table_lineage_map.keys():
                    if key.endswith(f".{table_name}") or key == table_name:
                        temp_lineage_key = key
                        break

            if is_temp and temp_lineage_key:
                temp_lineages = self._filter_temp_lineages_by_scenario(
                    self.table_lineage_map[temp_lineage_key], tl.scenario
                )

                temp_column_mappings = self._filter_mappings_by_scenario(
                    self.column_mapping_map.get(temp_lineage_key, []), tl.scenario
                )

                for temp_tl in temp_lineages:
                    rewritten_filter = self._rewrite_filter_condition(
                        tl.filter_condition,
                        temp_column_mappings,
                        temp_tl.filter_condition
                    )

                    merged_tl = TableLineage(
                        target_schema=tl.target_schema,
                        target_table=tl.target_table,
                        source_schema=temp_tl.source_schema,
                        source_table=temp_tl.source_table,
                        source_alias=temp_tl.source_alias,
                        join_type=tl.join_type if temp_tl.join_type == "FROM" else temp_tl.join_type,
                        join_condition=tl.join_condition or temp_tl.join_condition,
                        filter_condition=rewritten_filter,
                        is_cte_resolved=temp_tl.is_cte_resolved,
                        group_id=tl.group_id,
                        scenario=tl.scenario,
                    )
                    merged_lineages.append(merged_tl)
            else:
                merged_lineages.append(tl)

        return merged_lineages

    def _filter_temp_lineages_by_scenario(
        self, lineages: list[TableLineage], scenario: ProcessingScenario
    ) -> list[TableLineage]:
        if not scenario.discriminator_value:
            return lineages

        matched = [
            tl for tl in lineages
            if tl.scenario.discriminator_value == scenario.discriminator_value
            and tl.scenario.discriminator_field == scenario.discriminator_field
        ]
        if matched:
            return matched

        shared = [tl for tl in lineages if tl.scenario.is_shared]
        if shared:
            return shared

        return lineages

    def _filter_mappings_by_scenario(
        self, mappings: list[ColumnMapping], scenario: ProcessingScenario
    ) -> list[ColumnMapping]:
        if not scenario.discriminator_value:
            return mappings

        matched = [
            m for m in mappings
            if m.scenario.discriminator_value == scenario.discriminator_value
            and m.scenario.discriminator_field == scenario.discriminator_field
        ]
        if matched:
            return matched

        shared = [m for m in mappings if m.scenario.is_shared]
        if shared:
            return shared

        return mappings

    def _rewrite_filter_condition(self, downstream_filter: str,
                                  temp_column_mappings: list[ColumnMapping],
                                  upstream_filter: str) -> str:
        if not downstream_filter:
            return upstream_filter

        if not temp_column_mappings:
            return self._merge_filter_conditions(upstream_filter, downstream_filter)

        column_transform_map = {}
        for mapping in temp_column_mappings:
            if mapping.transformation_rule and mapping.transformation_rule != mapping.target_column:
                column_transform_map[mapping.target_column] = mapping.transformation_rule

        if not column_transform_map:
            return self._merge_filter_conditions(upstream_filter, downstream_filter)

        is_complex = self._is_complex_filter(downstream_filter, column_transform_map)

        if is_complex and self.ai_rewriter:
            try:
                mappings_dict = [
                    {
                        'target_column': m.target_column,
                        'transformation_rule': m.transformation_rule
                    }
                    for m in temp_column_mappings
                ]

                return self.ai_rewriter.rewrite_filter_condition(
                    downstream_filter,
                    mappings_dict,
                    upstream_filter
                )
            except Exception as e:
                print(f"Warning: AI rewrite failed, falling back to rules: {e}")

        try:
            rewritten_filter = downstream_filter
            for col_name, transform_expr in column_transform_map.items():
                pattern_with_alias = r'\b[a-zA-Z_][a-zA-Z0-9_]*\.' + re.escape(col_name) + r'\b'
                pattern_without_alias = r'\b' + re.escape(col_name) + r'\b'

                if '(' in transform_expr or '*' in transform_expr or '/' in transform_expr or '+' in transform_expr or '-' in transform_expr:
                    replacement = f"({transform_expr})"
                else:
                    replacement = transform_expr

                if re.search(pattern_with_alias, rewritten_filter):
                    rewritten_filter = re.sub(pattern_with_alias, replacement, rewritten_filter)
                elif re.search(pattern_without_alias, rewritten_filter):
                    rewritten_filter = re.sub(pattern_without_alias, replacement, rewritten_filter)

            return self._merge_filter_conditions(upstream_filter, rewritten_filter)
        except Exception as e:
            print(f"Warning: Failed to rewrite filter condition: {e}")
            return self._merge_filter_conditions(upstream_filter, downstream_filter)

    def _is_complex_filter(self, filter_condition: str, column_transform_map: dict) -> bool:
        complexity_indicators = [
            'CASE', 'WHEN', 'THEN', 'ELSE', 'END',
            'EXISTS', 'IN (', 'BETWEEN',
            'LIKE', 'REGEXP',
            'SUBSTR', 'SUBSTRING', 'CHARINDEX',
            'DATEADD', 'DATEDIFF', 'DATE_PART',
            'CAST(', 'CONVERT(',
            'COALESCE', 'NVL', 'IFNULL',
            'DECODE',
        ]

        filter_upper = filter_condition.upper()
        for indicator in complexity_indicators:
            if indicator in filter_upper:
                return True

        for col_name, transform_expr in column_transform_map.items():
            if transform_expr.count('(') > 1:
                return True
            if 'CASE' in transform_expr.upper():
                return True
            if transform_expr.count('*') + transform_expr.count('/') + transform_expr.count('+') + transform_expr.count('-') > 2:
                return True

        return False

    def _merge_filter_conditions(self, filter1: str, filter2: str) -> str:
        if not filter1 and not filter2:
            return ""
        if not filter1:
            return filter2
        if not filter2:
            return filter1
        return f"{filter1} AND {filter2}"
