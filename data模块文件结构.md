# Data 模块文件结构设计
---
## 文件结构
src/
└── bronco_trade_agents/
    ├── config.py
    ├── database.py
    ├── utils/
    │   └── logger.py
    └── data/
        ├── __init__.py
        ├── clients/
        │   ├── __init__.py
        │   └── massive.py
        ├── schedulers/
        │   ├── __init__.py
        │   └── market_clock.py
        ├── models.py
        ├── repositories.py
        ├── collector.py
        └── pipeline.py
---

## 各文件职责
  - config.py：集中读取 .env / Secrets（Massive API Key、DB URL、采集频率、交易时区等）。
  - database.py：初始化 TimescaleDB 引擎与 Session，封装 get_session()。
  - utils/logger.py：统一日志格式（时间戳、ticker、级别），供所有模块 import。
  - data/clients/massive.py：封装 Massive RESTClient 调用，提供 fetch_trades(ticker)、fetch_quotes(ticker) 等方法，并实现重试/节流。
  - data/schedulers/market_clock.py：根据 market_calendar 与交易时段决定是否需要采集（例如 is_market_open(now)）。
  - data/models.py：SQLAlchemy ORM 模型（Trade, Quote, Ohlcv1m, MarketCalendar, AIDecision）。后续扩展指标时，只需加模型。
  - data/repositories.py：封装数据库写入逻辑，如 save_trades(session, records)，负责批量写入、去重。
  - data/collector.py：核心采集流程：循环 NASDAQ 100 → 调用 Massive client → 调用 repository 写库 → 触发聚合任务。
  - data/pipeline.py：作为 Data 模块入口。绑定 APScheduler 定时任务、捕获异常、调用 collector.run_cycle()。

---

## 开发顺序建议
  - config.py：先把基础配置+常量理清，后续文件都依赖它。
  - database.py + data/models.py：建立 ORM 模型并测试数据库连接/迁移。
  - data/clients/massive.py：能拿到真实数据后，再写入库。
  - data/repositories.py：实现批量写入和事务管理。
  - data/schedulers/market_clock.py + data/collector.py：正式跑采集循环。
  - data/pipeline.py：最后布置 APScheduler / CLI 入口，接入 CI/CD。

