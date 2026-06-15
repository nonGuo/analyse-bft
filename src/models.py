from dataclasses import dataclass, field
from typing import Optional


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
