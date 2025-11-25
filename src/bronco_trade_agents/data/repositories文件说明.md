关键点说明：
_ns_to_datetime: 这是最关键的转换函数，确保入库的时间是人类可读的 TIMESTAMP WITH TIME ZONE。
pg_insert (PostgreSQL Dialect): 我们特意引入了 sqlalchemy.dialects.postgresql.insert，因为它支持 .on_conflict_do_nothing()。这是处理金融数据流（可能会有重试导致的数据重复）的标准做法。
Quote 去重: 目前代码中 save_quotes 使用了标准插入。建议：如果您希望 Quote 也去重，请在 models.py 中为 Quote 表添加类似 Trade 表的 UniqueConstraint (例如基于 time, ticker, sequence_number)，然后将 save_quotes 也改为使用 pg_insert(...).on_conflict_do_nothing()。