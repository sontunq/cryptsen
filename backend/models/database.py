from sqlalchemy import (
    Column,
    String,
    Integer,
    Float,
    DateTime,
    ForeignKey,
    Text,
    Index,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Coin(Base):
    __tablename__ = "coins"
    id = Column(String, primary_key=True)
    symbol = Column(String, index=True)
    name = Column(String)
    image_url = Column(String)
    rank = Column(Integer, index=True)
    updated_at = Column(DateTime(timezone=True))  # UTC


class SentimentScore(Base):
    __tablename__ = "sentiment_scores"
    id = Column(Integer, primary_key=True, autoincrement=True)
    coin_id = Column(String, ForeignKey("coins.id"), index=True)
    score_total = Column(Float, default=0)
    score_news = Column(Float, default=0)
    score_macro = Column(Float, default=0)
    score_social = Column(Float, default=0)
    # Khối lượng đề cập Reddit 24H — NULL khi chưa có dữ liệu / lỗi fetch.
    social_mentions = Column(Integer, nullable=True)
    score_sentiment = Column(Float, default=0)
    label = Column(String, default="Không có dữ liệu")
    summary = Column(Text, nullable=True)
    calculated_at = Column(DateTime(timezone=True))  # UTC

    __table_args__ = (
        Index("ix_sentiment_coin_time", "coin_id", "calculated_at"),
    )


class NewsItem(Base):
    __tablename__ = "news_items"
    id = Column(String, primary_key=True)  # hash của URL
    coin_id = Column(String, nullable=True, index=True)  # None = tin macro
    title = Column(String)
    url = Column(String, unique=True)  # cache key
    source = Column(String)  # coindesk|reddit|forexfactory
    sentiment_label = Column(String)  # positive|neutral|negative
    sentiment_score = Column(Float)
    reason = Column(Text, nullable=True)
    # Reddit-only fields (nullable cho CoinDesk/ForexFactory)
    upvotes = Column(Integer, nullable=True)
    num_comments = Column(Integer, nullable=True)
    published_at = Column(DateTime(timezone=True))  # UTC
    crawled_at = Column(DateTime(timezone=True))  # UTC

    __table_args__ = (
        Index(
            "ix_news_filter",
            "coin_id",
            "source",
            "sentiment_label",
            "published_at",
        ),
    )


class MacroEvent(Base):
    __tablename__ = "macro_events"
    id = Column(String, primary_key=True)  # sha1(event|date|currency)[:16]
    event_name = Column(String)
    event_date = Column(DateTime(timezone=True), index=True)  # UTC
    currency = Column(String)
    impact = Column(String)
    actual = Column(String, nullable=True)
    forecast = Column(String, nullable=True)
    previous = Column(String, nullable=True)
    sentiment_score = Column(Float, default=5.0)
    sentiment_label = Column(String, default="neutral")
    scraped_at = Column(DateTime(timezone=True))  # UTC
