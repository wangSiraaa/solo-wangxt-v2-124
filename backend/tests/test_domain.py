"""领域核对测试（合成数据）：
1) 理想线弹性案例：E 应回到 200 GPa，Rp0.2 应回到 ~300 MPa，Rm 正确；
2) 无清晰屈服案例：上/下屈服判不可得，但不崩溃，偏移法照常尝试；
3) 尺寸缺失案例：应力相关指标全部 available=False 且给出原因；
4) 颈缩后真应力/真应变必须为 null；
5) 排除点必须带原因，残差与区间影响随报告输出。
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from backend.domain.analysis import run_analysis
from backend.domain.models import (
    AnalysisPlan,
    ExcludedPoint,
    SpecimenGeometry,
    SpecimenShape,
    StrainSource,
)
from backend.domain.synthetic import (
    E_TRUE_MPA,
    S0_MM2,
    SY_TRUE_MPA,
    default_device,
    round_bar_specimen,
    synthetic_clear_yield,
    synthetic_no_clear_yield,
)


def _plan(index_range):
    lo, hi = index_range
    return AnalysisPlan(
        name="test",
        strain_source=StrainSource.EXTENSOMETER,
        elastic_index_min=lo, elastic_index_max=hi,
        min_elastic_points=5)


def test_clear_yield_modulus_and_proof_and_rm():
    ch, eps, sig = synthetic_clear_yield()
    spec = round_bar_specimen(lu=60.0, du=6.0)
    dev = default_device()

    # 弹性段取 ε 约 0.0005~0.0013（600 点覆盖 0~0.08 → 索引 4~10）
    plan = _plan((4, 10))
    rep = run_analysis(ch, spec, dev, plan)

    by_key = {r["key"]: r for r in rep["results"]}
    E = by_key["E"]
    assert E["available"]
    assert E["value"] == pytest.approx(E_TRUE_MPA, rel=1e-3)
    assert E["diagnostics"]["r2"] > 0.9999
    assert len(E["diagnostics"]["residual_mpa"]) == 6
    assert "interval_influence" in E["diagnostics"]

    Rp = by_key["Rp0.2"]
    assert Rp["available"], Rp["reason_if_unavailable"]
    # 合成屈服 300 MPa，插值应有小偏差（硬化过渡段）
    assert Rp["value"] == pytest.approx(SY_TRUE_MPA, abs=3.0)
    assert Rp["inputs"]["offset"] == 0.002
    assert "0.002 = 0.2%" in Rp["inputs"]["offset_unit"]

    Rm = by_key["Rm"]
    fmax = float(np.max(ch.force_n))
    assert Rm["available"]
    assert Rm["value"] == pytest.approx(fmax / S0_MM2, rel=1e-9)


def test_true_curve_null_after_necking():
    ch, eps, sig = synthetic_clear_yield()
    rep = run_analysis(ch, round_bar_specimen(), default_device(), _plan((4, 10)))
    m = rep["curve_limits"]["max_force_index"]
    ts = np.array([np.nan if v is None else v
                   for v in rep["series"]["true_stress_mpa"]])
    assert np.all(np.isnan(ts[m + 1:]))
    assert np.all(np.isfinite(ts[: m + 1]))
    assert any("颈缩" in w for w in rep["warnings"])


def test_no_clear_yield_has_no_plateau_but_pipeline_runs():
    ch, eps, sig = synthetic_no_clear_yield()
    plan = _plan((2, 8))
    rep = run_analysis(ch, round_bar_specimen(), default_device(), plan)
    assert rep["yield_plateau"]["available"] is False
    reason = rep["yield_plateau"]["reason_if_unavailable"]
    assert "屈服平台" in reason
    # 连续硬化曲线也可能找不到规范偏移交点；无论如何不得伪造数值
    by_key = {r["key"]: r for r in rep["results"]}
    if not by_key["Rp0.2"]["available"]:
        assert by_key["Rp0.2"]["reason_if_unavailable"]


def test_missing_dimensions_makes_stress_metrics_unavailable():
    ch, _, _ = synthetic_clear_yield()
    spec = SpecimenGeometry(
        specimen_id="MISS", shape=SpecimenShape.ROUND,
        diameter_mm=None, gauge_length_mm=50.0)
    rep = run_analysis(ch, spec, default_device(), _plan((4, 10)))
    by_key = {r["key"]: r for r in rep["results"]}
    for key in ("E", "Rp0.2", "Rm", "sigma_f_eng"):
        assert by_key[key]["available"] is False
        assert by_key[key]["reason_if_unavailable"]
    assert rep["elastic_fit"]["available"] is False
    # 断后指标同样缺尺寸
    assert by_key["Z"]["available"] is False
    assert "Su" in by_key["Z"]["reason_if_unavailable"] or "S0" in by_key["Z"]["reason_if_unavailable"]


def test_A_and_Z_from_post_fracture_dimensions():
    ch, _, _ = synthetic_clear_yield()
    spec = round_bar_specimen(lu=60.0, du=6.0)  # A=20%
    rep = run_analysis(ch, spec, default_device(), _plan((4, 10)))
    by_key = {r["key"]: r for r in rep["results"]}
    assert by_key["A"]["value"] == pytest.approx(20.0)
    s0 = math.pi * 10 ** 2 / 4
    su = math.pi * 6 ** 2 / 4
    assert by_key["Z"]["value"] == pytest.approx((s0 - su) / s0 * 100)


def test_excluded_points_need_reason_and_affect_fit():
    ch, _, _ = synthetic_clear_yield()
    with pytest.raises(Exception):
        ExcludedPoint(index=5, reason="", author="a")
    excl = [ExcludedPoint(index=6, reason="引伸计滑移尖点（核对录像确认）", author="tester")]
    rep = run_analysis(ch, round_bar_specimen(), default_device(),
                       _plan((4, 10)), exclusions=excl)
    assert rep["excluded_points"][0]["reason"].startswith("引伸计滑移")
    used = rep["elastic_fit"]["used_indices"]
    assert 6 not in used


def test_crosshead_strain_is_separate_channel_with_warning():
    ch, _, _ = synthetic_clear_yield()
    plan = AnalysisPlan(
        name="cross", strain_source=StrainSource.CROSSHEAD,
        elastic_index_min=4, elastic_index_max=10)
    rep = run_analysis(ch, round_bar_specimen(), default_device(), plan)
    assert rep["strain_source"] == "crosshead"
    assert any("夹具位移" in w for w in rep["results"][0]["warnings"] + rep["warnings"])


def test_report_carries_provenance_not_bare_numbers():
    ch, _, _ = synthetic_clear_yield()
    rep = run_analysis(ch, round_bar_specimen(lu=60.0, du=6.0),
                       default_device(), _plan((4, 10)))
    for r in rep["results"]:
        assert r["formula"]
        assert r["method"]
        assert r["inputs"]
        assert r["unit"]
    assert rep["plan"]["elastic_index_min"] == 4
