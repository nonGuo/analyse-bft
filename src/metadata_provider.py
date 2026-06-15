from typing import Protocol, Optional
import json
import os


class MetadataProvider(Protocol):
    def get_columns(self, table_name: str) -> list[dict[str, str]]:
        ...


class LocalFileMetadataProvider:
    def __init__(self, metadata_dir: str = "metadata"):
        self.metadata_dir = metadata_dir
        self._cache: dict[str, list[dict[str, str]]] = {}
        self._load_all()

    def _load_all(self):
        if not os.path.exists(self.metadata_dir):
            return

        for filename in os.listdir(self.metadata_dir):
            if filename.endswith('.json'):
                table_name = filename[:-5]
                filepath = os.path.join(self.metadata_dir, filename)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        if isinstance(data, list):
                            self._cache[table_name] = data
                except Exception:
                    pass

    def get_columns(self, table_name: str) -> list[dict[str, str]]:
        table_name = table_name.split('.')[-1]
        return self._cache.get(table_name, [])

    def add_table_metadata(self, table_name: str, columns: list[dict[str, str]]):
        table_name = table_name.split('.')[-1]
        self._cache[table_name] = columns

        if not os.path.exists(self.metadata_dir):
            os.makedirs(self.metadata_dir)

        filepath = os.path.join(self.metadata_dir, f"{table_name}.json")
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(columns, f, ensure_ascii=False, indent=2)


class DatabaseMetadataProvider:
    def __init__(self, connection_params: dict):
        self.connection_params = connection_params
        self._cache: dict[str, list[dict[str, str]]] = {}

    def get_columns(self, table_name: str) -> list[dict[str, str]]:
        if table_name in self._cache:
            return self._cache[table_name]

        try:
            import psycopg2
            conn = psycopg2.connect(**self.connection_params)
            cursor = conn.cursor()

            schema = 'public'
            table = table_name
            if '.' in table_name:
                parts = table_name.split('.')
                if len(parts) == 2:
                    schema, table = parts
                elif len(parts) == 3:
                    _, schema, table = parts

            query = """
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s
                ORDER BY ordinal_position
            """
            cursor.execute(query, (schema, table))
            columns = [{"name": row[0], "type": row[1]} for row in cursor.fetchall()]

            cursor.close()
            conn.close()

            self._cache[table_name] = columns
            return columns
        except Exception as e:
            print(f"Warning: Could not fetch metadata for {table_name}: {e}")
            return []


class DummyMetadataProvider:
    def get_columns(self, table_name: str) -> list[dict[str, str]]:
        return []
