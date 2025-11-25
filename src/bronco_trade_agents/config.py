"""
应用配置中心。

- 统一从 .env / 环境变量中加载敏感信息；
- 定义交易时段、策略频率等常量，供 Data / 策略 / 执行模块共享；
- 提供读取 NASDAQ 100 列表的工具函数（可来自环境变量或本地文件）。
"""
from __future__ import annotations

from datetime import time
from pathlib import Path
from typing import List

from pydantic import BaseModel, Field, PostgresDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class MarketHours(BaseModel):
    """描述某个交易时段的开闭时间（美国东部时间）。"""
    pre_market_open: time = Field(default=time(4, 0))
    pre_market_close: time = Field(default=time(9, 30))
    regular_open: time = Field(default=time(9, 30))
    regular_close: time = Field(default=time(16, 0))
    after_hours_open: time = Field(default=time(16, 0))
    after_hours_close: time = Field(default=time(20, 0))


class Settings(BaseSettings):
    """
    全局配置。默认从项目根目录的 .env 读取，也支持环境变量覆盖。
    """
    model_config = SettingsConfigDict(env_file=(".env",), env_file_encoding="utf-8", extra="ignore")

    massive_api_key: SecretStr = Field(..., alias="MASSIVE_API_KEY")
    database_url: PostgresDsn = Field(..., alias="DATABASE_URL")

    # ticker 文件路径：默认 `src/bronco_trade_agents/nasdaq100.txt`
    tickers_file: Path = Field(
        default=Path(__file__).resolve().parent / "nasdaq100.txt",
        alias="TICKERS_FILE",
    )

    # 采集参数
    collect_interval_seconds: int = Field(60, alias="COLLECT_INTERVAL_SECONDS")
    # strategy_timeframes: Sequence[int] = Field(default=(10, 15, 30, 60), alias="STRATEGY_TIMEFRAMES")

    # 时区配置
    market_timezone: str = Field(default="America/New_York", alias="MARKET_TIMEZONE")

    market_hours: MarketHours = Field(default_factory=MarketHours)


def load_tickers_from_file(file_path: Path) -> List[str]:
    """
    从文本读取 NASDAQ 100 列表。
    要求：每行一个 symbol，可带尾随逗号；允许空行/注释（# 开头）。
    """
    if not file_path.exists():
        raise FileNotFoundError(
            f"未找到 Nasdaq100 列表文件：{file_path}. "
            f"请在项目中创建该文件（每行一个 symbol，以逗号结尾也可）。"
        )

    tickers: List[str] = []
    for raw_line in file_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        symbol = line.rstrip(",").strip().upper()
        if symbol:
            tickers.append(symbol)

    if not tickers:
        raise ValueError(f"{file_path} 内没有有效的 symbol，请确认每行包含股票代码。")

    return tickers




# 单例访问入口
settings = Settings()
TARGET_TICKERS = load_tickers_from_file(settings.tickers_file)

__all__ = [
    "settings",
    "TARGET_TICKERS",
    "MarketHours",
    "Settings",
    "get_target_tickers",
]