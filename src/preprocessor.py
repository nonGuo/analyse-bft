import re


def remove_comments(sql: str) -> str:
    result = []
    i = 0
    n = len(sql)

    while i < n:
        if sql[i:i + 2] == '--':
            while i < n and sql[i] != '\n':
                i += 1
        elif sql[i:i + 2] == '/*':
            end = sql.find('*/', i + 2)
            if end == -1:
                break
            hint_content = sql[i + 2:end].strip()
            if hint_content.startswith('+'):
                result.append(sql[i:end + 2])
            i = end + 2
        else:
            result.append(sql[i])
            i += 1

    return ''.join(result)


def replace_variables(sql: str, default_value: str = "'2026-01-01'") -> str:
    sql = re.sub(r'\$\{[^}]+\}', default_value.strip("'"), sql)
    sql = re.sub(r'\$[a-zA-Z_][a-zA-Z0-9_.]*', default_value.strip("'"), sql)
    return sql


def remove_dws_physical_ddl(sql: str) -> str:
    patterns = [
        r'DISTRIBUTE\s+BY\s+HASH\s*\([^)]+\)',
        r'DISTRIBUTE\s+BY\s+MODULO\s*\([^)]+\)',
        r'DISTRIBUTE\s+BY\s+REPLICATION',
        r'WITH\s*\(\s*ORIENTATION\s*=\s*(?:COLUMN|ROW)\s*(?:,[^)]+)?\)',
        r'PARTITION\s+BY\s+RANGE\s*\([^)]+\)\s*\([^;]+\)',
    ]
    for pattern in patterns:
        sql = re.sub(pattern, '', sql, flags=re.IGNORECASE)
    return sql


def split_statements(sql: str) -> list[str]:
    statements = []
    current = []
    in_single_quote = False
    in_double_quote = False
    i = 0
    n = len(sql)

    while i < n:
        c = sql[i]

        if c == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
            current.append(c)
        elif c == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
            current.append(c)
        elif c == '-' and not in_single_quote and not in_double_quote:
            if sql[i:i + 2] == '--':
                while i < n and sql[i] != '\n':
                    i += 1
                continue
            else:
                current.append(c)
        elif c == '/' and not in_single_quote and not in_double_quote:
            if sql[i:i + 2] == '/*':
                end = sql.find('*/', i + 2)
                if end != -1:
                    i = end + 2
                    continue
            current.append(c)
        elif c == ';' and not in_single_quote and not in_double_quote:
            stmt = ''.join(current).strip()
            if stmt:
                statements.append(stmt)
            current = []
        else:
            current.append(c)

        i += 1

    stmt = ''.join(current).strip()
    if stmt:
        statements.append(stmt)

    return statements


def preprocess_sql(sql: str) -> list[str]:
    sql = remove_comments(sql)
    sql = replace_variables(sql)
    sql = remove_dws_physical_ddl(sql)
    return split_statements(sql)
