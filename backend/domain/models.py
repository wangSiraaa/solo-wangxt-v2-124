"""领域数据模型：试样、设备、信号通道、分析方案与结果。

设计原则：
- 夹具位移(crosshead)与引伸计读数(extensometer)是两个独立通道，绝不混入同一列。
- 每个尺寸/参数带单位，入库时换算为内部单位(N, mm)。
- 结果不仅是数值，还携带来源(provenance)、公式、输入引用、诊断量与告警。
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, model_validator


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SpecimenShape(str, Enum):
    ROUND = "round"          # 圆形截面试样，d0
    RECTANGULAR = "rect"     # 矩形截面试样，b0 × a0


class SpecimenGeometry(BaseModel):
    """试样原始尺寸（GB/T 228.1 记号）。"""
    specimen_id: str
    shape: SpecimenShape
    # 圆截面试样直径
    diameter_mm: float | None = Field(None, description="d0，原始直径 [mm]")
    # 矩形截面试样宽度/厚度
    width_mm: float | None = Field(None, description="b0，原始宽度 [mm]")
    thickness_mm: float | None = Field(None, description="a0，原始厚度 [mm]")
    gauge_length_mm: float = Field(..., description="L0，原始标距 [mm]（引伸计标距另行记录）")
    parallel_length_mm: float | None = Field(None, description="Lc，平行长度 [mm]")
    # 断后实测尺寸（试验后录入；缺失则断后指标不可计算）
    final_gauge_length_mm: float | None = Field(
        None, description="Lu，断后标距（对接试样后测量）[mm]")
    final_diameter_mm: float | None = Field(None, description="du，断后缩颈处最小直径 [mm]")
    final_width_mm: float | None = Field(None, description="bu，断后缩颈处宽度 [mm]")
    final_thickness_mm: float | None = Field(None, description="au，断后缩颈处厚度 [mm]")

    def area0_mm2(self) -> float | None:
        """原始横截面积 S0 [mm^2]；尺寸不足返回 None（不做猜测）。"""
        if self.shape is SpecimenShape.ROUND and self.diameter_mm:
            return 3.141592653589793 * self.diameter_mm ** 2 / 4.0
        if (self.shape is SpecimenShape.RECTANGULAR
                and self.width_mm and self.thickness_mm):
            return self.width_mm * self.thickness_mm
        return None

    def areau_mm2(self) -> float | None:
        """断后缩颈处最小横截面积 Su [mm^2]；缺失返回 None。"""
        if self.shape is SpecimenShape.ROUND and self.final_diameter_mm:
            return 3.141592653589793 * self.final_diameter_mm ** 2 / 4.0
        if (self.shape is SpecimenShape.RECTANGULAR
                and self.final_width_mm and self.final_thickness_mm):
            return self.final_width_mm * self.final_thickness_mm
        return None


class DeviceParams(BaseModel):
    """设备与传感器参数。"""
    machine_id: str
    load_cell_id: str
    load_cell_capacity_n: float | None = Field(None, description="传感器量程 [N]")
    load_cell_class: str | None = Field(None, description="准确度等级，如 0.5")
    extensometer_id: str | None = None
    extensometer_gauge_length_mm: float | None = Field(
        None, description="Le，引伸计标距 [mm]；与试样标距 L0 区分")
    extensometer_class: str | None = Field(None, description="如 1 级 / 0.5 级")
    sampling_rate_hz: float | None = None
    crosshead_compliance_mm_per_n: float | None = Field(
        None, description="机架/夹具柔度 C [mm/N]，仅在无引伸计时做修正用")


class StrainSource(str, Enum):
    EXTENSOMETER = "extensometer"   # 引伸计：ε = ΔLe / Le
    CROSSHEAD = "crosshead"         # 夹具位移：ε = (Δ - C·F) / L0，仅在无引伸计时


class SignalChannels(BaseModel):
    """原始信号。多列独立存储，保留原始值与原始单位记录，不做就地覆盖。

    各序列长度必须一致；引伸计可在某点摘除（摘除后为 null），
    用 extensometer_removed_at_index 标记最后一个有效点。
    """
    time_s: list[float] = Field(..., description="采样时间 [s]")
    force_n: list[float] = Field(..., description="载荷 F [N]")
    crosshead_displacement_mm: list[float] = Field(..., description="夹具（横梁）位移 [mm]")
    extensometer_displacement_mm: list[float | None] = Field(
        ..., description="引伸计位移 ΔLe [mm]；摘除后为 null")
    extensometer_removed_at_index: int | None = Field(
        None, description="引伸计摘除点索引（该点之后读数无效）")

    @model_validator(mode="after")
    def _check_channels(self) -> "SignalChannels":
        n = len(self.time_s)
        for name in ("force_n", "crosshead_displacement_mm",
                     "extensometer_displacement_mm"):
            if len(getattr(self, name)) != n:
                raise ValueError(
                    f"通道 {name} 长度({len(getattr(self, name))})与 time_s({n})不一致")
        idx = self.extensometer_removed_at_index
        if idx is not None and not (0 <= idx < n):
            raise ValueError("extensometer_removed_at_index 超出序列范围")
        return self

    def __len__(self) -> int:
        return len(self.time_s)


class ExcludedPoint(BaseModel):
    """人工排除的数据点：必须给出原因。"""
    index: int = Field(..., ge=0)
    reason: str = Field(..., min_length=1, description="排除原因，如：引伸计滑移尖点")
    author: str
    created_at: datetime = Field(default_factory=_utcnow)


class AnalysisPlan(BaseModel):
    """计算方案：弹性区选择、偏移量、应变来源等全部可追溯。"""
    name: str = "default"
    strain_source: StrainSource = StrainSource.EXTENSOMETER
    # 弹性拟合区间：用应变边界(无量纲)或点索引表达
    elastic_strain_min: float | None = None
    elastic_strain_max: float | None = None
    elastic_index_min: int | None = None
    elastic_index_max: int | None = None
    offset: float = Field(0.002, description="偏移法偏移量（无量纲）；0.2% = 0.002")
    offset_unit: Literal["strain_ratio"] = "strain_ratio"
    min_elastic_points: int = 10
    r2_warning_threshold: float = 0.99
    author: str = "lab"
    created_at: datetime = Field(default_factory=_utcnow)
    notes: str | None = None

    @model_validator(mode="after")
    def _check_elastic_range(self) -> "AnalysisPlan":
        by_index = self.elastic_index_min is not None or self.elastic_index_max is not None
        by_strain = self.elastic_strain_min is not None or self.elastic_strain_max is not None
        if by_index and by_strain:
            raise ValueError("弹性区只能用索引或应变边界中的一种方式指定")
        if by_index:
            if self.elastic_index_min is None or self.elastic_index_max is None:
                raise ValueError("elastic_index_min/max 必须同时提供")
            if not (0 <= self.elastic_index_min < self.elastic_index_max):
                raise ValueError("弹性区索引范围非法")
        if by_strain:
            if self.elastic_strain_min is None or self.elastic_strain_max is None:
                raise ValueError("elastic_strain_min/max 必须同时提供")
            if not (0 <= self.elastic_strain_min < self.elastic_strain_max):
                raise ValueError("弹性区应变范围非法")
        if self.offset < 0:
            raise ValueError("offset 不能为负")
        return self


class SourcedValue(BaseModel):
    """带完整来源的结果值：报告不允许出现无来源的裸数字。"""
    key: str
    label: str
    value: float | int | None = None
    unit: str
    available: bool = True
    reason_if_unavailable: str | None = None
    formula: str | None = None
    # 输入溯源：通道名、尺寸字段、点索引区间、方案参数
    inputs: dict = Field(default_factory=dict)
    method: str | None = None
    diagnostics: dict = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
