import os
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from redis import Redis

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://port_ops:port_ops_local@db:5432/port_ops")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
redis_client = Redis.from_url(REDIS_URL, decode_responses=True)

class Base(DeclarativeBase):
    pass


def ensure_runtime_columns():
    """对升级前已存在的库补齐新增列（CREATE TABLE 之外的轻量迁移）。"""
    inspector = inspect(engine)
    if "dispatch_actions" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("dispatch_actions")}
    statements = []
    if "analysis_job_id" not in existing:
        statements.append("ALTER TABLE dispatch_actions ADD COLUMN analysis_job_id INTEGER REFERENCES analysis_jobs(id)")
    if "graded_level_snapshot" not in existing:
        statements.append("ALTER TABLE dispatch_actions ADD COLUMN graded_level_snapshot VARCHAR(20)")
    if statements:
        with engine.begin() as conn:
            for statement in statements:
                conn.execute(text(statement))
