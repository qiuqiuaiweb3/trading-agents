### PostgreSQL 数据库设计方案

针对高频日内交易智能体，采用 **PostgreSQL + TimescaleDB** 方案存储时间序列数据。本设计已根据 Massive API 响应结构进行对齐，并集成了自动化数据保留策略与 NYSE 交易日历表。

---

### 1. 核心表结构设计 (Schema)

#### 1.1 逐笔成交表 (`trades`)
**数据源**：Massive API `/v3/trades/{stockTicker}`
**用途**：存储所有逐笔成交记录（Tick），用于构建 K 线及回测。

```sql
CREATE TABLE trades (
    time TIMESTAMPTZ NOT NULL,          -- participant_timestamp (纳秒级, 统一 UTC)
    ticker TEXT NOT NULL,               -- 股票代码 (例如 "AAPL")
    price NUMERIC NOT NULL,             -- 成交价格 (price)
    size NUMERIC NOT NULL,              -- 成交量 (size, API 返回为 number, 支持小数)
    exchange INTEGER,                   -- 交易所 ID (exchange)
    conditions INTEGER[],               -- 交易条件代码数组 (conditions)
    correction INTEGER,                 -- 修正指示符 (correction)
    id TEXT,                            -- 原始 Trade ID (id)
    sequence_number BIGINT,             -- 消息序列号 (sequence_number)
    tape INTEGER,                       -- 磁带 ID (1=A, 2=B, 3=C)
    trf_id INTEGER,                     -- Trade Reporting Facility ID
    trf_timestamp BIGINT                -- TRF 纳秒时间戳
);

-- 转换为 TimescaleDB 超表，按 1 天切分 chunk
SELECT create_hypertable('trades', 'time', chunk_time_interval => INTERVAL '1 day');

-- 索引优化：按标的和时间倒序查询最快
CREATE INDEX idx_trades_ticker_time ON trades (ticker, time DESC);
```

#### 1.2 NBBO 报价表 (`quotes`)
**数据源**：Massive API `/v3/quotes/{stockTicker}`
**用途**：存储最优买卖报价（NBBO），用于分析流动性与点差。

```sql
CREATE TABLE quotes (
    time TIMESTAMPTZ NOT NULL,          -- participant_timestamp (纳秒级, 统一 UTC)
    ticker TEXT NOT NULL,               -- 股票代码
    bid_price NUMERIC,                  -- 买一价 (bid_price)
    bid_size NUMERIC,                   -- 买一量 (bid_size)
    bid_exchange INTEGER,               -- 买方交易所 ID (bid_exchange)
    ask_price NUMERIC,                  -- 卖一价 (ask_price)
    ask_size NUMERIC,                   -- 卖一量 (ask_size)
    ask_exchange INTEGER,               -- 卖方交易所 ID (ask_exchange)
    conditions INTEGER[],               -- 报价条件代码 (conditions)
    indicators INTEGER[],               -- 指标代码 (indicators)
    sequence_number BIGINT,             -- 消息序列号 (sequence_number)
    tape INTEGER                        -- 磁带 ID
);

-- 转换为 TimescaleDB 超表
SELECT create_hypertable('quotes', 'time', chunk_time_interval => INTERVAL '1 day');

-- 索引优化
CREATE INDEX idx_quotes_ticker_time ON quotes (ticker, time DESC);
```

---

### 2. 自动数据保留策略 (Retention Policy)

**需求**：采集后的数据保留两个交易日，到期自动删除。
**实现**：利用 TimescaleDB 的 `add_retention_policy` 功能。

> 注意：TimescaleDB 的删除策略是基于“数据时间戳”而非“写入时间”。设置为 `2 days` 意味着“时间戳早于当前时间 2 天的数据”将被删除。对于日内交易，保留 2 天足够覆盖当天 + 前一交易日用于对比。

```sql
-- 自动删除 trades 表中 48 小时前的数据
SELECT add_retention_policy('trades', INTERVAL '2 days');

-- 自动删除 quotes 表中 48 小时前的数据
SELECT add_retention_policy('quotes', INTERVAL '2 days');
```

---

### 3. K 线聚合表 (`ohlcv_1m`)

**用途**：策略模块核心输入。直接查询此表而非原始 Tick，极大提高速度。
**实现**：使用 TimescaleDB 的 **Continuous Aggregates** 实时自动计算。

```sql
CREATE MATERIALIZED VIEW ohlcv_1m
WITH (timescaledb.continuous) AS
SELECT time_bucket('1 minute', time) AS bucket,
       ticker,
       first(price, time) as open,
       max(price) as high,
       min(price) as low,
       last(price, time) as close,
       sum(size) as volume,
       COUNT(*) as trade_count,
       SUM(price * size) / SUM(size) as vwap
FROM trades
GROUP BY bucket, ticker;

-- 自动刷新策略：每 1 分钟刷新一次，计算最近 2 分钟到 1 小时前的数据（预留 buffer）
SELECT add_continuous_aggregate_policy('ohlcv_1m',
    start_offset => INTERVAL '1 hour',
    end_offset => INTERVAL '1 minute',
    schedule_interval => INTERVAL '1 minute');
    
-- K线数据保留稍长一点（例如 7 天），便于策略回溯
SELECT add_retention_policy('ohlcv_1m', INTERVAL '7 days');
```

