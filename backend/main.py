import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from core.db import engine
from models.database import Base
from jobs.scheduler import scheduler, register_jobs
from analyzers.sentiment import load_sentiment
from clients.http_client import init_http, close_http
from routers import coins as coins_router
from routers import macro as macro_router
from routers import news as news_router
from routers import chat as chat_router
from routers import history as history_router
from services.macro_service import load_cache_from_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Khởi tạo DB (WAL pragma đã set bởi event listener trong core/db.py)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Migration nhẹ idempotent — SQLAlchemy create_all KHÔNG thêm cột mới
    # vào bảng đã tồn tại. Cột `social_mentions` được thêm ở phase
    # radar-refactor nên cần ALTER TABLE thủ công. Chạy trong connection
    # riêng để lỗi "duplicate column" không rollback transaction create_all.
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "ALTER TABLE sentiment_scores "
                    "ADD COLUMN social_mentions INTEGER"
                )
            )
    except Exception:
        # Cột đã tồn tại → SQLite raise OperationalError, bỏ qua.
        pass

    # 2. Load sentiment model vào RAM (1 lần duy nhất)
    load_sentiment()

    # 3. Singleton httpx.AsyncClient — APScheduler jobs import
    #    shared_client() trực tiếp, KHÔNG gắn app.state.
    init_http()

    # 4. Restore macro cache từ DB (nguồn sự thật) — quy tắc 8.
    await load_cache_from_db()

    # 5. Khởi động scheduler
    register_jobs()
    scheduler.start()

    yield

    # Shutdown theo thứ tự ngược
    scheduler.shutdown()
    await close_http()


app = FastAPI(title="Cryptsen API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(coins_router.router)
app.include_router(news_router.router)
app.include_router(macro_router.router)
app.include_router(chat_router.router)
app.include_router(history_router.router)


@app.get("/")
async def root():
    return {"name": "Cryptsen API", "status": "ok"}
