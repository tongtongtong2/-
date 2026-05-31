"""market_regime 表 CRUD。"""

from datetime import date

from src.database.connection import get_session
from src.database.repository.db_helpers import upsert_one
from src.database.schema import MarketRegimeOrm
from src.models import MarketRegime


def save(record: MarketRegime) -> None:
    orm = record.to_orm()
    values = {c.name: getattr(orm, c.name) for c in MarketRegimeOrm.__table__.columns}
    upsert_one(MarketRegimeOrm, values, update_columns=["state", "score", "data"])


def find_by_date(target_date: date) -> MarketRegime | None:
    session = get_session()
    try:
        result = (session.query(MarketRegimeOrm)
                  .filter(MarketRegimeOrm.date == target_date).first())
        return result.to_model() if result else None
    finally:
        session.close()


def find_between(start: date | None = None, end: date | None = None) -> list[MarketRegime]:
    session = get_session()
    try:
        q = session.query(MarketRegimeOrm)
        if start is not None:
            q = q.filter(MarketRegimeOrm.date >= start)
        if end is not None:
            q = q.filter(MarketRegimeOrm.date <= end)
        return [r.to_model() for r in q.order_by(MarketRegimeOrm.date.asc()).all()]
    finally:
        session.close()
