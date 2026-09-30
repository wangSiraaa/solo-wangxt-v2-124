"""PostgreSQL 连接配置。

DATABASE_URL 缺省指向本地 postgres；未配置/连不上时可用 SQLite 做单机演示，
但生产数据应使用 PostgreSQL（JSONB、事务、并发）。
"""
from __future__ import annotations

import os

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg://lab:lab@localhost:5432/materials_lab",
)

# 无 DATABASE_URL 且显式要求演示时：sqlite
DEMO_SQLITE_URL = "sqlite+pysqlite:///:memory:"


def use_demo_sqlite() -> bool:
    return os.environ.get("LAB_DEMO_SQLITE") == "1"
