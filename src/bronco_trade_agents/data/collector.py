"""
数据采集器 (Collector).
核心调度循环：
1. 检查市场状态 (MarketClock) - 支持盘后 15 分钟缓冲以捕获延迟上报数据
2. 遍历目标股票 (NASDAQ 100)
3. 调用 Client 获取最新 Trade/Quote
4. 调用 Repository 存入数据库
"""
import logging
import time
from datetime import datetime, timedelta
from typing import List

from sqlalchemy.orm import Session

from ..config import TARGET_TICKERS, settings
from ..database import session_scope
from .clients.massive import RESTClient
from .repositories import MarketDataRepository
from .schedulers.market_clock import MarketClock, MarketPhase

logger = logging.getLogger(__name__)


class DataCollector:
    # 闭市后的缓冲时间 (分钟)，用于捕获 TRF 延迟上报的交易
    GRACE_PERIOD_MINUTES = 15

    def __init__(self):
        self.tickers = TARGET_TICKERS

    def should_run(self) -> bool:
        """
        判断当前是否应该运行采集。
        逻辑：
        1. 市场开盘 (Pre/Regular/After)。
        2. 或者处于闭市后 15 分钟内的缓冲期 (Grace Period)。
        """
        if MarketClock.is_market_open(include_extended=True):
            return True

        # 检查是否处于缓冲期
        now = MarketClock.now()
        phase = MarketClock.get_market_phase(now)
        
        # 只有在刚刚闭市 (CLOSED) 且时间在当日 20:00 - 20:15 之间才算缓冲期
        # 简易判断：如果是工作日且时间在 20:00 ~ 20:15 ET
        # 获取今天的盘后结束时间 (通常是 20:00)
        # 注意：这里我们硬编码了 20:00 作为盘后结束基准，更严谨应从 config 读取
        # 但 MarketClock 已经封装了逻辑，如果 phase 是 CLOSED，说明已经过了 After Hours
        
        if phase == MarketPhase.CLOSED:
            # 获取今天的日期和时间
            current_time = now.time()
            # 假设盘后结束是 20:00
            ah_close = settings.market_hours.after_hours_close
            
            # 构造缓冲结束时间
            # 注意跨日问题，但在美股 ET 时间下 20:00 离午夜还早
            grace_end_dt = datetime.combine(now.date(), ah_close) + timedelta(minutes=self.GRACE_PERIOD_MINUTES)
            grace_end = grace_end_dt.time()
            
            # 如果当前时间在 20:00 到 20:15 之间
            if ah_close <= current_time < grace_end:
                # 还需要确认今天是工作日 (MarketClock.get_market_phase 已处理周末返回 CLOSED)
                # 只有当非周末时才允许缓冲
                if now.weekday() < 5: 
                    return True
        
        return False

    def collect_ticker(self, session: Session, client: RESTClient, ticker: str):
        """
        采集单个 Ticker 的数据并入库。
        """
        try:
            # 采集“今天”的数据
            # 注意：Massive API 的 list_trades 支持 date 参数。
            # 为了获取最新数据，我们需要请求当天的日期。
            today = MarketClock.now().date()
            
            # 1. Fetch & Save Trades
            trades_buffer = []
            
            # 尝试倒序获取最新的数据（减少网络传输）
            # limit=1000: 单次请求数量
            for trade in client.list_trades(ticker, date=today, limit=1000, order="desc"):
                trades_buffer.append(trade)
                # 缓冲区满或达到单次同步上限则写入 (例如只同步最新的 2000 条)
                if len(trades_buffer) >= 2000: 
                    break
            
            if trades_buffer:
                repo = MarketDataRepository(session)
                count = repo.save_trades(ticker, trades_buffer)
                # logger.debug(f"Saved {count} trades for {ticker}")

            # 2. Fetch & Save Quotes
            quotes_buffer = []
            for quote in client.list_quotes(ticker, date=today, limit=1000, order="desc"):
                quotes_buffer.append(quote)
                if len(quotes_buffer) >= 2000:
                    break
            
            if quotes_buffer:
                repo = MarketDataRepository(session)
                repo.save_quotes(ticker, quotes_buffer)

            logger.debug(f"Collected {ticker}: {len(trades_buffer)} trades, {len(quotes_buffer)} quotes")

        except Exception as e:
            logger.error(f"Error collecting {ticker}: {e}")

    def run_cycle(self):
        """
        执行一轮采集循环。
        """
        # 使用新的 should_run 逻辑
        if not self.should_run():
            logger.info("Market is closed (and outside grace period). Skipping cycle.")
            return

        logger.info(f"Starting collection cycle for {len(self.tickers)} tickers...")
        start_time = time.time()

        # 实例化 client，复用连接
        with RESTClient() as client:
            for ticker in self.tickers:
                with session_scope() as session:
                    self.collect_ticker(session, client, ticker)
                
                # 简单的节流，避免瞬间打爆 API
                # time.sleep(0.05) 

        duration = time.time() - start_time
        logger.info(f"Cycle completed in {duration:.2f}s")

    def run_forever(self):
        """
        主入口：死循环调度。
        """
        logger.info("Data Collector Service Started.")
        
        # 启动时先加载日历缓存
        with session_scope() as session:
            MarketClock.load_calendar_cache(session)

        while True:
            try:
                if self.should_run():
                    self.run_cycle()
                    
                    # 等待下一个周期
                    # PRD 要求每分钟采集一次
                    time.sleep(settings.collect_interval_seconds)
                else:
                    # 休市时，计算休眠时间
                    wait_time = MarketClock.time_until_next_open()
                    logger.info(f"Market closed. Sleeping for {wait_time} until next open...")
                    
                    sleep_sec = wait_time.total_seconds()
                    # 如果休眠时间很长（> 1小时），每小时醒一次重新 check（防止日历变更或人为干预）
                    if sleep_sec > 3600:
                        time.sleep(3600)
                    else:
                        # 至少睡 1 秒避免 cpu 空转
                        time.sleep(max(1, sleep_sec))
                        
            except KeyboardInterrupt:
                logger.info("Collector stopped by user.")
                break
            except Exception as e:
                logger.error(f"Unexpected error in main loop: {e}", exc_info=True)
                time.sleep(10)  # 出错后稍作等待
