"""分析编排：原始信号 + 试样/设备 + 方案 + 排除点 → 完整分析报告。

报告里每个指标都是 SourcedValue（公式、输入、方法、诊断、告警），
不允许只输出几个无来源的最终数值。
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

import numpy as np

from .elastic import fit_modulus, interval_influence
from .models import (
    AnalysisPlan,
    DeviceParams,
    ExcludedPoint,
    SignalChannels,
    SourcedValue,
    SpecimenGeometry,
)
from .signals import build_curve
from .strengths import (
    elongation_after_fracture,
    fracture_stress_eng,
    reduction_of_area,
    tensile_strength,
)
from .yield_ import OffsetYieldResult, offset_yield, yield_plateau


def _exclude_mask(n: int, exclusions: list[ExcludedPoint]) -> tuple[np.ndarray, list[dict]]:
    mask = np.ones(n, dtype=bool)
    records: list[dict] = []
    for p in exclusions:
        if not (0 <= p.index < n):
            raise ValueError(f"排除点索引 {p.index} 超出范围 [0, {n - 1}]")
        mask[p.index] = False
        records.append({
            "index": p.index,
            "reason": p.reason,
            "author": p.author,
            "created_at": p.created_at.isoformat(),
        })
    return mask, records


def _modulus_sourced(fit, plan: AnalysisPlan, influence: dict,
                     source: str) -> SourcedValue:
    if not fit.available:
        return SourcedValue(
            key="E", label="弹性模量 E", value=None, unit="MPa",
            available=False, reason_if_unavailable=fit.reason_if_unavailable,
            formula="σ = E·ε + b（最小二乘）",
            inputs={"strain_source": source,
                    "plan": plan.name,
                    "elastic_index_range": [fit.start_index, fit.end_index]},
            method="弹性段应力-应变线性拟合",
            diagnostics={"n_points": fit.n_points},
            warnings=fit.warnings)
    return SourcedValue(
        key="E", label="弹性模量 E", value=fit.modulus_mpa, unit="MPa",
        formula="σ = E·ε + b（最小二乘）",
        inputs={
            "strain_source": source,
            "plan": plan.name,
            "elastic_index_range": [fit.start_index, fit.end_index],
            "elastic_strain_range": [fit.strain_min, fit.strain_max],
        },
        method="弹性段应力-应变线性拟合（SciPy linregress）",
        diagnostics={
            "r2": fit.r2,
            "rmse_mpa": fit.rmse_mpa,
            "n_points": fit.n_points,
            "intercept_mpa": fit.intercept_mpa,
            "used_indices": fit.used_indices.tolist(),
            "residual_mpa": [float(x) for x in fit.residual_mpa],
            "residual_max_abs_mpa": float(np.max(np.abs(fit.residual_mpa))),
            "interval_influence": influence,
        },
        warnings=fit.warnings + (
            [f"区间端点内缩 {influence['trim_points_each_side']} 点时 E 最大漂移 "
             f"{influence['max_abs_drift_percent']:.2f}%"]
            if influence.get("available") and influence.get("max_abs_drift_percent", 0) > 2.0
            else []),
    )


def _proof_sourced(res: OffsetYieldResult, plan: AnalysisPlan,
                   source: str, e_value: float | None) -> SourcedValue:
    if not res.available:
        return SourcedValue(
            key="Rp0.2" if plan.offset == 0.002 else f"Rp{plan.offset*100:g}",
            label=f"规定塑性延伸强度 Rp{plan.offset*100:g}",
            value=None, unit="MPa", available=False,
            reason_if_unavailable=res.reason_if_unavailable,
            formula="σ = E·(ε - e_p)，与实测曲线第一个交点",
            inputs={"strain_source": source, "offset": plan.offset,
                    "offset_unit": "无量纲工程应变",
                    "offset_percent": plan.offset * 100,
                    "plan": plan.name},
            method="偏移直线法（SciPy 线性插值求交点）",
            warnings=res.warnings or [])
    return SourcedValue(
        key="Rp0.2" if plan.offset == 0.002 else f"Rp{plan.offset*100:g}",
        label=f"规定塑性延伸强度 Rp{plan.offset*100:g}",
        value=res.proof_stress_mpa, unit="MPa",
        formula="σ = E·(ε - e_p)，与实测曲线第一个交点",
        inputs={
            "strain_source": source,
            "offset": plan.offset,
            "offset_unit": "无量纲工程应变（0.002 = 0.2%，不是 0.002%）",
            "offset_percent": plan.offset * 100,
            "modulus_mpa": e_value,
            "plan": plan.name,
        },
        method="偏移直线法；交点在相邻采样点间线性插值",
        diagnostics={
            "proof_strain": res.proof_strain,
            "proof_strain_percent": res.proof_strain * 100,
            "cross_indices": [res.index_a, res.index_b],
            "interpolation_fraction": res.interpolation_fraction,
        },
        warnings=res.warnings or [],
    )


def run_analysis(channels: SignalChannels,
                 specimen: SpecimenGeometry,
                 device: DeviceParams,
                 plan: AnalysisPlan,
                 exclusions: list[ExcludedPoint] | None = None) -> dict[str, Any]:
    exclusions = exclusions or []
    n = len(channels)
    base_mask, excl_records = _exclude_mask(n, exclusions)

    curve = build_curve(channels, specimen, device, plan.strain_source)
    # 弹性拟合不允许使用颈缩后点
    base_mask_pre_neck = base_mask.copy()
    base_mask_pre_neck[curve.max_force_index + 1:] = False

    fit = fit_modulus(curve.stress_eng_mpa, curve.strain_eng,
                      curve.valid_strain, base_mask_pre_neck, plan)
    influence = interval_influence(
        curve.stress_eng_mpa, curve.strain_eng, curve.valid_strain,
        base_mask_pre_neck, fit)

    proof = offset_yield(
        curve.stress_eng_mpa, curve.strain_eng, curve.valid_strain,
        base_mask, fit.modulus_mpa if fit.available else float("nan"),
        fit.end_index if fit.available else curve.max_force_index,
        offset=plan.offset)

    plateau = yield_plateau(
        curve.stress_eng_mpa, curve.valid_strain, base_mask,
        curve.max_force_index)

    values = [
        _modulus_sourced(fit, plan, influence, plan.strain_source.value),
        _proof_sourced(proof, plan, plan.strain_source.value,
                       fit.modulus_mpa if fit.available else None),
        tensile_strength(curve),
        fracture_stress_eng(curve),
        elongation_after_fracture(specimen),
        reduction_of_area(specimen),
    ]

    warnings = list(curve.warnings)
    if not plateau.available:
        warnings.append(f"上/下屈服：{plateau.reason_if_unavailable}")

    # 曲线数据（原始信号 + 派生列；颈缩后真应力真应变为 null，明确不可用）
    series = _series_payload(channels, curve)

    return {
        "report_id": None,  # 由持久层补
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "specimen_id": specimen.specimen_id,
        "summary": {
            "E_mpa": values[0].value if values[0].available else None,
            f"Rp{plan.offset*100:g}_mpa": values[1].value if values[1].available else None,
            "Rm_mpa": values[2].value if values[2].available else None,
            "A_percent": values[4].value if values[4].available else None,
            "Z_percent": values[5].value if values[5].available else None,
        },
        "results": [v.model_dump() for v in values],
        "yield_plateau": asdict(plateau),
        "strain_source": plan.strain_source.value,
        "curve_limits": {
            "max_force_index": curve.max_force_index,
            "fracture_index": curve.fracture_index,
            "true_curve_valid_until_index": curve.true_valid_until_index,
            "extensometer_removed_at_index": channels.extensometer_removed_at_index,
        },
        "elastic_fit": {
            "available": fit.available,
            "reason_if_unavailable": fit.reason_if_unavailable,
            "modulus_mpa": fit.modulus_mpa if fit.available else None,
            "intercept_mpa": fit.intercept_mpa if fit.available else None,
            "r2": fit.r2 if fit.available else None,
            "rmse_mpa": fit.rmse_mpa if fit.available else None,
            "n_points": fit.n_points,
            "strain_range": [fit.strain_min, fit.strain_max] if fit.available else None,
            "index_range": [fit.start_index, fit.end_index],
            "interval_influence": influence,
            "residual_mpa": [float(x) for x in fit.residual_mpa],
            "used_indices": fit.used_indices.tolist(),
            "warnings": fit.warnings,
        },
        "offset_yield": asdict(proof),
        "series": series,
        "excluded_points": excl_records,
        "plan": plan.model_dump(mode="json"),
        "warnings": warnings,
        "unavailable_reasons": curve.unavailable_reasons,
    }


def _series_payload(channels: SignalChannels, curve) -> dict[str, Any]:
    def col(a):
        if a is None:
            return None
        return [None if (isinstance(x, float) and not np.isfinite(x)) else float(x)
                for x in np.asarray(a, dtype=float)]

    return {
        "index": list(range(len(channels))),
        "time_s": list(channels.time_s),
        "force_n": list(channels.force_n),
        "crosshead_displacement_mm": list(channels.crosshead_displacement_mm),
        "extensometer_displacement_mm": [
            None if v is None else float(v)
            for v in channels.extensometer_displacement_mm],
        "engineering_stress_mpa": col(curve.stress_eng_mpa),
        "engineering_strain": col(curve.strain_eng),
        "true_stress_mpa": col(curve.stress_true_mpa),
        "true_strain": col(curve.strain_true),
        "valid_strain": [bool(x) for x in curve.valid_strain],
    }
