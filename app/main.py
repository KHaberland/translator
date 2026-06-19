from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.download import router as download_router
from app.api.estimate import router as estimate_router
from app.api.status import router as status_router
from app.api.stream import router as stream_router
from app.api.translate import router as translate_router
from app.core.config import ensure_storage_dirs


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    ensure_storage_dirs()
    yield

app = FastAPI(
    title="Translator MVP",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(translate_router)
app.include_router(estimate_router)
app.include_router(status_router)
app.include_router(stream_router)
app.include_router(download_router)
