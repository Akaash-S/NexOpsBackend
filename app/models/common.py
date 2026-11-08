"""
Common utilities and helpers for SQLModel models.
"""
from datetime import datetime, timezone
from typing import Optional
from sqlmodel import SQLModel


def utc_now() -> datetime:
    """Return current naive UTC datetime for TIMESTAMP WITHOUT TIME ZONE columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_naive_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Convert datetime to naive UTC.
    None -> None.
    Aware -> converted to UTC then tzinfo stripped.
    Naive -> unchanged.
    """
    if dt is None:
        return None
    if dt.tzinfo is not None and dt.tzinfo.utcoffset(dt) is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


class BaseTable(SQLModel):
    """Base class for SQLModel tables that normalizes all datetime attributes to naive UTC."""

    def __init__(self, **data):
        for k, v in list(data.items()):
            if isinstance(v, datetime) and v.tzinfo is not None:
                data[k] = to_naive_utc(v)
        super().__init__(**data)

    def __setattr__(self, name, value):
        if isinstance(value, datetime) and value.tzinfo is not None:
            value = to_naive_utc(value)
        super().__setattr__(name, value)


