"""Async Engine und Session-Factory."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import config
from .models import Base

_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def init_engine(url: str | None = None) -> None:
    """Engine einmalig initialisieren (beim App-Start aufrufen)."""
    global _engine, _session_factory
    _engine = create_async_engine(
        url or config.DATABASE_URL,
        echo=False,        # auf True setzen für SQL-Debug-Ausgabe
        pool_size=5,
        max_overflow=10,
    )
    _session_factory = async_sessionmaker(
        _engine, expire_on_commit=False, class_=AsyncSession
    )


async def create_tables() -> None:
    """Alle Tabellen anlegen (Prototyp – für Produktion: Alembic nutzen)."""
    if _engine is None:
        raise RuntimeError("init_engine() muss zuerst aufgerufen werden.")
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Async Context-Manager für eine DB-Session mit automatischem Rollback bei Fehler."""
    if _session_factory is None:
        raise RuntimeError("init_engine() muss zuerst aufgerufen werden.")
    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
