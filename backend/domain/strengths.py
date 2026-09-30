"""抗拉强度、断裂点应力与断后塑性指标（A、Z）。

- 抗拉强度 Rm = Fm / S0（最大力点，注意不是断裂点）。
- 断后伸长率 A = (Lu - L0) / L0 ×100%；依赖试验后人工测量的 Lu，缺失即不可得。
- 断面收缩率 Z = (S0 - Su) / S0 ×100%；依赖断后缩颈处尺寸，缺失即不可得。
- 断裂应力（工程）仅作诊断参考：σ_f = F_f / S0；颈缩后不能反推真实承载面积。
"""
from __future__ import annotations

from .models import SourcedValue, SpecimenGeometry
from .signals import StressStrainResult


def tensile_strength(curve: StressStrainResult) -> SourcedValue:
    fmax = float(curve.force_n[curve.max_force_index])
    inputs = {
        "max_force_n": fmax,
        "max_force_index": curve.max_force_index,
        "area0_mm2": curve.area0_mm2,
    }
    if curve.area0_mm2 is None:
        return SourcedValue(
            key="Rm", label="抗拉强度 Rm", value=None, unit="MPa",
            available=False,
            reason_if_unavailable="S0 缺失：试样原始尺寸不完整，无法计算 Rm",
            formula="Rm = Fm / S0", inputs=inputs,
            method="最大力点载荷除以原始横截面积")
    rm = fmax / curve.area0_mm2
    return SourcedValue(
        key="Rm", label="抗拉强度 Rm", value=rm, unit="MPa",
        formula="Rm = Fm / S0", inputs=inputs,
        method="最大力点载荷除以原始横截面积",
        diagnostics={"max_force_index": curve.max_force_index,
                     "engineering_or_true": "engineering"})


def fracture_stress_eng(curve: StressStrainResult) -> SourcedValue:
    fi = curve.fracture_index
    ff = float(curve.force_n[fi])
    inputs = {"fracture_force_n": ff, "fracture_index": fi,
              "area0_mm2": curve.area0_mm2}
    w = ["断裂点由最大力后载荷跌破 5%·Fm 自动判定，请结合曲线确认"]
    if curve.area0_mm2 is None:
        return SourcedValue(
            key="sigma_f_eng", label="断裂工程应力（诊断）", value=None,
            unit="MPa", available=False,
            reason_if_unavailable="S0 缺失", formula="σ_f = F_f / S0",
            inputs=inputs, warnings=w)
    return SourcedValue(
        key="sigma_f_eng", label="断裂工程应力（诊断）",
        value=ff / curve.area0_mm2, unit="MPa",
        formula="σ_f = F_f / S0（用 S0，非颈缩真实面积）",
        inputs=inputs, method="断裂点载荷 / 原始面积",
        warnings=w + ["颈缩后真实承载面积未知，此值不等于断裂真应力"])


def elongation_after_fracture(spec: SpecimenGeometry) -> SourcedValue:
    l0 = spec.gauge_length_mm
    lu = spec.final_gauge_length_mm
    inputs = {"L0_mm": l0, "Lu_mm": lu}
    if lu is None:
        return SourcedValue(
            key="A", label="断后伸长率 A", value=None, unit="%",
            available=False,
            reason_if_unavailable="断后标距 Lu 未测量/未录入，A 不可计算（不能用力学位移推算）",
            formula="A = (Lu - L0) / L0 × 100%", inputs=inputs,
            method="试验后对接试样，人工测量标距")
    a_pct = (lu - l0) / l0 * 100.0
    w: list[str] = []
    if a_pct < 0:
        w.append("Lu < L0，断后测量异常，需复核")
    return SourcedValue(
        key="A", label="断后伸长率 A", value=a_pct, unit="%",
        formula="A = (Lu - L0) / L0 × 100%", inputs=inputs,
        method="试验后对接试样，人工测量标距", warnings=w,
        diagnostics={"L0_mm": l0, "Lu_mm": lu,
                     "permanent_extension_mm": lu - l0})


def reduction_of_area(spec: SpecimenGeometry) -> SourcedValue:
    s0 = spec.area0_mm2()
    su = spec.areau_mm2()
    inputs = {"S0_mm2": s0, "Su_mm2": su,
              "shape": spec.shape.value}
    missing = []
    if s0 is None:
        missing.append("S0（原始尺寸不完整）")
    if su is None:
        missing.append("Su（断后缩颈处尺寸未测量/未录入）")
    if missing:
        return SourcedValue(
            key="Z", label="断面收缩率 Z", value=None, unit="%",
            available=False,
            reason_if_unavailable=f"{'、'.join(missing)}缺失，Z 不可计算",
            formula="Z = (S0 - Su) / S0 × 100%", inputs=inputs,
            method="试验后测量缩颈处最小直径/宽厚")
    z = (s0 - su) / s0 * 100.0
    w: list[str] = []
    if z < 0:
        w.append("Su > S0，断后尺寸测量异常，需复核")
    return SourcedValue(
        key="Z", label="断面收缩率 Z", value=z, unit="%",
        formula="Z = (S0 - Su) / S0 × 100%", inputs=inputs,
        method="试验后测量缩颈处最小直径/宽厚", warnings=w,
        diagnostics={"S0_mm2": s0, "Su_mm2": su})
