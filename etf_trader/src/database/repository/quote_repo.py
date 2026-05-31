"""quote 表 CRUD。"""

from datetime import date

from src.database.connection import get_session
from src.database.repository.db_helpers import upsert
from src.database.schema import QuoteOrm
from src.models import Quote


def save_batch(records: list[Quote]) -> None:
    """批量写入行情记录。已存在的记录不会被覆盖（INSERT IGNORE）。"""
    if not records:
        return
    orm_records = [r.to_orm() for r in records]
    values = [{c.name: getattr(orm, c.name) for c in QuoteOrm.__table__.columns}
              for orm in orm_records]
    upsert(QuoteOrm, values, update_columns=None)  # INSERT IGNORE


def find_by_code_in_range(code: str, start: date | None = None,
                         end: date | None = None) -> list[Quote]:
    session = get_session()
    try:
        q = session.query(QuoteOrm).filter(QuoteOrm.code == code)
        if start is not None:
            q = q.filter(QuoteOrm.date >= start)
        if end is not None:
            q = q.filter(QuoteOrm.date <= end)
        return [r.to_model() for r in q.order_by(QuoteOrm.date.asc()).all()]
    finally:
        session.close()


def find_earliest_date(code: str) -> date | None:
    session = get_session()
    try:
        result = (session.query(QuoteOrm.date)
                  .filter(QuoteOrm.code == code)
                  .order_by(QuoteOrm.date.asc()).first())
        return result[0] if result else None
    finally:
        session.close()


def find_latest_date(code: str) -> date | None:
    session = get_session()
    try:
        result = (session.query(QuoteOrm.date)
                  .filter(QuoteOrm.code == code)
                  .order_by(QuoteOrm.date.desc()).first())
        return result[0] if result else None
    finally:
        session.close()


def find_latest_quote(code: str) -> Quote | None:
    session = get_session()
    try:
        result = (session.query(QuoteOrm)
                  .filter(QuoteOrm.code == code)
                  .order_by(QuoteOrm.date.desc()).first())
        return result.to_model() if result else None
    finally:
        session.close()
