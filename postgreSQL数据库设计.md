### 数据库设计建议

为了高效存储和查询高频交易所需的各类数据，建议使用 **PostgreSQL 结合 TimescaleDB 扩展**。这套方案专门针对时间序列数据优化，在写入性能和查询聚合上远超普通关系型表。

以下是基于你提供的 `Massive` API 数据结构和 PRD 需求设计的核心表结构方案：

---

### 1. 核心表结构

建议创建 4 张主要的时序表（Hypertables）：`trades`、`quotes`、`indicators`、`news`。

#### 1.1 成交数据表 (`trades`)
**用途**：存储逐笔成交数据（Tick），对应 Massive `/v3/trades/{stockTicker}`。
**特点**：数据量巨大，写入最频繁。

```sql
CREATE TABLE trades (
    time TIMESTAMPTZ NOT NULL,      -- participant_timestamp 或 sip_timestamp (建议统一用UTC)
    ticker TEXT NOT NULL,           -- 股票代码 (AAPL)
    price NUMERIC NOT NULL,         -- 成交价格
    size INTEGER NOT NULL,          -- 成交量 (volume)
    exchange INTEGER,               -- 交易所 ID
    conditions INTEGER[],           -- 交易条件代码 (数组)
    tape INTEGER,                   -- 磁带 ID (1=A, 2=B, 3=C)
    trade_id TEXT,                  -- 原始 Trade ID (用于去重/校验)
    sequence_number BIGINT          -- 消息序列号
);

-- 转换为 TimescaleDB 超表
SELECT create_hypertable('trades', 'time', chunk_time_interval => INTERVAL '1 day');

-- 索引优化
CREATE INDEX ON trades (ticker, time DESC);
CREATE INDEX ON trades (time DESC, ticker);
```

#### 1.2 报价数据表 (`quotes`)
**用途**：存储 NBBO 报价数据（Tick），对应 Massive `/v3/quotes/{stockTicker}`。
**特点**：数据量通常是 Trades 的数倍，建议只存 NBBO 变动或按需采样。

```sql
CREATE TABLE quotes (
    time TIMESTAMPTZ NOT NULL,      -- participant_timestamp 或 sip_timestamp
    ticker TEXT NOT NULL,
    bid_price NUMERIC NOT NULL,     -- 买一价
    ask_price NUMERIC NOT NULL,     -- 卖一价
    bid_size INTEGER NOT NULL,      -- 买一量
    ask_size INTEGER NOT NULL,      -- 卖一量
    exchange INTEGER,               -- 交易所 ID (通常是报价来源)
    conditions INTEGER[],           -- 报价条件代码
    tape INTEGER,
    sequence_number BIGINT
);

SELECT create_hypertable('quotes', 'time', chunk_time_interval => INTERVAL '1 day');

-- 索引优化
CREATE INDEX ON quotes (ticker, time DESC);
```

#### 1.3 技术指标表 (`indicators`)
**用途**：存储 Massive API 返回的 SMA、EMA、RSI、MACD 等指标数据。
**特点**：由于指标种类多，建议使用 **宽表** 或 **JSONB** 存储，避免为每个指标建表。

**方案 A：JSONB 存储（灵活性高，推荐）**
```sql
CREATE TABLE indicators (
    time TIMESTAMPTZ NOT NULL,      -- 指标对应的时间戳 (timestamp)
    ticker TEXT NOT NULL,
    type TEXT NOT NULL,             -- 指标类型: 'SMA', 'EMA', 'RSI', 'MACD'
    period INTEGER,                 -- 周期参数 (如 14, 50, 200)
    data JSONB NOT NULL             -- 具体数值 {value: 150.5} 或 {macd: 1.2, signal: 1.1, hist: 0.1}
);

SELECT create_hypertable('indicators', 'time', chunk_time_interval => INTERVAL '1 week');

CREATE INDEX ON indicators (ticker, type, time DESC);
```

**方案 B：宽表存储（查询性能略好，但扩展麻烦）**
```sql
CREATE TABLE indicators_1m (        -- 按频率分表，如 1分钟线指标
    time TIMESTAMPTZ NOT NULL,
    ticker TEXT NOT NULL,
    sma_20 NUMERIC,
    ema_20 NUMERIC,
    rsi_14 NUMERIC,
    macd_val NUMERIC,
    macd_signal NUMERIC,
    macd_hist NUMERIC
    -- ...更多列
);
```
考虑到你直接拉取 Massive 计算好的指标，**方案 A (JSONB)** 更适配 API 响应结构的多样性。

#### 1.4 K 线聚合表 (`ohlcv_1m`) —— **重要优化**
**用途**：用于策略模块快速查询，而不是每次都去扫 `trades` 表聚合。
**来源**：可以由程序定时从 `trades` 聚合写入，或者使用 TimescaleDB 的 **Continuous Aggregates** 功能自动维护。

```sql
-- 手动创建表（由 Python 程序写入）
CREATE TABLE ohlcv_1m (
    bucket TIMESTAMPTZ NOT NULL,
    ticker TEXT NOT NULL,
    open NUMERIC,
    high NUMERIC,
    low NUMERIC,
    close NUMERIC,
    volume BIGINT,
    vwap NUMERIC
);

SELECT create_hypertable('ohlcv_1m', 'bucket', chunk_time_interval => INTERVAL '1 week');
```

---

### 2. TimescaleDB 的优势利用

建议在 `Data 模块` 中利用 TimescaleDB 的特性来减少 Python 层的计算压力：

1.  **自动聚合 (Continuous Aggregates)**：
    让数据库自动把 `trades` 表的数据变成 1 分钟 K 线，而不需要 Python 每分钟跑循环去算。
    ```sql
    CREATE MATERIALIZED VIEW kline_1m
    WITH (timescaledb.continuous) AS
    SELECT time_bucket('1 minute', time) AS bucket,
           ticker,
           first(price, time) as open,
           max(price) as high,
           min(price) as low,
           last(price, time) as close,
           sum(size) as volume
    FROM trades
    GROUP BY bucket, ticker;
    ```

2.  **数据保留策略 (Retention Policy)**：
    如果 `trades` 数据量太大，可以设置自动删除过期数据（例如只保留最近 30 天的高频 tick，而保留 5 年的 K 线）。
    ```sql
    SELECT add_retention_policy('trades', INTERVAL '30 days');
    ```

### 3. 总结

- **表结构**：`trades` (Tick), `quotes` (NBBO), `indicators` (JSONB), `news` (普通表)。
- **核心字段**：时间戳 (`TIMESTAMPTZ`)、标的 (`TEXT`)、数值 (`NUMERIC`/`INTEGER`)。
- **技术选型**：PostgreSQL + TimescaleDB 扩展。
- **策略接口**：策略模块主要查询 `ohlcv_1m` (K线) 和 `indicators` 表，只有在做极高频微观结构分析时才查 `trades/v去查 `trades` / `quotes`。