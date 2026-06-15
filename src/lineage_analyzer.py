import sqlglot
from sqlglot import exp
from typing import Optional
from .models import ColumnMapping, TableDependency, LineageResult, TableLineage
from .dws_dialect import DWS


class LineageAnalyzer:
    def __init__(self, metadata_provider=None):
        self.metadata_provider = metadata_provider
        self.warnings = []
        self.cte_registry = {}
        self.cte_field_mappings = {}

    def _extract_ctes(self, parsed: exp.Expression) -> dict[str, exp.Select]:
        cte_map = {}
        with_clause = parsed.args.get('with_')
        if with_clause:
            for cte in with_clause.expressions:
                cte_name = cte.alias
                cte_query = cte.this
                if cte_name and cte_query:
                    cte_map[cte_name] = cte_query
        return cte_map

    def _extract_cte_field_mappings(self):
        for cte_name, cte_query in self.cte_registry.items():
            mappings = {}
            table_aliases = self._build_table_alias_map(cte_query)
            from_tables = self._get_from_tables_for_select(cte_query)
            
            for expr in cte_query.expressions:
                if isinstance(expr, exp.Alias):
                    field_name = expr.alias
                    source_expr = expr.this
                else:
                    field_name = expr.name
                    source_expr = expr
                
                transformation = source_expr.sql(dialect="dws")
                source_columns = []
                source_tables = []
                
                for col in source_expr.find_all(exp.Column):
                    col_name = col.name
                    table_ref = col.table
                    
                    if table_ref:
                        real_table = table_aliases.get(table_ref, table_ref)
                        if real_table not in source_tables:
                            source_tables.append(real_table)
                        full_col = f"{real_table}.{col_name}"
                        if full_col not in source_columns:
                            source_columns.append(full_col)
                    else:
                        inferred_table = self._infer_source_table(col_name, from_tables, table_aliases)
                        if inferred_table:
                            if inferred_table not in source_tables:
                                source_tables.append(inferred_table)
                            full_col = f"{inferred_table}.{col_name}"
                            if full_col not in source_columns:
                                source_columns.append(full_col)
                        else:
                            if col_name not in source_columns:
                                source_columns.append(col_name)
                
                mappings[field_name] = {
                    'transformation': transformation,
                    'source_tables': source_tables,
                    'source_columns': source_columns
                }
            
            self.cte_field_mappings[cte_name] = mappings

    def _get_from_tables_for_select(self, select: exp.Select) -> list[str]:
        from_tables = []
        from_clause = select.args.get('from_')
        if from_clause:
            for table in from_clause.find_all(exp.Table):
                table_name = self._get_table_name(table)
                if table_name:
                    from_tables.append(table_name)
        return from_tables

    def _resolve_cte_field(self, cte_name: str, field_name: str, visited: set = None) -> dict:
        if visited is None:
            visited = set()
        
        if cte_name in visited:
            return {'transformation': field_name, 'source_tables': [], 'source_columns': []}
        visited.add(cte_name)
        
        if cte_name not in self.cte_field_mappings:
            return {'transformation': f"{cte_name}.{field_name}", 'source_tables': [], 'source_columns': [f"{cte_name}.{field_name}"]}
        
        cte_mapping = self.cte_field_mappings[cte_name].get(field_name)
        if not cte_mapping:
            return {'transformation': f"{cte_name}.{field_name}", 'source_tables': [], 'source_columns': [f"{cte_name}.{field_name}"]}
        
        resolved_tables = []
        resolved_columns = []
        
        for src_table in cte_mapping['source_tables']:
            if src_table in self.cte_registry:
                col_name = None
                for src_col in cte_mapping['source_columns']:
                    if src_col.startswith(f"{src_table}."):
                        col_name = src_col.split('.')[-1]
                        break
                if col_name:
                    nested_result = self._resolve_cte_field(src_table, col_name, visited.copy())
                    resolved_tables.extend(nested_result['source_tables'])
                    resolved_columns.extend(nested_result['source_columns'])
            else:
                if src_table not in resolved_tables:
                    resolved_tables.append(src_table)
                for src_col in cte_mapping['source_columns']:
                    if src_col.startswith(f"{src_table}."):
                        if src_col not in resolved_columns:
                            resolved_columns.append(src_col)
        
        return {
            'transformation': cte_mapping['transformation'],
            'source_tables': list(set(resolved_tables)),
            'source_columns': list(set(resolved_columns))
        }

    def _resolve_cte_sources(self, cte_name: str, visited: set = None) -> list[str]:
        if visited is None:
            visited = set()
        
        if cte_name in visited:
            return []
        visited.add(cte_name)
        
        if cte_name not in self.cte_registry:
            return [cte_name]
        
        cte_query = self.cte_registry[cte_name]
        source_tables = []
        
        for table in cte_query.find_all(exp.Table):
            table_name = self._get_table_name(table)
            if table_name:
                if table_name in self.cte_registry:
                    nested_sources = self._resolve_cte_sources(table_name, visited.copy())
                    source_tables.extend(nested_sources)
                else:
                    if table_name not in source_tables:
                        source_tables.append(table_name)
        
        return source_tables

    def _classify_processing_scenario(self, transformation: str, source_columns: list[str]) -> str:
        if not transformation or transformation.strip() == "":
            return "赋值"

        transform_lower = transformation.lower().strip()

        has_column_ref = any(col.split('.')[-1] in transform_lower for col in source_columns if col)

        if not has_column_ref:
            if any(keyword in transform_lower for keyword in ['select', 'case', 'when', 'cast', 'convert']):
                pass
            else:
                return "赋值"

        if '(' in transformation or any(op in transformation for op in ['+', '-', '*', '/', '||', 'case', 'when', 'coalesce', 'nvl', 'if']):
            return "数据加工"

        if '.' in transformation and transformation.count('.') == 1 and ' ' not in transformation:
            return "直接复制"

        if transformation.replace('_', '').replace(' ', '').isalnum() and not has_column_ref:
            return "赋值"

        if has_column_ref and transformation.count(' ') == 0 and '(' not in transformation:
            return "直接复制"

        return "数据加工"

    def parse(self, sql: str) -> LineageResult:
        self.warnings = []
        self.cte_registry = {}
        self.cte_field_mappings = {}
        try:
            parsed = sqlglot.parse_one(sql, dialect="dws")
        except Exception as e:
            self.warnings.append(f"Parse error: {str(e)}")
            return LineageResult(target_table="", warnings=self.warnings)

        self.cte_registry = self._extract_ctes(parsed)
        self._extract_cte_field_mappings()

        target_table = self._extract_target_table(parsed)
        if not target_table:
            self.warnings.append("Could not identify target table")
            return LineageResult(target_table="", warnings=self.warnings)

        dependencies = self._extract_table_dependencies(parsed)
        
        select_expr = None
        if isinstance(parsed, exp.Insert):
            select_expr = parsed.expression
        elif isinstance(parsed, exp.Create):
            select_expr = parsed.expression
        else:
            select_expr = parsed
        
        all_mappings = []
        all_table_lineages = []
        
        if isinstance(select_expr, exp.Union):
            union_branches = self._extract_union_branches(select_expr)
            for group_id, branch in enumerate(union_branches, 1):
                branch_mappings = self._extract_column_mappings_from_select(branch, target_table, group_id)
                all_mappings.extend(branch_mappings)
                
                branch_table_lineages = self._extract_table_lineage_from_select(branch, target_table, group_id)
                all_table_lineages.extend(branch_table_lineages)
        else:
            mappings = self._extract_column_mappings(parsed, target_table)
            all_mappings = mappings
            table_lineages = self._extract_table_lineage(parsed, target_table)
            all_table_lineages = table_lineages

        return LineageResult(
            target_table=target_table,
            mappings=all_mappings,
            dependencies=dependencies,
            table_lineages=all_table_lineages,
            warnings=self.warnings
        )

    def _extract_union_branches(self, union_expr: exp.Union) -> list[exp.Select]:
        branches = []
        
        def collect_branches(expr):
            if isinstance(expr, exp.Union):
                collect_branches(expr.this)
                collect_branches(expr.expression)
            elif isinstance(expr, exp.Select):
                branches.append(expr)
        
        collect_branches(union_expr)
        return branches

    def _extract_target_table(self, parsed: exp.Expression) -> Optional[str]:
        if isinstance(parsed, exp.Insert):
            table = parsed.this
            if isinstance(table, exp.Schema):
                table = table.this
            return self._get_table_name(table)
        elif isinstance(parsed, exp.Create):
            table = parsed.this
            if isinstance(table, exp.Schema):
                table = table.this
            return self._get_table_name(table)
        elif isinstance(parsed, exp.Merge):
            return self._get_table_name(parsed.this)
        elif isinstance(parsed, exp.Update):
            return self._get_table_name(parsed.this)
        return None

    def _get_table_name(self, table_expr: exp.Expression) -> Optional[str]:
        if isinstance(table_expr, exp.Table):
            parts = []
            if table_expr.catalog:
                parts.append(table_expr.catalog)
            if table_expr.db:
                parts.append(table_expr.db)
            if table_expr.name:
                parts.append(table_expr.name)
            return '.'.join(parts) if parts else None
        return None

    def _split_schema_table(self, full_name: str) -> tuple[str, str]:
        if not full_name:
            return "", ""
        parts = full_name.split('.')
        if len(parts) == 1:
            return "", parts[0]
        elif len(parts) == 2:
            return parts[0], parts[1]
        elif len(parts) >= 3:
            return '.'.join(parts[:-1]), parts[-1]
        return "", full_name

    def _extract_table_dependencies(self, parsed: exp.Expression) -> list[TableDependency]:
        dependencies = []
        target = self._extract_target_table(parsed)

        source_tables = set()
        for table in parsed.find_all(exp.Table):
            table_name = self._get_table_name(table)
            if table_name and table_name != target:
                parent = table.parent
                is_target = False
                while parent:
                    if isinstance(parent, (exp.Insert, exp.Create, exp.Merge, exp.Update)):
                        if parent.this == table or (hasattr(parent.this, 'this') and parent.this.this == table):
                            is_target = True
                            break
                    parent = parent.parent

                if not is_target:
                    if table_name in self.cte_registry:
                        actual_sources = self._resolve_cte_sources(table_name)
                        source_tables.update(actual_sources)
                    else:
                        source_tables.add(table_name)

        for source in source_tables:
            dependencies.append(TableDependency(source_table=source, target_table=target))

        return dependencies

    def _extract_column_mappings(self, parsed: exp.Expression, target_table: str) -> list[ColumnMapping]:
        mappings = []

        select = None
        if isinstance(parsed, exp.Insert):
            select = parsed.expression
        elif isinstance(parsed, exp.Create):
            select = parsed.expression
        elif isinstance(parsed, exp.Merge):
            for match in parsed.find_all(exp.Match):
                if match.expression:
                    select = match.expression
                    break

        if not select:
            select = parsed

        if not isinstance(select, exp.Select):
            for s in parsed.find_all(exp.Select):
                select = s
                break

        if not isinstance(select, exp.Select):
            return mappings

        table_aliases = self._build_table_alias_map(parsed)
        from_tables = self._get_from_tables(parsed)
        target_columns = self._extract_target_columns(parsed)
        
        target_schema, target_table_name = self._split_schema_table(target_table)

        for idx, expr in enumerate(select.expressions):
            mapping = self._process_select_expr(expr, target_schema, target_table_name, idx, target_columns, table_aliases, from_tables, parsed)
            if mapping:
                mappings.append(mapping)

        return mappings

    def _extract_column_mappings_from_select(self, select: exp.Select, target_table: str, group_id: int) -> list[ColumnMapping]:
        mappings = []
        
        if not isinstance(select, exp.Select):
            return mappings

        table_aliases = self._build_table_alias_map(select)
        from_tables = self._get_from_tables_for_select(select)
        
        target_schema, target_table_name = self._split_schema_table(target_table)
        target_columns = []

        for idx, expr in enumerate(select.expressions):
            mapping = self._process_select_expr(expr, target_schema, target_table_name, idx, target_columns, table_aliases, from_tables, select)
            if mapping:
                mapping.group_id = group_id
                mappings.append(mapping)

        return mappings

    def _extract_table_lineage(self, parsed: exp.Expression, target_table: str) -> list[TableLineage]:
        table_lineages = []
        target_schema, target_table_name = self._split_schema_table(target_table)
        
        select = None
        if isinstance(parsed, exp.Insert):
            select = parsed.expression
        elif isinstance(parsed, exp.Create):
            select = parsed.expression
        else:
            select = parsed
            
        if not isinstance(select, exp.Select):
            for s in parsed.find_all(exp.Select):
                select = s
                break
        
        if not isinstance(select, exp.Select):
            return table_lineages
        
        table_aliases = self._build_table_alias_map(parsed)
        
        from_clause = select.args.get('from_')
        if from_clause:
            for table in from_clause.find_all(exp.Table):
                table_full_name = self._get_table_name(table)
                if table_full_name:
                    actual_tables = []
                    if table_full_name in self.cte_registry:
                        actual_tables = self._resolve_cte_sources(table_full_name)
                    else:
                        actual_tables = [table_full_name]
                    
                    table_alias = table.alias or ""
                    
                    for actual_table in actual_tables:
                        src_schema, src_table_name = self._split_schema_table(actual_table)
                        
                        filter_cond = self._extract_table_filter(table, select)
                        
                        lineage = TableLineage(
                            target_schema=target_schema,
                            target_table=target_table_name,
                            source_schema=src_schema,
                            source_table=src_table_name,
                            source_alias=table_alias,
                            join_type="FROM",
                            join_condition="",
                            filter_condition=filter_cond,
                            is_cte_resolved=(table_full_name in self.cte_registry)
                        )
                        table_lineages.append(lineage)
        
        for join in select.args.get('joins', []) or []:
            join_table = join.this
            if isinstance(join_table, exp.Table):
                table_full_name = self._get_table_name(join_table)
                if table_full_name:
                    actual_tables = []
                    if table_full_name in self.cte_registry:
                        actual_tables = self._resolve_cte_sources(table_full_name)
                    else:
                        actual_tables = [table_full_name]
                    
                    table_alias = join_table.alias or ""
                    
                    join_type = join.args.get('side', '') or ''
                    join_kind = join.args.get('kind', '') or ''
                    if join_kind:
                        join_type = f"{join_type} {join_kind}".strip()
                    if not join_type:
                        join_type = "INNER"
                    
                    join_cond = ""
                    on_clause = join.args.get('on')
                    if on_clause:
                        join_cond = on_clause.sql(dialect="dws")
                    
                    for actual_table in actual_tables:
                        src_schema, src_table_name = self._split_schema_table(actual_table)
                        
                        filter_cond = self._extract_table_filter(join_table, select)
                        
                        lineage = TableLineage(
                            target_schema=target_schema,
                            target_table=target_table_name,
                            source_schema=src_schema,
                            source_table=src_table_name,
                            source_alias=table_alias,
                            join_type=join_type.upper(),
                            join_condition=join_cond,
                            filter_condition=filter_cond,
                            is_cte_resolved=(table_full_name in self.cte_registry)
                        )
                        table_lineages.append(lineage)
        
        return table_lineages

    def _extract_table_lineage_from_select(self, select: exp.Select, target_table: str, group_id: int) -> list[TableLineage]:
        table_lineages = []
        target_schema, target_table_name = self._split_schema_table(target_table)
        
        if not isinstance(select, exp.Select):
            return table_lineages
        
        table_aliases = self._build_table_alias_map(select)
        
        from_clause = select.args.get('from_')
        if from_clause:
            for table in from_clause.find_all(exp.Table):
                table_full_name = self._get_table_name(table)
                if table_full_name:
                    actual_tables = []
                    if table_full_name in self.cte_registry:
                        actual_tables = self._resolve_cte_sources(table_full_name)
                    else:
                        actual_tables = [table_full_name]
                    
                    table_alias = table.alias or ""
                    
                    for actual_table in actual_tables:
                        src_schema, src_table_name = self._split_schema_table(actual_table)
                        
                        filter_cond = self._extract_table_filter(table, select)
                        
                        lineage = TableLineage(
                            target_schema=target_schema,
                            target_table=target_table_name,
                            source_schema=src_schema,
                            source_table=src_table_name,
                            source_alias=table_alias,
                            join_type="FROM",
                            join_condition="",
                            filter_condition=filter_cond,
                            is_cte_resolved=(table_full_name in self.cte_registry),
                            group_id=group_id
                        )
                        table_lineages.append(lineage)
        
        for join in select.args.get('joins', []) or []:
            join_table = join.this
            if isinstance(join_table, exp.Table):
                table_full_name = self._get_table_name(join_table)
                if table_full_name:
                    actual_tables = []
                    if table_full_name in self.cte_registry:
                        actual_tables = self._resolve_cte_sources(table_full_name)
                    else:
                        actual_tables = [table_full_name]
                    
                    table_alias = join_table.alias or ""
                    
                    join_type = join.args.get('side', '') or ''
                    join_kind = join.args.get('kind', '') or ''
                    if join_kind:
                        join_type = f"{join_type} {join_kind}".strip()
                    if not join_type:
                        join_type = "INNER"
                    
                    join_cond = ""
                    on_clause = join.args.get('on')
                    if on_clause:
                        join_cond = on_clause.sql(dialect="dws")
                    
                    for actual_table in actual_tables:
                        src_schema, src_table_name = self._split_schema_table(actual_table)
                        
                        filter_cond = self._extract_table_filter(join_table, select)
                        
                        lineage = TableLineage(
                            target_schema=target_schema,
                            target_table=target_table_name,
                            source_schema=src_schema,
                            source_table=src_table_name,
                            source_alias=table_alias,
                            join_type=join_type.upper(),
                            join_condition=join_cond,
                            filter_condition=filter_cond,
                            is_cte_resolved=(table_full_name in self.cte_registry),
                            group_id=group_id
                        )
                        table_lineages.append(lineage)
        
        return table_lineages

    def _extract_table_filter(self, table: exp.Table, select: exp.Select) -> str:
        where_clause = select.args.get('where')
        if not where_clause:
            return ""
        
        table_alias = table.alias
        table_name = self._get_table_name(table)
        
        where_sql = where_clause.sql(dialect="dws")
        
        if table_alias and table_alias in where_sql:
            return where_sql.replace("WHERE ", "")
        elif table_name and table_name in where_sql:
            return where_sql.replace("WHERE ", "")
        
        from_clause = select.args.get('from_')
        joins = select.args.get('joins', []) or []
        
        if from_clause and not joins:
            from_tables = list(from_clause.find_all(exp.Table))
            if len(from_tables) == 1:
                return where_sql.replace("WHERE ", "")
        
        return ""

    def _build_table_alias_map(self, parsed: exp.Expression) -> dict[str, str]:
        alias_map = {}
        for table in parsed.find_all(exp.Table):
            table_name = self._get_table_name(table)
            if table_name:
                alias = table.alias
                if alias:
                    alias_map[alias] = table_name
                alias_map[table_name] = table_name
        return alias_map

    def _get_from_tables(self, parsed: exp.Expression) -> list[str]:
        from_tables = []
        select = None
        
        if isinstance(parsed, exp.Insert):
            select = parsed.expression
        elif isinstance(parsed, exp.Create):
            select = parsed.expression
        else:
            select = parsed
            
        if not isinstance(select, exp.Select):
            for s in parsed.find_all(exp.Select):
                select = s
                break
        
        if isinstance(select, exp.Select):
            from_clause = select.args.get('from_')
            if from_clause:
                for table in from_clause.find_all(exp.Table):
                    table_name = self._get_table_name(table)
                    if table_name:
                        from_tables.append(table_name)
        
        return from_tables

    def _extract_target_columns(self, parsed: exp.Expression) -> list[str]:
        if isinstance(parsed, exp.Insert):
            schema = parsed.this
            if isinstance(schema, exp.Schema):
                return [col.name for col in schema.expressions]
        return []

    def _process_select_expr(self, expr: exp.Expression, target_schema: str, target_table: str, idx: int,
                             target_columns: list[str], table_aliases: dict[str, str],
                             from_tables: list[str], parsed: exp.Expression) -> Optional[ColumnMapping]:
        if isinstance(expr, exp.Alias):
            target_col = expr.alias
            source_expr = expr.this
        else:
            if idx < len(target_columns):
                target_col = target_columns[idx]
            else:
                target_col = expr.name or f"col_{idx}"
            source_expr = expr

        source_schemas = []
        source_tables = []
        source_aliases = []
        source_columns = []
        transformation = source_expr.sql(dialect="dws")
        cte_substitutions = {}

        for col in source_expr.find_all(exp.Column):
            col_name = col.name
            table_ref = col.table

            if table_ref:
                real_table = table_aliases.get(table_ref, table_ref)
                if real_table in self.cte_registry:
                    actual_sources = self._resolve_cte_sources(real_table)
                    for src_table_full in actual_sources:
                        src_schema, src_table_name = self._split_schema_table(src_table_full)
                        if src_table_name not in source_tables:
                            source_tables.append(src_table_name)
                        if src_schema and src_schema not in source_schemas:
                            source_schemas.append(src_schema)
                        if table_ref and table_ref not in source_aliases:
                            source_aliases.append(table_ref)
                    
                    cte_field_result = self._resolve_cte_field(real_table, col_name)
                    
                    for src_col in cte_field_result['source_columns']:
                        if '.' in src_col and not any(cte in src_col for cte in self.cte_registry.keys()):
                            if src_col not in source_columns:
                                source_columns.append(src_col)
                    
                    cte_transform = cte_field_result['transformation']
                    if cte_transform != col_name and cte_transform != f"{real_table}.{col_name}":
                        if '(' in cte_transform or any(op in cte_transform for op in ['+', '-', '*', '/', 'case', 'when']):
                            col_ref = f"{table_ref}.{col_name}"
                            cte_substitutions[col_ref] = cte_transform
                    
                    full_col = f"{real_table}.{col_name}"
                else:
                    src_schema, src_table_name = self._split_schema_table(real_table)
                    if src_table_name not in source_tables:
                        source_tables.append(src_table_name)
                    if src_schema and src_schema not in source_schemas:
                        source_schemas.append(src_schema)
                    if table_ref and table_ref not in source_aliases:
                        source_aliases.append(table_ref)
                    full_col = f"{real_table}.{col_name}"
                    if full_col not in source_columns:
                        source_columns.append(full_col)
            else:
                inferred_table = self._infer_source_table(col_name, from_tables, table_aliases)
                if inferred_table:
                    if inferred_table in self.cte_registry:
                        actual_sources = self._resolve_cte_sources(inferred_table)
                        for src_table_full in actual_sources:
                            src_schema, src_table_name = self._split_schema_table(src_table_full)
                            if src_table_name not in source_tables:
                                source_tables.append(src_table_name)
                            if src_schema and src_schema not in source_schemas:
                                source_schemas.append(src_schema)
                        
                        cte_field_result = self._resolve_cte_field(inferred_table, col_name)
                        
                        for src_col in cte_field_result['source_columns']:
                            if '.' in src_col and not any(cte in src_col for cte in self.cte_registry.keys()):
                                if src_col not in source_columns:
                                    source_columns.append(src_col)
                        
                        cte_transform = cte_field_result['transformation']
                        if cte_transform != col_name and cte_transform != f"{inferred_table}.{col_name}":
                            if '(' in cte_transform or any(op in cte_transform for op in ['+', '-', '*', '/', 'case', 'when']):
                                cte_substitutions[col_name] = cte_transform
                        
                        full_col = f"{inferred_table}.{col_name}"
                    else:
                        src_schema, src_table_name = self._split_schema_table(inferred_table)
                        if src_table_name not in source_tables:
                            source_tables.append(src_table_name)
                        if src_schema and src_schema not in source_schemas:
                            source_schemas.append(src_schema)
                        full_col = f"{inferred_table}.{col_name}"
                        if full_col not in source_columns:
                            source_columns.append(full_col)
                else:
                    if col_name not in source_columns:
                        source_columns.append(col_name)

        source_columns = list(dict.fromkeys(source_columns))
        source_schemas = list(dict.fromkeys(source_schemas))
        source_aliases = list(dict.fromkeys(source_aliases))

        if isinstance(source_expr, exp.Star):
            self.warnings.append(f"SELECT * encountered - metadata provider needed for expansion")
            return None

        sorted_subs = sorted(cte_substitutions.items(), key=lambda x: len(x[0]), reverse=True)
        for col_ref, cte_transform in sorted_subs:
            if col_ref in transformation:
                transformation = transformation.replace(col_ref, f"({cte_transform})")

        processing_scenario = self._classify_processing_scenario(transformation, source_columns)

        return ColumnMapping(
            target_schema=target_schema,
            target_table=target_table,
            target_column=target_col,
            source_schemas=source_schemas,
            source_tables=source_tables,
            source_aliases=source_aliases,
            source_columns=source_columns,
            transformation_rule=transformation,
            processing_scenario=processing_scenario
        )

    def _infer_source_table(self, col_name: str, from_tables: list[str], table_aliases: dict[str, str]) -> Optional[str]:
        # If only one table in FROM clause, use it
        if len(from_tables) == 1:
            return from_tables[0]
        
        # If metadata provider is available, use it to find which table has this column
        if self.metadata_provider:
            for table in from_tables:
                columns = self.metadata_provider.get_columns(table)
                if any(col['name'] == col_name for col in columns):
                    return table
        
        # Cannot infer - return None
        return None
