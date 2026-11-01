"""Tiny SQLite auto-migration: adds columns that exist in the models but are
missing in an older connectx.db, so you don't have to delete the database
every time a new column is added. (New tables are handled by create_all.)"""
import enum
from sqlalchemy import inspect, text
from app.database import Base, engine


def _default_sql(col) -> str:
    d = col.default
    if d is None or not getattr(d, "is_scalar", False):
        return ""
    arg = d.arg
    if isinstance(arg, enum.Enum):
        arg = arg.name
    if isinstance(arg, bool):
        return f" DEFAULT {1 if arg else 0}"
    if isinstance(arg, (int, float)):
        return f" DEFAULT {arg}"
    if isinstance(arg, str):
        return " DEFAULT '" + arg.replace("'", "''") + "'"
    return ""


def run_light_migrations() -> None:
    if engine.dialect.name != "sqlite":
        return
    insp = inspect(engine)
    existing_tables = set(insp.get_table_names())
    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue
        have = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name in have:
                continue
            default_sql = _default_sql(col)
            if not col.nullable and not default_sql:
                print(f"[migrate] skipped {table.name}.{col.name} (NOT NULL without default)")
                continue
            col_type = col.type.compile(dialect=engine.dialect)
            ddl = f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {col_type}{default_sql}'
            try:
                with engine.begin() as conn:
                    conn.execute(text(ddl))
                print(f"[migrate] added column {table.name}.{col.name}")
            except Exception as e:  # noqa: BLE001
                print(f"[migrate] could not add {table.name}.{col.name}: {e}")
