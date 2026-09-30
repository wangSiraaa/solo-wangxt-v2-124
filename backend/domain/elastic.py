"""弹性模量 E 的线性拟合与区间影响分析。

σ = E·ε + b，最小二乘（scipy.stats.linregress）。
输出不止 E：逐点拟合残差、R²、RMSE、区间端点、点数，
并提供区间敏感性（端点内缩一档后 E 变化多少），供选择区间时实时判断。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import stats

from .models import AnalysisPlan


@dataclass
class ElasticFit:
    modulus_mpa: float
    intercept_mpa: float
    r2: float
    rmse_mpa: float
    n_points: int
    start_index: int
    end_index: int          # 半开
    strain_min: float
    strain_max: float
    residual_mpa: np.ndarray    # 区间内逐点残差 σ - (Eε+b)
    used_indices: np.ndarray
    warnings: list[str]
    available: bool = True
    reason_if_unavailable: str | None = None


def _select_indices(strain: np.ndarray,
                    valid: np.ndarray,
                    plan: AnalysisPlan,
                    base_mask: np.ndarray) -> np.ndarray:
    """合并：有效性掩码 + 人工排除掩码 + 方案区间。"""
    n = len(strain)
    mask = valid & base_mask
    idx = np.arange(n)
    if plan.elastic_index_min is not None:
        mask &= (idx >= plan.elastic_index_min) & (idx < plan.elastic_index_max)
    else:
        lo = plan.elastic_strain_min
        hi = plan.elastic_strain_max
        if lo is not None and hi is not None:
            with np.errstate(invalid="ignore"):
                mask &= (strain >= lo) & (strain <= hi)
    return np.where(mask)[0]


def fit_modulus(stress_mpa: np.ndarray | None,
                strain: np.ndarray,
                valid: np.ndarray,
                base_mask: np.ndarray,
                plan: AnalysisPlan) -> ElasticFit:
    if stress_mpa is None:
        return ElasticFit(
            modulus_mpa=float("nan"), intercept_mpa=float("nan"),
            r2=float("nan"), rmse_mpa=float("nan"), n_points=0,
            start_index=0, end_index=0, strain_min=float("nan"),
            strain_max=float("nan"),
            residual_mpa=np.array([]), used_indices=np.array([], dtype=int),
            available=False,
            reason_if_unavailable="原始横截面积缺失，应力不可计算，无法拟合弹性模量",
            warnings=["弹性模量不可得：应力输入缺失"],
        )

    used = _select_indices(strain, valid, plan, base_mask)
    warnings: list[str] = []
    if len(used) < plan.min_elastic_points:
        return ElasticFit(
            modulus_mpa=float("nan"), intercept_mpa=float("nan"),
            r2=float("nan"), rmse_mpa=float("nan"), n_points=len(used),
            start_index=int(used[0]) if len(used) else 0,
            end_index=int(used[-1]) + 1 if len(used) else 0,
            strain_min=float(np.nanmin(strain[used])) if len(used) else float("nan"),
            strain_max=float(np.nanmax(strain[used])) if len(used) else float("nan"),
            residual_mpa=np.array([]), used_indices=used,
            available=False,
            reason_if_unavailable=(
                f"弹性区内有效点 {len(used)} 个，少于最小要求 "
                f"{plan.min_elastic_points} 个；请扩大区间或减少排除点"),
            warnings=["弹性模量不可得：有效点不足"],
        )

    e = strain[used]
    s = stress_mpa[used]
    reg = stats.linregress(e, s)
    pred = reg.slope * e + reg.intercept
    residual = s - pred
    rmse = float(np.sqrt(np.mean(residual ** 2)))

    if reg.rvalue ** 2 < plan.r2_warning_threshold:
        warnings.append(
            f"弹性段线性度 R²={reg.rvalue ** 2:.5f} 低于阈值 "
            f"{plan.r2_warning_threshold}，所选区间可能包含非弹性段/滑移点")
    if abs(reg.intercept) > 0.05 * reg.slope * np.mean(e):
        # 截距偏大常提示零点未对齐或区间下端含压头贴合段
        warnings.append(
            f"拟合截距 {reg.intercept:.2f} MPa 偏大，建议检查载荷/位移零点或区间起点")

    return ElasticFit(
        modulus_mpa=float(reg.slope),
        intercept_mpa=float(reg.intercept),
        r2=float(reg.rvalue ** 2),
        rmse_mpa=rmse,
        n_points=len(used),
        start_index=int(used[0]),
        end_index=int(used[-1]) + 1,
        strain_min=float(e.min()),
        strain_max=float(e.max()),
        residual_mpa=residual,
        used_indices=used,
        warnings=warnings,
    )


def interval_influence(stress_mpa: np.ndarray | None,
                       strain: np.ndarray,
                       valid: np.ndarray,
                       base_mask: np.ndarray,
                       fit: ElasticFit,
                       trim: int = 5) -> dict:
    """区间敏感性：分别从左/右端内缩 trim 个点重新拟合，看 E 的漂移 [%]。

    供 UI 选择弹性区时即时反馈：区间微调不应使 E 大幅变化。
    """
    if not fit.available:
        return {"available": False, "reason": fit.reason_if_unavailable}
    idx = fit.used_indices
    if len(idx) <= 2 * trim + 2:
        trim = max(1, (len(idx) - 2) // 4)

    def _refit(sub: np.ndarray) -> dict:
        e, s = strain[sub], stress_mpa[sub]
        r = stats.linregress(e, s)
        return {
            "modulus_mpa": float(r.slope),
            "r2": float(r.rvalue ** 2),
            "start_index": int(sub[0]),
            "end_index": int(sub[-1]) + 1,
            "n_points": len(sub),
        }

    left_trimmed = _refit(idx[trim:])
    right_trimmed = _refit(idx[:-trim])
    both_trimmed = _refit(idx[trim:-trim])
    e0 = fit.modulus_mpa

    def drift(d: dict) -> float:
        return (d["modulus_mpa"] - e0) / e0 * 100.0

    return {
        "available": True,
        "full": {"modulus_mpa": e0, "r2": fit.r2,
                 "start_index": fit.start_index, "end_index": fit.end_index,
                 "n_points": fit.n_points},
        "trim_points_each_side": trim,
        "left_trimmed": left_trimmed,
        "right_trimmed": right_trimmed,
        "both_trimmed": both_trimmed,
        "drift_percent": {
            "left_trimmed": drift(left_trimmed),
            "right_trimmed": drift(right_trimmed),
            "both_trimmed": drift(both_trimmed),
        },
        "max_abs_drift_percent": max(
            abs(drift(left_trimmed)), abs(drift(right_trimmed)),
            abs(drift(both_trimmed))),
    }
