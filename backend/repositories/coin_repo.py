import logging

from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from core.db import AsyncSessionLocal
from core.time import now_utc
from models.database import Coin

log = logging.getLogger(__name__)


async def upsert_many(coins_raw: list[dict]) -> int:
    """Upsert list coin từ CoinGecko. `coins_raw` là JSON gốc của CoinGecko.
    Trả về số bản ghi xử lý."""
    if not coins_raw:
        return 0

    rows = []
    now = now_utc()
    for idx, c in enumerate(coins_raw):
        try:
            rows.append(
                {
                    "id": c["id"],
                    "symbol": str(c.get("symbol", "")).upper(),
                    "name": c.get("name", ""),
                    "image_url": c.get("image", ""),
                    "rank": int(c.get("market_cap_rank") or idx + 1),
                    "updated_at": now,
                }
            )
        except Exception as e:
            log.warning(f"upsert_many bỏ qua coin lỗi: {e}")

    if not rows:
        return 0

    stmt = sqlite_insert(Coin).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Coin.id],
        set_={
            "symbol": stmt.excluded.symbol,
            "name": stmt.excluded.name,
            "image_url": stmt.excluded.image_url,
            "rank": stmt.excluded.rank,
            "updated_at": stmt.excluded.updated_at,
        },
    )
    async with AsyncSessionLocal() as session:
        await session.execute(stmt)
        await session.commit()
    return len(rows)


async def upsert_many_ranked_by_symbol(coins_raw: list[dict]) -> int:
    """Upsert danh sách coin đã xếp hạng sẵn (1..N) theo symbol.

    Quy tắc:
    - Tái sử dụng id cũ nếu symbol đã tồn tại trong DB (tránh trùng coin).
    - Tăng rank toàn bộ coin hiện có lên +10000 trước khi upsert danh sách mới,
      để top list mới luôn đứng đầu mà không cần xoá dữ liệu lịch sử.
    """
    if not coins_raw:
        return 0

    now = now_utc()
    async with AsyncSessionLocal() as session:
        existing = await session.execute(
            select(Coin.id, Coin.symbol, Coin.name, Coin.image_url)
        )
        symbol_to_existing: dict[str, tuple[str, str | None, str | None]] = {}
        for coin_id, symbol, name, image_url in existing.all():
            if symbol:
                symbol_to_existing[str(symbol).upper()] = (
                    coin_id,
                    name,
                    image_url,
                )

        rows = []
        for idx, c in enumerate(coins_raw):
            try:
                symbol = str(c.get("symbol", "")).upper()
                if not symbol:
                    continue
                existing_row = symbol_to_existing.get(symbol)
                existing_id = existing_row[0] if existing_row else None
                existing_name = (existing_row[1] if existing_row else None) or ""
                existing_image = (existing_row[2] if existing_row else None) or ""

                incoming_name = str(c.get("name") or symbol).strip()
                if incoming_name.upper() == symbol and existing_name:
                    final_name = existing_name
                else:
                    final_name = incoming_name or existing_name or symbol

                incoming_image = str(c.get("image") or "").strip()
                final_image = incoming_image or existing_image

                coin_id = existing_id or str(c.get("id") or symbol.lower())
                rows.append(
                    {
                        "id": coin_id,
                        "symbol": symbol,
                        "name": final_name,
                        "image_url": final_image,
                        "rank": int(c.get("rank") or idx + 1),
                        "updated_at": now,
                    }
                )
            except Exception as e:
                log.warning(f"upsert_many_ranked_by_symbol bỏ qua coin lỗi: {e}")

        if not rows:
            return 0

        # Đẩy rank cũ xuống thấp để top mới luôn được ưu tiên khi sort ASC.
        await session.execute(update(Coin).values(rank=Coin.rank + 10000))

        stmt = sqlite_insert(Coin).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=[Coin.id],
            set_={
                "symbol": stmt.excluded.symbol,
                "name": stmt.excluded.name,
                "image_url": stmt.excluded.image_url,
                "rank": stmt.excluded.rank,
                "updated_at": stmt.excluded.updated_at,
            },
        )
        await session.execute(stmt)
        await session.commit()
    return len(rows)


async def get_sorted_by_rank() -> list[Coin]:
    """Trả list Coin ORM, sort theo rank ASC."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Coin).order_by(Coin.rank.asc()))
        return list(result.scalars().all())


async def get_by_id(coin_id: str) -> Coin | None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Coin).where(Coin.id == coin_id)
        )
        return result.scalar_one_or_none()
