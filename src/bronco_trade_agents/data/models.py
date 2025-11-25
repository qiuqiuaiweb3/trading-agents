"""
SQLAlchemy ORM 模型集合。

包含：
- trades / quotes 时间序列表（TimescaleDB hypertable）
- ohlcv_1m 连续聚合视图（仅定义 metadata，建表由 SQL 完成）
- market_calendar 节假日/早收配置
- ai_decisions 记录 AI 策略切换生命周期
"""
from __future__ import annotations

from datetime import date, datetime, time
from typing import Optional

from sqlalchemy import (
    TIMESTAMP,
    BigInteger,
    Column,
    Date,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


# ---------- Trades & Quotes ----------


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    time: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), index=True, nullable=False)
    ticker: Mapped[str] = mapped_column(String(16), index=True, nullable=False)

    price: Mapped[float] = mapped_column(Numeric, nullable=False)
    size: Mapped[float] = mapped_column(Numeric, nullable=False)

    exchange: Mapped[Optional[int]] = mapped_column(Integer)
    conditions: Mapped[Optional[list[int]]] = mapped_column(ARRAY(Integer))
    correction: Mapped[Optional[int]] = mapped_column(Integer)
    tape: Mapped[Optional[int]] = mapped_column(Integer)
    trf_id: Mapped[Optional[int]] = mapped_column(Integer)
    trf_timestamp: Mapped[Optional[int]] = mapped_column(BigInteger)
    participant_timestamp: Mapped[Optional[int]] = mapped_column(BigInteger)

    massive_trade_id: Mapped[Optional[str]] = mapped_column(String(64), unique=False)
    sequence_number: Mapped[Optional[int]] = mapped_column(BigInteger, index=True)

    __table_args__ = (
        UniqueConstraint("time", "ticker", "massive_trade_id", name="uq_trades_unique_trade"),
    )


class Quote(Base):
    __tablename__ = "quotes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    time: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), index=True, nullable=False)
    ticker: Mapped[str] = mapped_column(String(16), index=True, nullable=False)

    bid_price: Mapped[Optional[float]] = mapped_column(Numeric)
    bid_size: Mapped[Optional[float]] = mapped_column(Numeric)
    bid_exchange: Mapped[Optional[int]] = mapped_column(Integer)

    ask_price: Mapped[Optional[float]] = mapped_column(Numeric)
    ask_size: Mapped[Optional[float]] = mapped_column(Numeric)
    ask_exchange: Mapped[Optional[int]] = mapped_column(Integer)

    conditions: Mapped[Optional[list[int]]] = mapped_column(ARRAY(Integer))
    indicators: Mapped[Optional[list[int]]] = mapped_column(ARRAY(Integer))
    participant_timestamp: Mapped[Optional[int]] = mapped_column(BigInteger)
    sequence_number: Mapped[Optional[int]] = mapped_column(BigInteger, index=True)
    tape: Mapped[Optional[int]] = mapped_column(Integer)
    # --- 新增：唯一约束以支持幂等写入 ---
    __table_args__ = (
        UniqueConstraint("time", "ticker", "sequence_number", name="uq_quotes_unique_quote"),
    )

# ---------- Market Calendar ----------


class MarketCalendar(Base):
    __tablename__ = "market_calendar"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)  # 'open', 'closed', 'early_close'
    open_time: Mapped[Optional[time]] = mapped_column(Time)
    close_time: Mapped[Optional[time]] = mapped_column(Time)
    description: Mapped[Optional[str]] = mapped_column(Text)


# ---------- AI Decisions ----------


class AIDecision(Base):
    __tablename__ = "ai_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    strategy_name: Mapped[str] = mapped_column(String(64), nullable=False)

    start_time: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), index=True, nullable=False)
    end_time: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True), index=True)

    reason: Mapped[Optional[str]] = mapped_column(Text)
    ai_model_version: Mapped[Optional[str]] = mapped_column(String(32))

    initial_price: Mapped[float] = mapped_column(Numeric, nullable=False)
    final_price: Mapped[Optional[float]] = mapped_column(Numeric)

    pnl_amount: Mapped[Optional[float]] = mapped_column(Numeric)
    pnl_percentage: Mapped[Optional[float]] = mapped_column(Numeric)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)  # active/completed/force_stopped