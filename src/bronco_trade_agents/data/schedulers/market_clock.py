"""
市场时钟 (Market Clock).
负责判断当前是否为交易时段（Pre-market, Regular, After-hours），并处理时区转换。
集成了数据库日历配置 (MarketCalendar) 以处理节假日和提前闭市。
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from enum import Enum
from typing import Dict, Optional
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from ...config import settings
from ..models import MarketCalendar

logger = logging.getLogger(__name__)


class MarketPhase(str, Enum):
    """市场交易阶段"""
    CLOSED = "closed"
    PRE_MARKET = "pre_market"
    REGULAR = "regular"
    AFTER_HOURS = "after_hours"


class MarketClock:
    """
    提供美股交易时段判断逻辑。
    基于 America/New_York 时区。
    支持从数据库加载特殊交易日历（节假日/早收）。
    """

    TIMEZONE = ZoneInfo(settings.market_timezone)
    
    # 内存缓存：{date: MarketCalendar对象}
    _calendar_cache: Dict[date, MarketCalendar] = {}

    @classmethod
    def load_calendar_cache(cls, session: Session, start_date: Optional[date] = None, end_date: Optional[date] = None):
        """
        从数据库加载日历配置到内存缓存。
        建议在应用启动时调用一次，或每天定时刷新。
        
        :param session: 数据库会话
        :param start_date: 加载起始日期 (默认: 今天)
        :param end_date: 加载结束日期 (默认: 今年年底)
        """
        today = cls.now().date()
        start = start_date or today
        # 默认加载到明年年初，覆盖足够长的时间
        end = end_date or date(today.year + 1, 1, 1)

        logger.info(f"Loading market calendar from {start} to {end}...")
        
        try:
            records = session.query(MarketCalendar).filter(
                MarketCalendar.date >= start,
                MarketCalendar.date <= end
            ).all()
            
            count = 0
            for r in records:
                cls._calendar_cache[r.date] = r
                count += 1
            
            logger.info(f"Loaded {count} calendar entries into cache.")
        except Exception as e:
            logger.error(f"Failed to load market calendar: {e}")
            # 不抛出异常，允许降级到默认逻辑

    @classmethod
    def now(cls) -> datetime:
        """获取当前的东部时间 (ET)。"""
        return datetime.now(cls.TIMEZONE)

    @classmethod
    def get_market_phase(cls, dt: datetime | None = None) -> MarketPhase:
        """
        判断指定时间（默认为当前时间）处于哪个交易阶段。
        优先检查数据库配置（节假日），其次检查常规时间表。
        """
        if dt is None:
            dt = cls.now()
        else:
            # 确保转换为目标时区 (ET)
            if dt.tzinfo is None:
                # 假设无时区时间为 UTC（视业务约定），这里转换为 ET
                # 如果传入的是 naive time，最好先 replace(tzinfo=...) 明确来源
                # 这里为了稳健，假设它是 UTC
                dt = dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(cls.TIMEZONE)
            else:
                dt = dt.astimezone(cls.TIMEZONE)

        current_date = dt.date()
        current_time = dt.time()
        hours = settings.market_hours

        # --- 1. 检查数据库缓存 (特殊日历) ---
        cal_entry = cls._calendar_cache.get(current_date)
        
        if cal_entry:
            # 显式休市
            if cal_entry.status == 'closed':
                return MarketPhase.CLOSED
            
            # 提前闭市 (Early Close)
            # 通常 Early Close 发生在 Regular 之后 (如 13:00)，此时没有 After Hours
            if cal_entry.status == 'early_close':
                # 如果当前时间超过了设定的关闭时间
                if cal_entry.close_time and current_time >= cal_entry.close_time:
                    return MarketPhase.CLOSED
                
                # 如果还没到关闭时间，继续走下面的判断逻辑，
                # 但需要注意 Early Close 日通常没有 After Hours
                # 这里简单处理：如果当前时间 > regular_close 但 < early_close_time (罕见)，
                # 或者在 regular 期间。
                # 实际上 Early Close 修改的是 regular_close 的时间。
                
                # 动态调整今日的收盘时间
                effective_regular_close = cal_entry.close_time or hours.regular_close
                # Early Close 日通常没有盘后
                effective_after_close = effective_regular_close 
                
                if hours.pre_market_open <= current_time < hours.regular_open:
                    return MarketPhase.PRE_MARKET
                elif hours.regular_open <= current_time < effective_regular_close:
                    return MarketPhase.REGULAR
                else:
                    return MarketPhase.CLOSED

        # --- 2. 常规逻辑 (周末检查) ---
        # 如果数据库没说今天要上班，且今天是周末 -> 休市
        # 如果数据库显式说 'open' (例如周末调休)，上面的 if cal_entry 会处理吗？
        # 目前逻辑：只有 closed/early_close 会被缓存命中处理。
        # 如果需要支持“周末加班”，需扩展 status='open' 逻辑。美股通常无周末调休。
        if dt.weekday() >= 5:
            return MarketPhase.CLOSED

        # --- 3. 常规时间段检查 ---
        if hours.pre_market_open <= current_time < hours.regular_open:
            return MarketPhase.PRE_MARKET
        
        elif hours.regular_open <= current_time < hours.regular_close:
            return MarketPhase.REGULAR
        
        elif hours.after_hours_open <= current_time < hours.after_hours_close:
            return MarketPhase.AFTER_HOURS
        
        else:
            return MarketPhase.CLOSED

    @classmethod
    def is_market_open(cls, include_extended: bool = True) -> bool:
        """
        判断当前是否开市。
        :param include_extended: 是否包含盘前盘后。默认为 True (全时段采集)。
        """
        phase = cls.get_market_phase()
        
        if phase == MarketPhase.CLOSED:
            return False
        
        if not include_extended:
            return phase == MarketPhase.REGULAR
        
        return phase in (MarketPhase.PRE_MARKET, MarketPhase.REGULAR, MarketPhase.AFTER_HOURS)

    @classmethod
    def time_until_next_open(cls) -> timedelta:
        """
        计算距离下一次开盘（Pre-market）还有多久。
        用于休市时的 Sleep 策略。
        """
        now = cls.now()
        today = now.date()
        
        # 今天的开盘时间
        today_open = datetime.combine(today, settings.market_hours.pre_market_open, tzinfo=cls.TIMEZONE)
        
        # 如果还没到今天的开盘时间
        if now < today_open:
            return today_open - now
        
        # 往后找每一天，直到找到一个非周末且非假日的日子
        next_day = today + timedelta(days=1)
        while True:
            # 1. 检查缓存是否休市
            cal_entry = cls._calendar_cache.get(next_day)
            is_holiday = cal_entry and cal_entry.status == 'closed'
            
            # 2. 检查周末
            is_weekend = next_day.weekday() >= 5
            
            if not is_holiday and not is_weekend:
                break
            
            next_day += timedelta(days=1)
            
        next_open = datetime.combine(next_day, settings.market_hours.pre_market_open, tzinfo=cls.TIMEZONE)
        return next_open - now