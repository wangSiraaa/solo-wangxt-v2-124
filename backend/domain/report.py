"""把带来源的报告渲染为可归档的 Markdown。

不允许只输出几个无来源的最终数值：每个指标列出数值/单位、公式、
输入与方案溯源、诊断量、告警；不可得项写明原因。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any


def _fmt(v, nd: int = 4) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.{nd}g}"
    return str(v)


def render_markdown(rep: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"# 拉伸试验分析报告（{rep.get('specimen_id', '')}）")
    lines.append("")
    lines.append(f"- 生成时间（UTC）：{rep.get('generated_at', '')}")
    lines.append(f"- 报告 ID：{rep.get('report_id') or '（未保存）'}")
    lines.append(f"- 应变来源：**{rep.get('strain_source')}**"
                 "（引伸计/夹具位移，二者独立）")
    plan = rep.get("plan", {})
    lines.append(f"- 计算方案：{plan.get('name')}，作者 {plan.get('author')}")
    lines.append(f"- 偏移量：{plan.get('offset')} 无量纲应变 "
                 f"= {float(plan.get('offset', 0)) * 100:g}%")
    cl = rep.get("curve_limits", {})
    lines.append(f"- 最大力点索引：{cl.get('max_force_index')}；"
                 f"断裂点索引：{cl.get('fracture_index')}；"
                 f"真应力/真应变有效至索引："
                 f"{cl.get('true_curve_valid_until_index')}（其后颈缩，换算无效）")
    lines.append("")

    lines.append("## 结果（含来源）")
    lines.append("")
    lines.append("| 指标 | 结果 | 单位 | 公式/方法 | 输入溯源 | 状态 |")
    lines.append("|---|---|---|---|---|---|")
    for r in rep.get("results", []):
        if r["available"]:
            status = "✅"
            val = _fmt(r["value"])
        else:
            status = f"❌ {r.get('reason_if_unavailable', '')}"
            val = "不可得"
        inputs = "; ".join(f"{k}={_fmt(v, 5)}" for k, v in
                           (r.get("inputs") or {}).items()
                           if not isinstance(v, (list, dict)))
        formula = (r.get("formula") or "") + "；" + (r.get("method") or "")
        lines.append(
            f"| {r['label']} | {val} | {r['unit']} | {formula.strip('；')} "
            f"| {inputs} | {status} |")
    lines.append("")

    ef = rep.get("elastic_fit", {})
    if ef.get("available"):
        lines.append("## 弹性模量拟合诊断")
        lines.append("")
        lines.append(f"- E = {_fmt(ef['modulus_mpa'])} MPa；"
                     f"R² = {ef['r2']:.6f}；RMSE = {_fmt(ef['rmse_mpa'])} MPa；"
                     f"拟合点数 = {len(ef.get('used_indices', []))}")
        inf = ef.get("interval_influence") or {}
        if inf.get("available"):
            d = inf["drift_percent"]
            lines.append(
                f"- 区间敏感性（每端内缩 {inf['trim_points_each_side']} 点）："
                f"左端 {d['left_trimmed']:+.2f}%，右端 {d['right_trimmed']:+.2f}%，"
                f"两端 {d['both_trimmed']:+.2f}%；"
                f"最大绝对漂移 {inf['max_abs_drift_percent']:.2f}%")
        res = ef.get("residual_mpa") or []
        lines.append(f"- 逐点残差（MPa）：{', '.join(f'{x:.3f}' for x in res[:20])}"
                     + (" …" if len(res) > 20 else ""))
        lines.append("")

    oy = rep.get("offset_yield") or {}
    lines.append("## 0.2% 偏移法（单位：无量纲工程应变，0.002 = 0.2%）")
    lines.append("")
    if oy.get("available"):
        lines.append(f"- Rp{oy['offset']*100:g} = {_fmt(oy['proof_stress_mpa'])} MPa，"
                     f"对应应变 {oy['proof_strain']:.6f} "
                     f"= {oy['proof_strain']*100:.3f}%")
        lines.append(f"- 交点位于索引 {oy['index_a']}–{oy['index_b']} 之间，"
                     f"线性插值系数 {oy['interpolation_fraction']:.3f}")
    else:
        lines.append(f"- 不可得：{oy.get('reason_if_unavailable')}")
    lines.append("")

    lines.append("## 人工排除点（原始信号保留，仅在分析中屏蔽）")
    lines.append("")
    ex = rep.get("excluded_points") or []
    if ex:
        for e in ex:
            lines.append(f"- 索引 {e['index']}：{e['reason']}（{e['author']}，{e['created_at']}）")
    else:
        lines.append("- 无")
    lines.append("")

    if rep.get("warnings"):
        lines.append("## 告警")
        lines.append("")
        for w in rep["warnings"]:
            lines.append(f"- ⚠️ {w}")
        lines.append("")

    if rep.get("unavailable_reasons"):
        lines.append("## 不可计算原因")
        for r in rep["unavailable_reasons"]:
            lines.append(f"- {r}")
        lines.append("")

    lines.append(f"_报告渲染时间 {datetime.utcnow().isoformat()}Z_")
    return "\n".join(lines)
