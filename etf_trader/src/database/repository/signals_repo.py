"""signals 表 CRUD。"""

from datetime import date

from src.database.connection import get_session
from src.database.repository.db_helpers import upsert_one
from src.database.schema import SignalOrm
from src.models import Signal


def save(code: str, date: date, signal: str, version: str, meta: dict) -> None:
    """写入或替换单日策略信号。"""
    upsert_one(SignalOrm, {
        "code": code, "date": date, "signal": signal,
        "strategy_version": version, "signal_meta": meta,
    }, update_columns=["signal", "strategy_version", "signal_meta"])


def find_by_date(date: date) -> list[Signal]:
    session = get_session()
    try:
        results = (session.query(SignalOrm)
                   .filter(SignalOrm.date == date)
                   .order_by(SignalOrm.code.asc()).all())
        return [r.to_model() for r in results]
    finally:
        session.close()


def find_by_code_between(code: str, start: date | None = None,
                         end: date | None = None) -> list[Signal]:
    session = get_session()
    try:
        q = session.query(SignalOrm).filter(SignalOrm.code == code)
        if start is not None:
            q = q.filter(SignalOrm.date >= start)
        if end is not None:
            q = q.filter(SignalOrm.date <= end)
        return [r.to_model() for r in q.order_by(SignalOrm.date.asc()).all()]
    finally:
        session.close()
