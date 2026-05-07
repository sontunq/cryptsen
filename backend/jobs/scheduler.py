from datetime import datetime, timedelta

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from core.config import settings
from core.time import VN_TZ

# ⚠️ Import callable TRỰC TIẾP (quy tắc 20) — string path "module:func"
# sẽ raise ModuleNotFoundError lúc TRIGGER (30 phút sau startup)
# thay vì lúc register.
from clients.binance import fetch_top_volume_coins
from services.macro_service import update_macro_cache
from services.score_engine import compute_tier

# misfire_grace_time + coalesce: tránh dồn job khi 1 cycle chạy lâu
# hơn interval. max_instances=1: chặn 2 job cùng id chạy song song.
scheduler = AsyncIOScheduler(
    timezone=pytz.timezone("Asia/Ho_Chi_Minh"),
    job_defaults={
        "misfire_grace_time": 300,
        "coalesce": True,
        "max_instances": 1,
    },
)


def register_jobs():
    now = datetime.now(VN_TZ)

    # SEED: ép chạy ngay khi startup (quy tắc 20) — nếu không,
    # lần đầu fetch_coins chạy sau 24h, tier1 chạy sau 30 phút với
    # DB rỗng → UI trống, macro = 5.0 default.
    scheduler.add_job(
        fetch_top_volume_coins,
        "interval",
        hours=24,
        id="fetch_coins",
        kwargs={"limit": settings.binance_top_coins},
        next_run_time=now + timedelta(seconds=5),
    )
    scheduler.add_job(
        update_macro_cache,
        "interval",
        hours=settings.macro_refresh_hours,
        id="macro_calendar",
        next_run_time=now + timedelta(seconds=30),
    )
    # Tier 1 chạy sau khi fetch_coins + macro đã xong (~60s buffer)
    scheduler.add_job(
        compute_tier,
        "interval",
        minutes=settings.tier1_minutes,
        id="tier1",
        kwargs={"tier": 1},
        next_run_time=now + timedelta(seconds=60),
    )
    scheduler.add_job(
        compute_tier,
        "interval",
        hours=settings.tier2_hours,
        id="tier2",
        kwargs={"tier": 2},
        next_run_time=now + timedelta(seconds=120),
    )
    scheduler.add_job(
        compute_tier,
        "interval",
        hours=settings.tier3_hours,
        id="tier3",
        kwargs={"tier": 3},
        next_run_time=now + timedelta(seconds=180),
    )
    scheduler.add_job(
        compute_tier,
        "interval",
        hours=settings.tier4_hours,
        id="tier4",
        kwargs={"tier": 4},
        next_run_time=now + timedelta(seconds=240),
    )
