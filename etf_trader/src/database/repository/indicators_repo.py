"""indicators 表 CRUD。兼容 PostgreSQL / MySQL。"""

from datetime import date

from sqlalchemy import func
from sqlalchemy.dialects.mysql import insert as mysql_insert

from src.database.connection import get_session
from src.database.schema import IndicatorsOrm
from src.models import Indicators


def save(code: str, date: date, data: dict) -> None:
    """写入或合并单日技术指标。

    MySQL: INSERT ... ON DUPLICATE KEY UPDATE，使用 JSON_MERGE_PATCH 合并。
    """
    import json
    session = get_session()
    try:
        from sqlalchemy import text
        session.execute(
            text("""
                INSERT INTO indicators (code, date, data) 
                VALUES (:code, :date, :data)
                ON DUPLICATE KEY UPDATE data = JSON_MERGE_PATCH(data, VALUES(data))
            """),
            {"code": code, "date": date, "data": json.dumps(data)},
        )
        session.commit()
    finally:
        session.close()


def find_by_code_between(code: str, start: date | None = None,
                         end: date | None = None) -> list[Indicators]:
    """按 ETF 代码和日期区间查询技术指标。

    Args:
        code:  ETF 代码
        start: 起始日期（含），None 表示不限制
        end:   结束日期（含），None 表示不限制

    Returns:
        按日期升序排列的 Indicators 列表
    """
    session = get_session()
    try:
        q = session.query(IndicatorsOrm).filter(IndicatorsOrm.code == code)
        if start is not None:
            q = q.filter(IndicatorsOrm.date >= start)
        if end is not None:
            q = q.filter(IndicatorsOrm.date <= end)
        return [r.to_model() for r in q.order_by(IndicatorsOrm.date.asc()).all()]
    finally:
        session.close()


def count_between(code: str, start: date, end: date) -> int:
    """统计区间内指标记录数。

    service 层据此判断数据完整度，决定是否需要补算。

    Args:
        code:  ETF 代码
        start: 起始日期（含）
        end:   结束日期（含）

    Returns:
        区间内记录条数
    """
    session = get_session()
    try:
        return (
            session.query(func.count())
            .filter(IndicatorsOrm.code == code)
            .filter(IndicatorsOrm.date >= start)
            .filter(IndicatorsOrm.date <= end)
            .scalar()
        )
    finally:
        session.close()
