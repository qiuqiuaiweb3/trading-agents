> 说明
> - Trade / Quote 表结构与 Massive API 字段对齐，size 使用 Numeric 以容纳未来期权/ETF 等非整数成交量。
> - massive_trade_id 用于去重。你可以根据真实响应字段命名（Massive 文档：i 字段为 Trade ID）。
> - MarketCalendar 用来存 NYSE 官方节假日与早收时间，Data 模块的 market_clock 会引用。
> - AIDecision 记录策略切换生命周期（start/end、pnl 等）。status 字段便于查找当前正在运行的策略。
> - 不需要为 ohlcv_1m 定义 ORM 类（它是连续聚合视图，用 SQL 建即可）。如后续想以 ORM 查询，可另写映射类。
粘贴完成后，记得在适当的位置调用 Base.metadata.create_all(engine)（例如在单独的初始化脚本或 Alembic 迁移里）以确保这些表存在。之后就可以继续实现 data/clients/massive.py 或 repositories.py 了。

主要发现与变更：
Trade 模型:
缺失字段: 原模型缺少 participant_timestamp（参与者时间戳）。
修正: 已添加 participant_timestamp 字段 (类型: BigInteger)。
一致性: sequence_number, sip_timestamp (映射为 time), size, tape, trf_id, trf_timestamp, conditions, correction, exchange, price 等字段均已对齐。id 字段对应 API 的 Trade ID (字符串) 已映射为 massive_trade_id，模型内部保留自增 id 作为主键。
Quote 模型:
缺失字段: 原模型缺少 participant_timestamp。
修正: 已添加 participant_timestamp 字段 (类型: BigInteger)。
一致性: Bid/Ask 的 price/size/exchange 以及 conditions, indicators, sequence_number, tape 等字段均已对齐。
注意: 即使 Quote API 文档中提及 trf_timestamp，但在标准行情数据（如 Polygon/SIP）中 Quote 通常不包含 TRF 字段（仅 Trade 包含），因此未强制添加该字段以避免冗余，除非确信 Quote 数据源包含此字段。