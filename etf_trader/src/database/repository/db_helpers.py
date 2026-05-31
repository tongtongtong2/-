"""数据库兼容层：屏蔽 PostgreSQL / MySQL upsert 语法差异。"""
import json
from typing import Any

from sqlalchemy import text

from src.database.connection import get_session
from src.database.schema import Base


def upsert(table_class: type[Base], values: list[dict[str, Any]],
           update_columns: list[str] | None = None) -> None:
    """通用 upsert：INSERT ... ON DUPLICATE KEY UPDATE（MySQL 语法）。"""
    if not values:
        return

    table = table_class.__table__
    columns = [c.name for c in table.columns]

    # 反引号包裹列名
    q_cols = [f"`{c}`" for c in columns]
    col_list = ", ".join(q_cols)

    placeholders = ", ".join(
        f"({', '.join(f':{col}_{i}' for col in columns)})"
        for i in range(len(values))
    )
    params = {}
    for i, row in enumerate(values):
        for col in columns:
            val = row.get(col)
            if isinstance(val, dict):
                val = json.dumps(val, ensure_ascii=False)
            params[f"{col}_{i}"] = val

    if update_columns is None:
        sql = f"INSERT IGNORE INTO `{table.name}` ({col_list}) VALUES {placeholders}"
    elif update_columns:
        updates = ", ".join(f"`{c}` = VALUES(`{c}`)" for c in update_columns)
        sql = f"INSERT INTO `{table.name}` ({col_list}) VALUES {placeholders} ON DUPLICATE KEY UPDATE {updates}"
    else:
        sql = f"INSERT INTO `{table.name}` ({col_list}) VALUES {placeholders}"

    session = get_session()
    try:
        session.execute(text(sql), params)
        session.commit()
    finally:
        session.close()


def upsert_one(table_class: type[Base], values: dict[str, Any],
               update_columns: list[str] | None = None) -> None:
    """单行 upsert。"""
    upsert(table_class, [values], update_columns)
