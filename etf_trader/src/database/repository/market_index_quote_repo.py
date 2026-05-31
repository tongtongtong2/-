"""market_index_quote 表 CRUD。"""

from datetime import date

from src.database.connection import get_session
from src.database.repository.db_helpers import upsert
from src.database.schema import MarketIndexQuoteOrm
from src.models import MarketIndexQuote


UPDATE_COLS = ["open", "high", "low", "close", "volume", "amount"]


def save_batch(records: list[MarketIndexQuote]) -> None:
    if not records:
        return
    orm_records = [r.to_orm() for r in records]
    values = [{c.name: getattr(orm, c.name) for c in MarketIndexQuoteOrm.__table__.columns}
              for orm in orm_records]
    upsert(MarketIndexQuoteOrm, values, update_columns=UPDATE_COLS)


def find_by_code_in_range(index_code: str, start: date | None = None,
                          end: date | None = None) -> list[MarketIndexQuote]:
    session = get_session()
    try:
        q = session.query(MarketIndexQuoteOrm).filter(
            MarketIndexQuoteOrm.index_code == index_code)
        if start is not None:
            q = q.filter(MarketIndexQuoteOrm.date >= start)
        if end is not None:
            q = q.filter(MarketIndexQuoteOrm.date <= end)
        return [r.to_model() for r in q.order_by(MarketIndexQuoteOrm.date.asc()).all()]
    finally:
        session.close()


def find_latest_date(index_code: str) -> date | None:
    session = get_session()
    try:
        result = (session.query(MarketIndexQuoteOrm.date)
                  .filter(MarketIndexQuoteOrm.index_code == index_code)
                  .order_by(MarketIndexQuoteOrm.date.desc()).first())
        return result[0] if result else None
    finally:
        session.close()
