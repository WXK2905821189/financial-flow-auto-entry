"""数据库连接与会话管理（SQLAlchemy 2.0 同步模式）。

中台面向财务单一使用方、并发量可控，采用同步引擎 + 每请求会话，简单可靠。
"""
from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import BigInteger, Integer, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings

# 主键自增类型：MySQL 用 BIGINT AUTO_INCREMENT；SQLite（单测/冒烟）用 INTEGER 以支持自增
BIGINT_PK = BigInteger().with_variant(Integer, "sqlite")


class Base(DeclarativeBase):
    """ORM 基类，所有模型继承自它。"""


engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_recycle=3600,
    echo=settings.environment == "dev",
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖：每请求一个会话，请求结束自动关闭。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()