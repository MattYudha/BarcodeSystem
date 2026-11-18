from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from sqlalchemy import text

from bhv import __version__
from bhv.db import dispose_engine, get_sessionmaker


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await dispose_engine()


app = FastAPI(
    title="Bhavia Inventory API",
    version=__version__,
    lifespan=lifespan,
)


@app.get("/healthz", tags=["ops"])
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz", tags=["ops"])
async def readyz(response: Response) -> dict[str, str]:
    try:
        async with get_sessionmaker()() as s:
            await s.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 - laporan readiness, bukan error handling bisnis
        response.status_code = 503
        return {"status": "db_unavailable"}
    return {"status": "ready"}
