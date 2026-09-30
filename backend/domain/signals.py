"""信号到工程/真实应力-应变的转换。

铁律：
1. 夹具位移与引伸计读数分通道处理，选择哪一个由分析方案显式声明。
2. 真应力/真应变换算 σ_t=σ(1+ε)、ε_t=ln(1+ε) 基于均匀变形（体积不变）假设，
   只在最大力点（颈缩开始）之前成立；颈缩之后一律标记 invalid，不做假装有效的换算。
3. 尺寸缺失（S0 算不出）时工程应力不可得，返回 None 与原因，而不是猜测面积。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .models import (
    DeviceParams,
    SignalChannels,
    SpecimenGeometry,
    StrainSource,
)


@dataclass
class StressStrainResult:
    stress_eng_mpa: np.ndarray | None
    strain_eng: np.ndarray | None
    strain_source: StrainSource | None
    valid_strain: np.ndarray          # bool：该点应变是否有效（引伸计未摘除）
    time_s: np.ndarray
    force_n: np.ndarray
    area0_mm2: float | None
    max_force_index: int | None       # 最大力点（颈缩起始判据点）
    fracture_index: int | None        # 断裂点估计
    true_valid_until_index: int | None  # 真应变换量有效区间右端（含）
    stress_true_mpa: np.ndarray | None  # 仅颈缩前有值，其余 nan
    strain_true: np.ndarray | None
    warnings: list[str]
    unavailable_reasons: list[str]


def engineering_stress(force_n: np.ndarray, area0_mm2: float | None
                       ) -> tuple[np.ndarray | None, str | None]:
    if area0_mm2 is None:
        return None, "原始横截面积 S0 缺失（试样尺寸不足），工程应力不可计算"
    if area0_mm2 <= 0:
        return None, "原始横截面积 S0 非正，数据异常"
    return np.asarray(force_n, dtype=float) / area0_mm2, None


def engineering_strain(channels: SignalChannels,
                       specimen: SpecimenGeometry,
                       device: DeviceParams,
                       source: StrainSource
                       ) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """返回 (应变序列, 有效性掩码, 告警)。

    引伸计：ε = ΔLe / Le；摘除点之后无效。
    夹具位移：ε = (δ - C·F) / L0；C 未知则不修正并告警。
    """
    warnings: list[str] = []
    n = len(channels)
    valid = np.ones(n, dtype=bool)

    if source is StrainSource.EXTENSOMETER:
        le = device.extensometer_gauge_length_mm
        if not le or le <= 0:
            raise ValueError("使用引伸计应变但未提供有效的引伸计标距 Le")
        raw = np.array(
            [np.nan if v is None else v for v in channels.extensometer_displacement_mm],
            dtype=float,
        )
        strain = raw / le
        if channels.extensometer_removed_at_index is not None:
            cut = channels.extensometer_removed_at_index
            valid[cut + 1:] = False
        valid &= ~np.isnan(strain)
        strain = np.where(valid, strain, np.nan)
        return strain, valid, warnings

    # 夹具位移（不能与引伸计混为一列：这里显式独立计算并标注来源）
    delta = np.asarray(channels.crosshead_displacement_mm, dtype=float)
    force = np.asarray(channels.force_n, dtype=float)
    c = device.crosshead_compliance_mm_per_n
    if c is None:
        c = 0.0
        warnings.append(
            "使用夹具位移估算应变且机架/夹具柔度 C 未知：未做柔度修正，"
            "弹性段应变被系统性高估，模量结果仅供参考")
    elif c < 0:
        raise ValueError("机架柔度不能为负")
    l0 = specimen.gauge_length_mm
    if not l0 or l0 <= 0:
        raise ValueError("试样标距 L0 无效")
    strain = (delta - c * force) / l0
    warnings.append("应变来源于夹具位移，包含夹具打滑/机架变形风险，应优先使用引伸计")
    return strain, valid, warnings


def detect_fracture(force_n: np.ndarray, max_force_index: int,
                    drop_ratio: float = 0.05) -> int:
    """断裂点：最大力之后，载荷首次跌破 drop_ratio·Fmax 的点的前一个有效点。

    若直至序列结束都未跌破（合成理想曲线/采集在断裂前停止），取最后一点。
    """
    f = np.asarray(force_n, dtype=float)
    fmax = f[max_force_index]
    threshold = drop_ratio * fmax
    after = np.where(f[max_force_index:] < threshold)[0]
    if len(after) == 0:
        return len(f) - 1
    first_below = max_force_index + int(after[0])
    return max(max_force_index, first_below - 1)


def build_curve(channels: SignalChannels,
                specimen: SpecimenGeometry,
                device: DeviceParams,
                source: StrainSource) -> StressStrainResult:
    warnings: list[str] = []
    reasons: list[str] = []
    force = np.asarray(channels.force_n, dtype=float)
    area0 = specimen.area0_mm2()

    stress, reason = engineering_stress(force, area0)
    if reason:
        reasons.append(reason)

    strain, valid, strain_warnings = engineering_strain(
        channels, specimen, device, source)
    warnings.extend(strain_warnings)

    # 最大力点：在有效加载段取 F 最大处（颈缩起始判据，GB/T：Rmt 对应最大力）
    m_idx = int(np.nanargmax(force))
    fracture_idx = detect_fracture(force, m_idx)

    stress_true = None
    strain_true = None
    if stress is not None:
        stress_true = np.full_like(stress, np.nan, dtype=float)
        strain_true = np.full_like(stress, np.nan, dtype=float)
        upto = m_idx  # 0..m_idx 视为均匀变形段
        seg_ok = valid[: upto + 1] & (strain[: upto + 1] > -1.0)
        stress_true[: upto + 1] = np.where(
            seg_ok, stress[: upto + 1] * (1.0 + strain[: upto + 1]), np.nan)
        strain_true[: upto + 1] = np.where(
            seg_ok, np.log1p(np.maximum(strain[: upto + 1], -1.0)), np.nan)
        if m_idx < len(force) - 1:
            warnings.append(
                f"最大力点(索引 {m_idx})之后为颈缩段：真应力/真应变简单换算已停止，"
                "该段数值标记为无效，需要 Bridgman 等修正才可继续")

    return StressStrainResult(
        stress_eng_mpa=stress,
        strain_eng=strain,
        strain_source=source,
        valid_strain=valid,
        time_s=np.asarray(channels.time_s, dtype=float),
        force_n=force,
        area0_mm2=area0,
        max_force_index=m_idx,
        fracture_index=fracture_idx,
        true_valid_until_index=m_idx,
        stress_true_mpa=stress_true,
        strain_true=strain_true,
        warnings=warnings,
        unavailable_reasons=reasons,
    )
