"""
数据库基础设施。

- 创建 SQLAlchemy Engine / Session；
- 提供 Base 供 models.py 继承；
- 提供上下文管理器 session_scope() 简化事务写法；
- 暴露 init_db() 方便启动时检测连接、建表。
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, scoped_session, sessionmaker

from .config import settings

# SQLAlchemy 推荐关闭 autocommit/autoflush，手动控制事务。
engine = create_engine(
    settings.database_url.unicode_string(),
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

SessionLocal = scoped_session(
    sessionmaker(bind=engine, autoflush=False, autocommit=False)
)

Base = declarative_base()


@contextmanager
def session_scope() -> Iterator[SessionLocal]:
    """
    提供一个自动提交/回滚的 Session 上下文：
    >>> with session_scope() as session:
    ...     session.add(obj)
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:  # noqa: BLE001
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    """
    初始化数据库：
    1. 测试连接
    2. 自动创建所有 ORM 模型对应的表（如果不存在）
    """
    from sqlalchemy import text
    
    # 1. 测试连接
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
        connection.commit()
    
    # 2. 创建所有表 (如果不存在)
    # 注意：需要先导入所有 models，确保它们被注册到 Base.metadata
    from .data.models import Trade, Quote, MarketCalendar, AIDecision  # noqa: F401
    Base.metadata.create_all(engine)


__all__ = ["Base", "engine", "SessionLocal", "session_scope", "init_db"]