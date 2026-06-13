"""SQLite连接管理器 — 上下文管理器，自动迁移"""
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from config import DB_PATH


def _get_schema_path() -> Path:
    """获取schema.sql路径"""
    return Path(__file__).resolve().parent / "schema.sql"


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """执行schema.sql确保所有表存在"""
    schema_path = _get_schema_path()
    if schema_path.exists():
        conn.executescript(schema_path.read_text(encoding="utf-8"))
        conn.commit()


@contextmanager
def connect() -> Generator[sqlite3.Connection, None, None]:
    """获取数据库连接（上下文管理器）

    用法:
        with db.connect() as conn:
            rows = conn.execute("SELECT * FROM etf_quotes").fetchall()
    """
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        _ensure_schema(conn)
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    """显式初始化数据库（创建所有表）"""
    with connect() as conn:
        _ensure_schema(conn)
