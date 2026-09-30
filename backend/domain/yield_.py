"""规定塑性延伸强度 Rp（默认 Rp0.2，偏移法）。

单位：偏移量 offset 为无量纲工程应变（0.2% = 0.002），方案里显式记录 offset_unit。
做法：作偏移直线 σ = E·(ε - offset)，在弹性段右端之后寻找与实测曲线的第一个交点，
交点附近线性插值求 σ 与 ε。无交点 / 模量不可得 / 应变无效时明确报告，不输出猜测值。
另提供上/下屈服点检测作为辅助（仅当出现屈服平台时有意义，缺失则标记不可得）。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class OffsetYieldResult:
    available: bool
    proof_stress_mpa: float | None
    proof_strain: float | None
    index_a: int | None = None
    index_b: int | None = None
    interpolation_fraction: float | None = None
    offset: float = 0.002
    warnings: list[str] | None = None
    reason_if_unavailable: str | None = None


def offset_yield(stress_mpa: np.ndarray | None,
                 strain: np.ndarray,
                 valid: np.ndarray,
                 base_mask: np.ndarray,
                 modulus_mpa: float,
                 elastic_end_index: int,
                 offset: float = 0.002) -> OffsetYieldResult:
    warnings: list[str] = []
    if stress_mpa is None:
        return OffsetYieldResult(
            available=False, proof_stress_mpa=None, proof_strain=None,
            reason_if_unavailable="应力不可计算（S0 缺失），无法做偏移法",
            warnings=[], offset=offset)
    if not np.isfinite(modulus_mpa) or modulus_mpa <= 0:
        return OffsetYieldResult(
            available=False, proof_stress_mpa=None, proof_strain=None,
            reason_if_unavailable="弹性模量拟合不可用，无法构造偏移直线",
            warnings=[], offset=offset)

    n = len(stress_mpa)
    mask = base_mask & valid
    idx = np.where(mask)[0]
    # 只在弹性段右端之后寻找交点
    idx = idx[idx >= elastic_end_index - 1]
    if len(idx) < 2:
        return OffsetYieldResult(
            available=False, proof_stress_mpa=None, proof_strain=None,
            reason_if_unavailable="弹性段之后没有足够的有效点寻找偏移线交点",
            warnings=[], offset=offset)

    e = strain[idx]
    s = stress_mpa[idx]
    line = modulus_mpa * (e - offset)
    diff = s - line

    # 弹性段内 σ - E(ε-offset) = E·offset > 0；交点是曲线被偏移线追平，
    # 即差值第一次由正转负的穿越。
    crossings = np.where((diff[:-1] >= 0) & (diff[1:] < 0))[0]
    if len(crossings) == 0:
        # 某些材料曲线一直在偏移线上方（无清晰屈服且偏移线与加载曲线不形成规范交点）
        return OffsetYieldResult(
            available=False, proof_stress_mpa=None, proof_strain=None,
            reason_if_unavailable=(
                "偏移直线与实测曲线在有效应变范围内无交点；可能偏移量不适用、"
                "引伸计过早摘除或材料无明确屈服特征"),
            warnings=["无清晰屈服：未找到偏移线交点"], offset=offset)

    k = int(crossings[0])
    ia, ib = int(idx[k]), int(idx[k + 1])
    # 在 [ia, ib] 间对 diff 线性插值求零点
    d0, d1 = diff[k], diff[k + 1]
    t = d0 / (d0 - d1)
    eps_p = float(strain[ia] + t * (strain[ib] - strain[ia]))
    sig_p = float(stress_mpa[ia] + t * (stress_mpa[ib] - stress_mpa[ia]))

    # 一致性检查：插值点应力不应超过区间最大应力太多
    seg_max = float(np.nanmax(s))
    if sig_p > seg_max * 1.02:
        warnings.append("偏移交点应力插值异常，请检查区间内数据点")

    return OffsetYieldResult(
        available=True,
        proof_stress_mpa=sig_p,
        proof_strain=eps_p,
        index_a=ia,
        index_b=ib,
        interpolation_fraction=float(t),
        offset=offset,
        warnings=warnings,
    )


@dataclass
class YieldPlateauResult:
    available: bool
    upper_yield_mpa: float | None = None
    lower_yield_mpa: float | None = None
    reason_if_unavailable: str | None = None


def yield_plateau(stress_mpa: np.ndarray | None,
                  valid: np.ndarray,
                  base_mask: np.ndarray,
                  search_end_index: int) -> YieldPlateauResult:
    """上/下屈服特征检测，两种形态：
    1) 尖点型：某点后出现 >2% 的载荷突降（上/下屈服点）；
    2) 平台型：弹性段后出现长平直段（应力变化 <0.5%，持续足够多点）。

    连续光滑硬化（无清晰屈服）时返回不可得，绝不强行取一个点。
    """
    if stress_mpa is None:
        return YieldPlateauResult(False, reason_if_unavailable="应力不可计算")
    end = min(search_end_index, int(0.6 * len(stress_mpa)))
    seg_idx = np.where(base_mask[:end] & valid[:end])[0]
    if len(seg_idx) < 20:
        return YieldPlateauResult(False, reason_if_unavailable="搜索点不足")
    s = stress_mpa[seg_idx]

    # 1) 尖点突降（发生在曲线前 1/3，避开颈缩与硬化波动）
    third = len(s) // 3
    window = max(5, len(s) // 20)
    for i in range(2, third - window):
        ahead_min = float(np.min(s[i: i + window]))
        if s[i] >= np.max(s[max(0, i - 3): i + 1]) and ahead_min < 0.98 * s[i]:
            return YieldPlateauResult(
                True, upper_yield_mpa=float(s[i]), lower_yield_mpa=ahead_min)

    # 2) 平直平台：只在曲线前 1/4 段（弹性段之后）搜索，
    #    避免把硬化曲线渐近变缓误判为平台。
    win = max(8, len(s) // 40)
    early_end = len(s) // 4
    global_max = float(np.max(s))
    for i in range(win, early_end):
        w = s[i: i + win]
        level = float(np.median(w))
        if level <= 0.1 * global_max:
            continue  # 排除起始贴合/零段
        # 窗口前应力必须已达到平台水平的 95%：
        # 渐变硬化曲线此前应力明显更低，真正的平台此前已爬到平台水平
        prev_max = float(np.max(s[:i]))
        if prev_max < 0.95 * level:
            continue
        if (float(np.max(w)) - float(np.min(w))) / level < 0.005:
            # 平台之后必须出现显著硬化回升（≥30%），以区别于硬化渐近段
            post_max = float(np.max(s[i + win:]))
            if post_max >= 1.30 * level:
                return YieldPlateauResult(
                    True, upper_yield_mpa=level, lower_yield_mpa=level)

    return YieldPlateauResult(
        False,
        reason_if_unavailable="弹性段后未检测到载荷突降或平直段（无清晰屈服平台）")
