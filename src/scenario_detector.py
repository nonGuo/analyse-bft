import re
from collections import defaultdict
from .models import ProcessingScenario, ColumnMapping, TableLineage, LineageResult


class ScenarioDetector:
    def __init__(self):
        self.discriminator_fields: dict[str, dict[str, set[str]]] = {}

    def discover_discriminator_fields(self, column_mapping_map: dict[str, list[ColumnMapping]]):
        constant_assignments: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))

        for target_table, mappings in column_mapping_map.items():
            for mapping in mappings:
                const_value = self._extract_constant_string(mapping.transformation_rule)
                if const_value is not None:
                    constant_assignments[target_table][mapping.target_column].add(const_value)

        for table, columns in constant_assignments.items():
            for column, values in columns.items():
                if len(values) > 1:
                    if table not in self.discriminator_fields:
                        self.discriminator_fields[table] = {}
                    self.discriminator_fields[table][column] = values

    def detect_write_scenario(self, target_table: str, mappings: list[ColumnMapping]) -> ProcessingScenario:
        if target_table not in self.discriminator_fields:
            return ProcessingScenario()

        disc_fields = self.discriminator_fields[target_table]
        for mapping in mappings:
            if mapping.target_column in disc_fields:
                const_value = self._extract_constant_string(mapping.transformation_rule)
                if const_value is not None:
                    return ProcessingScenario(
                        discriminator_field=mapping.target_column,
                        discriminator_value=const_value,
                    )
        return ProcessingScenario()

    def detect_read_scenario(self, table_lineages: list[TableLineage]) -> ProcessingScenario:
        for tl in table_lineages:
            if not tl.filter_condition:
                continue
            source_table = f"{tl.source_schema}.{tl.source_table}" if tl.source_schema else tl.source_table
            matched = self._match_filter_to_discriminator(
                tl.filter_condition, source_table, tl.source_alias
            )
            if matched:
                return matched
            matched = self._match_filter_to_discriminator(
                tl.filter_condition, tl.source_table, tl.source_alias
            )
            if matched:
                return matched
        return ProcessingScenario()

    def detect_scenario_for_sql(
        self,
        target_table: str,
        mappings: list[ColumnMapping],
        table_lineages: list[TableLineage],
    ) -> ProcessingScenario:
        write_scenario = self.detect_write_scenario(target_table, mappings)
        if write_scenario.discriminator_value:
            return write_scenario

        read_scenario = self.detect_read_scenario(table_lineages)
        if read_scenario.discriminator_value:
            return read_scenario

        return ProcessingScenario(is_shared=True)

    def _match_filter_to_discriminator(
        self, filter_condition: str, source_table: str, alias: str
    ) -> ProcessingScenario | None:
        for table, fields in self.discriminator_fields.items():
            table_matches = (
                table == source_table
                or table.endswith(f".{source_table}")
                or source_table.endswith(f".{table}")
            )
            if not table_matches:
                continue

            for field_name in fields:
                matched_value = self._extract_equality_value(filter_condition, field_name, alias)
                if matched_value is not None:
                    return ProcessingScenario(
                        discriminator_field=field_name,
                        discriminator_value=matched_value,
                    )
        return None

    def _extract_equality_value(self, filter_condition: str, field_name: str, alias: str) -> str | None:
        patterns = []
        if alias:
            patterns.append(
                re.compile(
                    r'\b' + re.escape(alias) + r'\.' + re.escape(field_name) + r"""\s*=\s*'([^']+)""",
                    re.IGNORECASE,
                )
            )
        patterns.append(
            re.compile(
                r'\b' + re.escape(field_name) + r"""\s*=\s*'([^']+)""",
                re.IGNORECASE,
            )
        )

        for pattern in patterns:
            m = pattern.search(filter_condition)
            if m:
                return m.group(1)
        return None

    @staticmethod
    def _extract_constant_string(transformation_rule: str) -> str | None:
        if not transformation_rule:
            return None
        stripped = transformation_rule.strip()
        m = re.match(r"^'([^']*)'$", stripped)
        if m:
            return m.group(1)
        return None
