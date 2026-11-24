import os
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from redis import Redis

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://port_ops:port_ops_local@db:5432/port_ops")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
redis_client = Redis.from_url(REDIS_URL, decode_responses=True)

class Base(DeclarativeBase):
    pass