---

### 4. 交易日历与休市管理 (`market_calendar`)

**需求**：与 NYSE 官方时间保持一致，支持节假日与提早休市。
**数据源参考**：[NYSE Holidays & Trading Hours](https://www.nyse.com/markets/hours-calendars)

```sql
CREATE TABLE market_calendar (
    date DATE PRIMARY KEY,              -- 交易日期
    status TEXT NOT NULL,               -- 'open', 'closed', 'early_close'
    open_time TIME,                     -- 开盘时间 (通常 09:30:00 ET)
    close_time TIME,                    -- 收盘时间 (通常 16:00:00 ET，提早休市为 13:00:00 ET)
    description TEXT                    -- 说明 (如 "Independence Day")
);

-- 示例数据插入（基于 2025 NYSE 日历）
INSERT INTO market_calendar (date, status, open_time, close_time, description) VALUES
('2025-01-01', 'closed', NULL, NULL, 'New Year’s Day'),
('2025-01-20', 'closed', NULL, NULL, 'Martin Luther King, Jr. Day'),
('2025-02-17', 'closed', NULL, NULL, 'Washington''s Birthday'),
('2025-04-18', 'closed', NULL, NULL, 'Good Friday'),
('2025-05-26', 'closed', NULL, NULL, 'Memorial Day'),
('2025-06-19', 'closed', NULL, NULL, 'Juneteenth National Independence Day'),
('2025-07-03', 'early_close', '09:30:00', '13:00:00', 'Independence Day (Early Close)'),
('2025-07-04', 'closed', NULL, NULL, 'Independence Day'),
('2025-09-01', 'closed', NULL, NULL, 'Labor Day'),
('2025-11-27', 'closed', NULL, NULL, 'Thanksgiving Day'),
('2025-11-28', 'early_close', '09:30:00', '13:00:00', 'Day After Thanksgiving (Early Close)'),
('2025-12-24', 'early_close', '09:30:00', '13:00:00', 'Christmas Eve (Early Close)'),
('2025-12-25', 'closed', NULL, NULL, 'Christmas Day');
```

*注：Python 代码中需处理时区转换，将上述 ET 时间转为 UTC 后再进行比对。*

---
### ai_decisions
```sql
CREATE TABLE ai_decisions (
    id SERIAL PRIMARY KEY,
    start_time TIMESTAMPTZ NOT NULL,    -- 策略切换/开始的时间
    end_time TIMESTAMPTZ,               -- 策略结束/被切换的时间 (NULL 表示当前正在运行)
    
    ticker TEXT NOT NULL,               -- 针对哪个标的
    
    strategy_name TEXT NOT NULL,        -- 选中的策略名称 (如 "MACD_Trend_V1")
    reason TEXT,                        -- AI 选择该策略的理由 (摘要)
    
    initial_price NUMERIC NOT NULL,     -- 策略开始时的标的价格
    final_price NUMERIC,                -- 策略结束时的标的价格
    
    pnl_amount NUMERIC,                 -- 该策略运行期间的盈利金额 (Realized PnL)
    pnl_percentage NUMERIC,             -- 收益率
    
    status TEXT DEFAULT 'active',       -- 'active' (运行中), 'completed' (已结束), 'force_stopped'
    
    ai_model_version TEXT               -- 记录是哪个版本的模型做的决策
);

-- 索引：方便查询某个标的的决策历史，或查找当前活跃的策略
CREATE INDEX idx_ai_decisions_ticker_time ON ai_decisions (ticker, start_time DESC);
CREATE INDEX idx_ai_decisions_active ON ai_decisions (ticker) WHERE status = 'active';
```

start_time / end_time：构成了策略的生命周期。当 AI 发出“切换”指令时，系统会：
找到该标的当前 status='active' 的记录。
更新其 end_time、final_price、pnl_amount。
将 status 设为 completed。
插入一条新的记录，start_time 为当前时间，status='active'。
pnl_amount：这是核心字段。下次 AI 做决策时，可以 SELECT AVG(pnl_amount) FROM ai_decisions WHERE strategy_name = '...' 来评估该策略最近的表现。


---

### 5. 技术指标 (可选/未来扩展)

如果你后续决定存储 Massive 计算好的指标，可以使用如下 JSONB 结构，完美适配 Massive API 的响应格式。

```sql
CREATE TABLE indicators (
    time TIMESTAMPTZ NOT NULL,
    ticker TEXT NOT NULL,
    type TEXT NOT NULL,                 -- 'SMA', 'EMA', 'MACD', 'RSI'
    params JSONB,                       -- 存储参数 {period: 14} 或 {short: 12, long: 26, signal: 9}
    values JSONB NOT NULL               -- 存储结果 {value: 105.2} 或 {macd: 1.5, signal: 1.2, hist: 0.3}
);

SELECT create_hypertable('indicators', 'time', chunk_time_interval => INTERVAL '1 day');
SELECT add_retention_policy('indicators', INTERVAL '2 days');
```
