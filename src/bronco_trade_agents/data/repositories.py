"""
数据仓储层 (Repository Layer)。
负责将 API 原始数据转换为 ORM 对象，并高效写入 TimescaleDB/PostgreSQL。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ..config import settings
from .models import Quote, Trade

logger = logging.getLogger(__name__)


class MarketDataRepository:
    """
    行情数据仓库。
    处理 Trade 和 Quote 数据的清洗、转换与持久化。
    """

    def __init__(self, session: Session):
        self.session = session

    @staticmethod
    def _ns_to_datetime(ns_timestamp: int | None) -> datetime | None:
        """
        将纳秒时间戳转换为带时区 (UTC) 的 datetime 对象。
        Massive API 返回的是纳秒整数。
        """
        if ns_timestamp is None:
            return None
        # 转换为秒 (float)
        ts_seconds = ns_timestamp / 1_000_000_000.0
        # 统一使用 UTC，入库后由数据库处理时区或应用层转换
        return datetime.fromtimestamp(ts_seconds, tz=timezone.utc)

    def save_trades(self, ticker: str, trades_data: List[Dict[str, Any]]) -> int:
        """
        批量保存 Trade 数据。
        使用 INSERT ... ON CONFLICT DO NOTHING 忽略重复数据。

        :param ticker: 股票代码
        :param trades_data: API 返回的原始字典列表
        :return: 成功插入的记录数 (包含被忽略的重复项，取决于 DB 驱动反馈，通常仅用于日志)
        """
        if not trades_data:
            return 0

        # 1. 数据转换映射
        records = []
        for t in trades_data:
            # 必须字段检查
            sip_ts = t.get("sip_timestamp")
            if not sip_ts:
                continue

            # 构建符合 ORM 模型定义的字典
            record = {
                "time": self._ns_to_datetime(sip_ts),
                "ticker": ticker,
                "price": t.get("price"),
                "size": t.get("size"),
                "exchange": t.get("exchange"),
                "conditions": t.get("conditions"),  # ARRAY(Integer)
                "correction": t.get("correction"),
                "tape": t.get("tape"),
                "trf_id": t.get("trf_id"),
                "trf_timestamp": t.get("trf_timestamp"), # BigInt，无需转换
                "participant_timestamp": t.get("participant_timestamp"), # BigInt
                "massive_trade_id": str(t.get("id")), # 映射 ID
                "sequence_number": t.get("sequence_number"),
            }
            records.append(record)

        if not records:
            return 0

        # 2. 构造批量插入语句 (PostgreSQL 特有的 ON CONFLICT)
        stmt = pg_insert(Trade).values(records)
        
        # 定义冲突处理：如果 (time, ticker, massive_trade_id) 冲突，则不做任何操作
        stmt = stmt.on_conflict_do_nothing(
            constraint="uq_trades_unique_trade" 
        )

        # 3. 执行
        try:
            result = self.session.execute(stmt)
            self.session.commit()
            # rowcount 在 on_conflict_do_nothing 下可能不准确反映实际新增行数，但在批量场景下足够作为指标
            return result.rowcount
        except Exception as e:
            self.session.rollback()
            logger.error(f"Failed to save batch trades for {ticker}: {e}")
            raise

    def save_quotes(self, ticker: str, quotes_data: List[Dict[str, Any]]) -> int:
        """
        批量保存 Quote 数据。
        使用 INSERT ... ON CONFLICT DO NOTHING 忽略重复数据。
        """
        if not quotes_data:
            return 0

        records = []
        for q in quotes_data:
            sip_ts = q.get("sip_timestamp")
            if not sip_ts:
                continue

            record = {
                "time": self._ns_to_datetime(sip_ts),
                "ticker": ticker,
                "bid_price": q.get("bid_price"),
                "bid_size": q.get("bid_size"),
                "bid_exchange": q.get("bid_exchange"),
                "ask_price": q.get("ask_price"),
                "ask_size": q.get("ask_size"),
                "ask_exchange": q.get("ask_exchange"),
                "conditions": q.get("conditions"),
                "indicators": q.get("indicators"),
                "participant_timestamp": q.get("participant_timestamp"),
                "sequence_number": q.get("sequence_number"),
                "tape": q.get("tape"),
            }
            records.append(record)

        if not records:
            return 0

        # 使用 PostgreSQL 特有的 ON CONFLICT 处理重复数据
        stmt = pg_insert(Quote).values(records)
        stmt = stmt.on_conflict_do_nothing(
            constraint="uq_quotes_unique_quote"
        )

        try:
            result = self.session.execute(stmt)
            self.session.commit()
            return result.rowcount
        except Exception as e:
            self.session.rollback()
            logger.error(f"Failed to save batch quotes for {ticker}: {e}")
            raise

# # 为了兼容上面 save_quotes 中可能用到的通用 insert，导入一下
# from sqlalchemy import insert
