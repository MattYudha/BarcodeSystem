"""Koneksi DB async.

Pola transaksi: dependency `get_db` memberi AsyncSession; endpoint yang menulis WAJIB memanggil
`await db.commit()` sendiri sebelum return. Jika ada exception, session ditutup -> rollback.
(Commit eksplisit menjamin data tersimpan SEBELUM respons sukses dikirim ke client.)
"""

from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import Row, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from bhv.config import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine, _sessionmaker
    if _engine is None:
        _engine = create_async_engine(
            get_settings().database_url,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=10,
            connect_args={"options": "-c timezone=UTC"},
        )
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    get_engine()
    assert _sessionmaker is not None
    return _sessionmaker


async def get_db() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as session:
        yield session


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


# --- helper query ringkas (SQL eksplisit; logika stok ada di DB) ---------------------------


async def fetch_one(db: AsyncSession, sql: str, **params: Any) -> Row[Any] | None:
    return (await db.execute(text(sql), params)).first()


async def fetch_all(db: AsyncSession, sql: str, **params: Any) -> list[Row[Any]]:
    return list((await db.execute(text(sql), params)).all())


async def fetch_val(db: AsyncSession, sql: str, **params: Any) -> Any:
    return (await db.execute(text(sql), params)).scalar()


async def execute(db: AsyncSession, sql: str, **params: Any) -> int:
    result = await db.execute(text(sql), params)
    return int(getattr(result, "rowcount", 0) or 0)
