## Data 模块文件结构设计方案

基于 PRD 的需求（Massive API 采集、PostgreSQL 存储、分钟级调度、交易日历管理）和技术栈（Python 3.13, Poetry, APScheduler, SQLAlchemy, TimescaleDB, httpx），我为你设计了以下 Data 模块的文件结构。

这个结构遵循“功能分离”原则：**配置、采集逻辑、数据库模型、调度器** 相互独立，便于维护和扩展。

### 1. 推荐文件结构

请在项目根目录下创建 `src/bronco_trade_agents` 目录（如果你之前设置了 `package-mode=false`，可以直接放在 `src/` 或项目根目录下，但推荐用 `src/` 结构保持整洁）。

```text
src/bronco_trade_agents/
├── __init__.py
├── config.py                # 全局配置（加载 .env，定义常量）
├── database.py              # 数据库连接与 Session 管理
├── data/
│   ├── __init__.py
│   ├── collector.py         # 核心采集逻辑（调用 Massive API）
│   ├── scheduler.py         # 定时任务调度（APScheduler）
│   ├── models.py            # 数据库表结构定义（SQLAlchemy 模型）
│   ├── calendars.py         # 交易日历与休市时间管理
│   └── clients/
│       ├── __init__.py
│       └── massive.py       # Massive API 的底层 HTTP 封装
└── utils/
    ├── __init__.py
    └── logger.py            # 日志配置
```

---

### 2. 各文件功能设计说明

#### **`src/bronco_trade_agents/config.py`**
- **功能**：加载环境变量（`MASSIVE_API_KEY`, `DATABASE_URL`），定义全局常量。
- **关键内容**：
  - `SETTINGS` 类：使用 `pydantic-settings` 或 `os.getenv` 读取配置。
  - `NASDAQ_100_TICKERS`：列表，存储 100 个股票代码（或者从 DB/文件读取）。
  - `TIME_FRAMES`：定义采集频率（如 `1m`）和策略频率。

#### **`src/bronco_trade_agents/database.py`**
- **功能**：初始化数据库连接池，提供 Session。
- **关键内容**：
  - 创建 `AsyncEngine`（如果是异步采集）或同步 `Engine`。
  - 定义 `get_db()` 依赖函数。
  - 负责数据库表的初始化（`Base.metadata.create_all`）。

#### **`src/bronco_trade_agents/data/models.py`**
- **功能**：定义 PostgreSQL 表结构（ORM 模型）。
- **表设计（对应 PRD 需求）**：
  - `Trade` 表：存储逐笔成交（time, ticker, price, size, exchange）。
  - `Quote` 表：存储报价（time, ticker, bid_price, ask_price, bid_size, ask_size）。
  - `News` 表：存储舆情（time, ticker, headline, source, sentiment_score）。
  - `OHLCV_1m` 表：聚合后的 1 分钟 K 线（time, ticker, open, high, low, close, volume），**这是优化建议里提到的聚合表**。
  - **TimescaleDB 优化**：在表创建后，通过 SQL 语句将其转为 Hypertable（按时间分区）。

#### **`src/bronco_trade_agents/data/calendars.py`**
- **功能**：判断当前是否为“采集时间”（美股交易时段、排除节假日）。
- **关键内容**：
  - `is_market_open(datetime)` 函数：判断给定时间是否开市。
  - `get_next_market_open()`：获取下一个开盘时间。
  - 能够加载 `market_hours.json` 或硬编码 PRD 中的规则（09:30-16:00 ET 等）。
  - 处理时区转换（ET -> UTC）。

#### **`src/bronco_trade_agents/data/clients/massive.py`**
- **功能**：封装对 Massive API 的 HTTP 请求。
- **关键内容**：
  - 使用 `httpx.AsyncClient` 实现异步高并发请求。
  - `get_trades(ticker)`、`get_quotes(ticker)`、`get_news(ticker)` 方法。
  - 引入 `tenacity` 库进行自动重试（处理 API 限流或网络波动）。

#### **`src/bronco_trade_agents/data/collector.py`**
- **功能**：业务层的采集逻辑，串联 Client 和 Database。
- **逻辑流程**：
  1. 检查 `calendars.is_market_open()`，若休市则跳过。
  2. 遍历 NASDAQ 100 股票列表。
  3. 调用 `massive.py` 获取数据。
  4. 数据清洗（去重、格式化）。
  5. 批量写入数据库（`session.add_all` 或 `bulk_insert`）。
  6. 计算/更新 1 分钟聚合表（可选，或由 DB 触发器完成）。

#### **`src/bronco_trade_agents/data/scheduler.py`**
- **功能**：启动和管理定时任务。
- **关键内容**：
  - 初始化 `AsyncIOScheduler`。
  - 添加任务：`scheduler.add_job(collector.run_collection_cycle, 'cron', minute='*')`（每分钟触发）。
  - 提供 `start()` 和 `stop()` 方法供 `main.py` 调用。

---

### 3. 下一步实施建议

如果你准备好了，我们可以按以下顺序开始编写代码：

1.  **基础层**：先写 `config.py` 和 `database.py`，打通数据库连接。
2.  **模型层**：写 `models.py`，并在本地/Docker 数据库中把表建出来，测试 TimescaleDB 插件是否生效。
3.  **客户端**：写 `clients/massive.py`，用真实 API Key 测试能不能拉到一条 AAPL 的数据。
4.  **业务层**：写 `collector.py` 和 `scheduler.py`，实现每分钟自动跑一次。

你想先从哪一个文件开始？