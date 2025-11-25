说明：
settings.database_url 会读取 .env 中的 DATABASE_URL（已经设为 postgresql://trader:secret@db:5432/trading），直接传给 create_engine 即可。
session_scope() 便于在 data/repositories.py 或其他模块里用 with session_scope(): ... 写入数据库。
init_db() 不是必须，但有助于在 data/pipeline.py 启动时快速检测数据库是否可连（如果需要建表，可在 models 中另写 Base.metadata.create_all(engine)）。

session_scope()（第 34-49 行）是一个上下文管理器，用来安全地管理数据库 Session 生命周期。它会在 with session_scope() as session: 块中提供一个短期 Session，块内完成后自动执行 session.commit()；如果出现异常则 rollback() 并重新抛出，最后确保 session.close() 被调用，避免连接泄漏。这样其他模块在读写数据库时不用每次手动写 try/except/commit/close，代码更整洁。
init_db()（第 52-58 行）用于在程序启动时做一次“数据库健康检查”。它会创建一个连接，执行 SELECT 1，如果能成功说明数据库地址、凭证、TimescaleDB 服务等都正常；若连接失败则立即抛错，方便你在 Data 模块启动前尽早发现问题。这个函数可以在 pipeline.py 或 App 启动脚本里调用。