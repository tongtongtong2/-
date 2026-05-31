"""operation_advice 表 CRUD。"""

from datetime import date

from src.database.connection import get_session
from src.database.repository.db_helpers import upsert
from src.database.schema import OperationAdviceOrm
from src.models import OperationAdvice


def save_batch(records: list[OperationAdvice]) -> None:
    if not records:
        return
    orm_records = [r.to_orm() for r in records]
    values = [{c.name: getattr(orm, c.name) for c in OperationAdviceOrm.__table__.columns}
              for orm in orm_records]
    upsert(OperationAdviceOrm, values, update_columns=None)


def find_by_code(code: str) -> list[OperationAdvice]:
    session = get_session()
    try:
        q = session.query(OperationAdviceOrm).filter(OperationAdviceOrm.code == code)
        return [r.to_model() for r in q.order_by(OperationAdviceOrm.date.asc()).all()]
    finally:
        session.close()


def find_by_date(date: date) -> list[OperationAdvice]:
    session = get_session()
    try:
        results = (session.query(OperationAdviceOrm)
                   .filter(OperationAdviceOrm.date == date)
                   .order_by(OperationAdviceOrm.code.asc()).all())
        return [r.to_model() for r in results]
    finally:
        session.close()
