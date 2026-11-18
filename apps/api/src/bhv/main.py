from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import text

from bhv import __version__, errors
from bhv.config import get_settings
from bhv.db import dispose_engine, get_sessionmaker
from bhv.routers import auth, categories, products, users

API_PREFIX = "/api/v1"
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await dispose_engine()


app = FastAPI(
    title="Bhavia Inventory API",
    version=__version__,
    lifespan=lifespan,
    docs_url=f"{API_PREFIX}/docs",
    openapi_url=f"{API_PREFIX}/openapi.json",
)
errors.install(app)


@app.middleware("http")
async def csrf_and_headers(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    # CSRF: cookie SameSite=Lax + tolak request mutasi dari origin browser yang tidak dikenal.
    # Client non-browser (tanpa header Origin) tetap diizinkan; mereka tidak membawa cookie korban.
    if request.method not in _SAFE_METHODS:
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") not in get_settings().allowed_origins:
            err = errors.AppError("CSRF_REJECTED", {"origin": origin})
            return JSONResponse(
                {"code": err.code, "message": err.message, "details": err.details},
                status_code=err.status,
            )
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("X-Frame-Options", "DENY")
    if request.url.path.startswith(API_PREFIX) and "cache-control" not in response.headers:
        response.headers["Cache-Control"] = "no-store"
    return response


for r in (auth.router, users.router, categories.router, products.router):
    app.include_router(r, prefix=API_PREFIX)


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
