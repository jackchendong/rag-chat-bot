import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
import uvicorn

from app.api import router as api_router
from app.core.database import Base, engine


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(lifespan=lifespan)

app.include_router(api_router, prefix="/api")


front_dist_dir = Path(__file__).resolve().parent.parent / "front" / "dist"
if front_dist_dir.exists():
    app.mount("/", StaticFiles(directory=str(front_dist_dir), html=True), name="front")


if __name__ == "__main__":
    load_dotenv()
    port = int(os.getenv("SERVER_PORT", "8000"))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=True)
