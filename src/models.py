from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ProcessingScenario:
    discriminator_field: str = ""
    discriminator_value: str = ""
    is_shared: bool = False

    @property
    def label(self) -> str:
        if self.is_shared:
            return "(公共)"
        if self.discriminator_field and self.discriminator_value:
            return f"{self.discriminator_field}={self.discriminator_value}"
        return ""


@dataclass
class ColumnMapping:
    target_schema: str = ""
    target_table: str = ""
    target_column: str = ""
    source_schemas: list[str] = field(default_factory=list)
    source_tables: list[str] = field(default_factory=list)
    source_aliases: list[str] = field(default_factory=list)
    source_columns: list[str] = field(default_factory=list)
    transformation_rule: str = ""
    data_type: str = ""
    processing_scenario: str = ""
    group_id: int = 1
    scenario: ProcessingScenario = field(default_factory=ProcessingScenario)


@dataclass
class TableDependency:
    source_table: str
    target_table: str


@dataclass
class TableLineage:
    target_schema: str = ""
    target_table: str = ""
    source_schema: str = ""
    source_table: str = ""
    source_alias: str = ""
    join_type: str = ""
    join_condition: str = ""
    filter_condition: str = ""
    is_cte_resolved: bool = False
    group_id: int = 1
    scenario: ProcessingScenario = field(default_factory=ProcessingScenario)


@dataclass
class LineageResult:
    target_table: str
    mappings: list[ColumnMapping] = field(default_factory=list)
    dependencies: list[TableDependency] = field(default_factory=list)
    table_lineages: list[TableLineage] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class ParseResult:
    lineage_results: list[LineageResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class ScenarioDataFlowNode:
    table_name: str
    scenario: ProcessingScenario = field(default_factory=ProcessingScenario)

    @property
    def node_id(self) -> str:
        if self.scenario.is_shared or not self.scenario.discriminator_value:
            return self.table_name
        return f"{self.table_name}[{self.scenario.discriminator_field}={self.scenario.discriminator_value}]"


@dataclass
class ScenarioDataFlowEdge:
    source: ScenarioDataFlowNode
    target: ScenarioDataFlowNode
    filter_condition: str = ""


@dataclass
class ScenarioChain:
    scenario: ProcessingScenario
    target_tables: list[str] = field(default_factory=list)
    source_tables: list[str] = field(default_factory=list)
    intermediate_tables: list[str] = field(default_factory=list)
    sql_files: list[str] = field(default_factory=list)
    mappings: list[ColumnMapping] = field(default_factory=list)
    table_lineages: list[TableLineage] = field(default_factory=list)
    dependencies: list[TableDependency] = field(default_factory=list)
