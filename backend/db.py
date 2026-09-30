"""SQLAlchemy ORM：试样、设备、原始信号记录、分析方案、分析报告。

- raw_signal 以 JSONB 原样保存所有通道（含原始单位元数据），永不就地覆盖；
- analysis_reports 保存方案 JSON、排除点（含原因）、完整带来源的结果 JSON。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    String,
    Text,
    create_engine,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
    sessionmaker,
)

from .config import DATABASE_URL, DEMO_SQLITE_URL, use_demo_sqlite


def _json_type():
    # SQLite 演示环境没有 JSONB
    return JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    pass


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SpecimenRecord(Base):
    __tablename__ = "specimens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    specimen_code: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    shape: Mapped[str] = mapped_column(String(16))
    geometry: Mapped[dict] = mapped_column(_json_type())  # 全部尺寸字段 + 单位说明
    material: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    tests: Mapped[list["TestRecord"]] = relationship(back_populates="specimen")


class DeviceRecord(Base):
    __tablename__ = "devices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    params: Mapped[dict] = mapped_column(_json_type())  # 量程、等级、引伸计标距、柔度
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    tests: Mapped[list["TestRecord"]] = relationship(back_populates="device")


class TestRecord(Base):
    """一次拉伸试验：原始信号 + 所用试样/设备。"""
    __tablename__ = "tests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    test_code: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    specimen_id: Mapped[str] = mapped_column(ForeignKey("specimens.id"))
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id"))
    test_standard: Mapped[str | None] = mapped_column(String(64), nullable=True,
                                                      default="GB/T 228.1")
    # 原始信号：时间/载荷/夹具位移/引伸计位移分列；通道单位元数据随存
    raw_signal: Mapped[dict] = mapped_column(_json_type())
    channel_units: Mapped[dict] = mapped_column(_json_type())
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    specimen: Mapped[SpecimenRecord] = relationship(back_populates="tests")
    device: Mapped[DeviceRecord] = relationship(back_populates="tests")
    analyses: Mapped[list["AnalysisRecord"]] = relationship(back_populates="test")


class AnalysisRecord(Base):
    """一次分析运行：方案 + 排除点（带原因）+ 完整报告（带来源）。"""
    __tablename__ = "analyses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    test_id: Mapped[str] = mapped_column(ForeignKey("tests.id"), index=True)
    plan: Mapped[dict] = mapped_column(_json_type())
    excluded_points: Mapped[list] = mapped_column(_json_type(), default=list)
    report: Mapped[dict] = mapped_column(_json_type())
    summary: Mapped[dict] = mapped_column(_json_type())
    author: Mapped[str] = mapped_column(String(128), default="lab")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    test: Mapped[TestRecord] = relationship(back_populates="analyses")


_url = DEMO_SQLITE_URL if use_demo_sqlite() else DATABASE_URL
if use_demo_sqlite():
    from sqlalchemy.pool import StaticPool

    engine = create_engine(
        _url, future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool)
else:
    engine = create_engine(_url, future=True, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, future=True, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(engine)
