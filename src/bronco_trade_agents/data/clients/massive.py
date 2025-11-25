"""
Massive API 客户端封装。
实现与 Massive V3 REST API 的交互，支持自动分页和重试。
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, Iterator, Optional

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from ...config import settings

logger = logging.getLogger(__name__)


class RESTClient:
    """
    Massive Data V3 API 客户端。
    模拟官方 SDK 行为，提供生成器模式的数据获取方法，自动处理分页。
    """

    BASE_URL = "https://api.massive.com/v3"

    def __init__(
        self,
        api_key: str | None = None,
        timeout: float = 30.0,
    ):
        """
        初始化客户端。

        :param api_key: API Key。若未提供，尝试从 settings 获取。
        :param timeout: 请求超时时间（秒）。
        """
        self.api_key = api_key or settings.massive_api_key.get_secret_value()
        self.timeout = timeout

        # 初始化持久化 session
        # 注意：Massive API 使用 query parameter (apiKey) 进行认证，而非 Header
        self._client = httpx.Client(
            base_url=self.BASE_URL,
            headers={
                "Accept": "application/json",
            },
            # 将 apiKey 作为默认查询参数注入到所有请求中
            params={"apiKey": self.api_key},
            timeout=self.timeout,
        )

    def close(self) -> None:
        """关闭底层连接。"""
        self._client.close()

    def __enter__(self) -> "RESTClient":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.NetworkError, httpx.TimeoutException, httpx.HTTPStatusError)),
        reraise=True,
    )
    def _get(self, url: str, params: Dict[str, Any] | None = None) -> Dict[str, Any]:
        """
        执行 GET 请求，处理重试和错误检查。
        如果 url 是完整路径（如 next_url），httpx 会自动忽略 base_url。
        """
        response = self._client.get(url, params=params)
        response.raise_for_status()
        return response.json()

    def _paginate(self, endpoint: str, params: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
        url = endpoint
        current_params = params
        page_count = 0

        while True:
            page_count += 1
            logger.debug(f"Fetching page {page_count} (URL: {url})") # 增加日志
            
            data = self._get(url, params=current_params)
            
            results = data.get("results", [])
            if not results:
                # 如果某页没数据，通常意味着结束，但也取决于 API 行为
                if not data.get("next_url"):
                    break

            for item in results:
                yield item

            next_url = data.get("next_url")
            if not next_url:
                break
            
            url = next_url
            current_params = None

    def list_trades(
        self,
        ticker: str,
        date: date | str | None = None,
        limit: int = 1000,
        sort: str = "timestamp",
        order: str = "asc",
    ) -> Iterator[Dict[str, Any]]:
        """
        获取逐笔成交数据 (Trades)。自动处理分页。

        对应 API: GET /v3/trades/{stockTicker}

        :param ticker: 股票代码 (e.g. "AAPL")
        :param date: 日期 "YYYY-MM-DD" 或 None。对应 API 的 `timestamp` 参数。
        :param limit: 每页数量 (默认 1000, 最大 50000)
        :param sort: 排序字段 (默认 "timestamp")
        :param order: 排序方向 ("asc" or "desc")
        :return: 交易记录字典的迭代器
        """
        endpoint = f"/trades/{ticker}"
        params = {
            "limit": limit,
            "sort": sort,
            "order": order,
        }
        if date:
            # API 文档要求参数名为 timestamp，但接受 YYYY-MM-DD 格式
            params["timestamp"] = date.isoformat() if hasattr(date, "isoformat") else date

        logger.debug(f"Starting trade fetch for {ticker} (date={date})")
        yield from self._paginate(endpoint, params)

    def list_quotes(
        self,
        ticker: str,
        date: date | str | None = None,
        limit: int = 1000,
        sort: str = "timestamp",
        order: str = "asc",
    ) -> Iterator[Dict[str, Any]]:
        """
        获取报价数据 (Quotes)。自动处理分页。

        对应 API: GET /v3/quotes/{stockTicker}
        """
        endpoint = f"/quotes/{ticker}"
        params = {
            "limit": limit,
            "sort": sort,
            "order": order,
        }
        if date:
            params["timestamp"] = date.isoformat() if hasattr(date, "isoformat") else date

        logger.debug(f"Starting quote fetch for {ticker} (date={date})")
        yield from self._paginate(endpoint, params)