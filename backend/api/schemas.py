"""HTTP API 的 Pydantic 模式（与领域模型解耦，允许原始单位入站）。"""
from __future__ import annotations

from pydantic import BaseModel, Field

from backend.domain.models import StrainSource


class GeometryIn(BaseModel):
    specimen_code: str
    shape: str
    material: str | None = None
    diameter_mm: float | None = None
    width_mm: float | None = None
    thickness_mm: float | None = None
    gauge_length_mm: float
    parallel_length_mm: float | None = None
    final_gauge_length_mm: float | None = None
    final_diameter_mm: float | None = None
    final_width_mm: float | None = None
    final_thickness_mm: float | None = None


class DeviceIn(BaseModel):
    machine_id: str
    load_cell_id: str
    load_cell_capacity_n: float | None = None
    load_cell_class: str | None = None
    extensometer_id: str | None = None
    extensometer_gauge_length_mm: float | None = None
    extensometer_class: str | None = None
    sampling_rate_hz: float | None = None
    crosshead_compliance_mm_per_n: float | None = None


class SignalIn(BaseModel):
    """原始信号导入：四列独立，载荷/位移可携带原始单位，服务端换算。"""
    test_code: str
    specimen_code: str
    device_machine_id: str
    test_standard: str | None = "GB/T 228.1"
    time_s: list[float]
    force: list[float] = Field(..., description="载荷原始读数")
    force_unit: str = "N"
    crosshead_displacement: list[float] = Field(..., description="夹具位移原始读数")
    crosshead_displacement_unit: str = "mm"
    extensometer_displacement: list[float | None] = Field(..., description="引伸计读数，独立列")
    extensometer_displacement_unit: str = "mm"
    extensometer_removed_at_index: int | None = None


class ExclusionIn(BaseModel):
    index: int
    reason: str = Field(..., min_length=1)
    author: str = "lab"


class AnalyzeIn(BaseModel):
    test_id: str
    strain_source: StrainSource = StrainSource.EXTENSOMETER
    elastic_index_min: int | None = None
    elastic_index_max: int | None = None
    elastic_strain_min: float | None = None
    elastic_strain_max: float | None = None
    offset: float = 0.002
    min_elastic_points: int = 10
    r2_warning_threshold: float = 0.99
    author: str = "lab"
    notes: str | None = None
    excluded_points: list[ExclusionIn] = []


class ElasticPreviewIn(AnalyzeIn):
    """只算弹性拟合 + 残差 + 区间影响（供拖选区间时实时调用）。"""
    pass
