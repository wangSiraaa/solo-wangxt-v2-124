import { CommonModule } from '@angular/common';
import { Component, OnInit, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { first } from 'rxjs';
import { ApiService } from './api.service';
import { PlotComponent } from './plot.component';
import { AnalyzeRequest, Report } from './report.model';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [CommonModule, FormsModule, PlotComponent],
  templateUrl: './app.component.html',
})
export class AppComponent implements OnInit {
  private api = inject(ApiService);

  report: Report | null = null;
  testId = '';
  loading = false;
  error = '';
  savedAnalysisId = '';
  history: any[] = [];

  // 方案输入
  strainSource: 'extensometer' | 'crosshead' = 'extensometer';
  idxMin: number | null = null;
  idxMax: number | null = null;
  offsetPct = 0.2;                 // UI 用百分数：0.2%（明确单位）
  minPoints = 10;
  r2Threshold = 0.99;
  notes = '';
  excludeInput = '';

  // 曲线显示选择
  showEng = true;
  showTrue = true;
  showOffsetLine = true;

  curveTraces: any[] = [];
  curveLayout: any = {};
  residualTraces: any[] = [];
  residualLayout: any = {};

  ngOnInit(): void {
    this.loadDemo('clear_yield');
  }

  loadDemo(name: 'clear_yield' | 'no_clear_yield' | 'missing_dims'): void {
    this.loading = true;
    this.error = '';
    this.api.demoCase(name).pipe(first()).subscribe({
      next: (d) => {
        this.testId = d.test_id;
        this.savedAnalysisId = d.analysis_id;
        this.api.getReport(d.analysis_id).pipe(first()).subscribe({
          next: (rep) => {
            this.report = rep;
            const p = rep.plan;
            this.strainSource = rep.strain_source as any;
            this.idxMin = p.elastic_index_min;
            this.idxMax = p.elastic_index_max;
            this.offsetPct = (p.offset ?? 0.002) * 100;
            this.minPoints = p.min_elastic_points ?? 10;
            this.notes = p.notes ?? '';
            this.refreshHistory();
            this.render();
            this.loading = false;
          },
          error: (e) => this.fail(e),
        });
      },
      error: (e) => this.fail(e),
    });
  }

  private fail(e: any): void {
    this.loading = false;
    this.error = typeof e?.error?.detail === 'string'
      ? e.error.detail : (e?.message ?? '请求失败');
  }

  private refreshHistory(): void {
    if (!this.testId) return;
    this.api.listByTest(this.testId).pipe(first()).subscribe({
      next: (rows) => (this.history = rows),
      error: () => (this.history = []),
    });
  }

  private body(persistExclusions: boolean): AnalyzeRequest {
    return {
      test_id: this.testId,
      strain_source: this.strainSource,
      elastic_index_min: this.idxMin,
      elastic_index_max: this.idxMax,
      offset: this.offsetPct / 100,   // 0.2% → 0.002 无量纲应变
      min_elastic_points: this.minPoints,
      r2_warning_threshold: this.r2Threshold,
      notes: this.notes || null,
      excluded_points: persistExclusions && this.report
        ? this.report.excluded_points.map((e) => ({
            index: e.index, reason: e.reason, author: 'lab-user' }))
        : [],
    };
  }

  /** 拖选区间实时预览：拟合残差 + 区间影响。 */
  preview(): void {
    if (!this.testId || this.idxMin == null || this.idxMax == null) return;
    this.loading = true;
    this.api.preview(this.body(false)).pipe(first()).subscribe({
      next: (d) => {
        if (this.report) {
          this.report.elastic_fit = d.elastic_fit;
          this.report.offset_yield = d.offset_yield;
          this.report.warnings = d.warnings;
          this.render();
        }
        this.loading = false;
      },
      error: (e) => this.fail(e),
    });
  }

  runAnalysis(): void {
    if (!this.testId) return;
    this.loading = true;
    this.api.analyze(this.body(true)).pipe(first()).subscribe({
      next: (d) => {
        this.savedAnalysisId = d.id;
        this.api.getReport(d.id).pipe(first()).subscribe({
          next: (rep) => {
            this.report = rep;
            this.refreshHistory();
            this.render();
            this.loading = false;
          },
          error: (e) => this.fail(e),
        });
      },
      error: (e) => this.fail(e),
    });
  }

  addExclusion(): void {
    if (!this.report) return;
    const lines = this.excludeInput
      .split(/[;\n]/)
      .map((s) => s.trim())
      .filter(Boolean);
    for (const ln of lines) {
      const m = ln.match(/^(\d+)\s*[:：]\s*(.+)$/);
      if (!m) continue;
      const index = Number(m[1]);
      const reason = m[2].trim();
      if (!this.report.excluded_points.some((e) => e.index === index)) {
        this.report.excluded_points.push({
          index, reason, author: 'lab-user',
          created_at: new Date().toISOString(),
        });
      }
    }
    this.excludeInput = '';
    this.preview();
  }

  removeExclusion(i: number): void {
    this.report?.excluded_points.splice(i, 1);
    this.preview();
  }

  render(): void {
    if (!this.report) return;
    const s = this.report.series;
    const lim = this.report.curve_limits;
    const traces: any[] = [];

    if (this.showEng) {
      traces.push({
        x: s.engineering_strain,
        y: s.engineering_stress_mpa,
        mode: 'lines',
        name: '工程应力-应变',
        line: { color: '#1d4ed8', width: 2 },
      });
    }
    if (this.showTrue) {
      // 颈缩后的点为 null，Plotly 自动断线，视觉上就不展示"假"真应力
      traces.push({
        x: s.true_strain,
        y: s.true_stress_mpa,
        mode: 'lines',
        name: `真应力-应变（仅颈缩前，索引 ≤ ${lim.true_curve_valid_until_index}）`,
        line: { color: '#15803d', width: 2, dash: 'dash' },
      });
    }

    // 弹性拟合点高亮
    const fit = this.report.elastic_fit;
    if (fit.available) {
      const ui = fit.used_indices;
      traces.push({
        x: ui.map((i) => s.engineering_strain[i]),
        y: ui.map((i) => s.engineering_stress_mpa[i]),
        mode: 'markers',
        name: '弹性拟合点',
        marker: { color: '#f59e0b', size: 7 },
      });
      // 拟合直线（覆盖区间外延一点）
      const e0 = Math.min(...ui.map((i) => s.engineering_strain[i] ?? 0));
      const e1 = Math.max(...ui.map((i) => s.engineering_strain[i] ?? 0));
      const E = fit.modulus_mpa ?? 0;
      const inter = this.fittedIntercept();
      traces.push({
        x: [e0, e1 * 1.15],
        y: [E * e0 + inter, E * (e1 * 1.15) + inter],
        mode: 'lines',
        name: `E 拟合线 (E=${(E / 1000).toFixed(1)} GPa)`,
        line: { color: '#f59e0b', width: 1.5, dash: 'dot' },
      });
    }

    // 0.2% 偏移线（单位在图例写清）
    if (this.showOffsetLine && fit.available && fit.modulus_mpa) {
      const offset = this.offsetPct / 100;
      const E = fit.modulus_mpa;
      const xMax = Math.max(
        ...s.engineering_strain.filter((v): v is number => v != null));
      traces.push({
        x: [offset, xMax],
        y: [0, E * (xMax - offset)],
        mode: 'lines',
        name: `偏移线（offset=${this.offsetPct}% = ${(offset).toFixed(3)} 无量纲应变）`,
        line: { color: '#b91c1c', width: 1.5, dash: 'dashdot' },
      });
    }

    // 偏移交点
    const oy = this.report.offset_yield;
    if (oy.available && oy.proof_strain != null) {
      traces.push({
        x: [oy.proof_strain], y: [oy.proof_stress_mpa],
        mode: 'markers+text', name: `Rp${this.offsetPct}`,
        text: [`Rp${this.offsetPct}`], textposition: 'top right',
        marker: { color: '#b91c1c', size: 11, symbol: 'star' },
      });
    }

    // 最大力点 / 断裂点
    traces.push({
      x: [s.engineering_strain[lim.max_force_index]],
      y: [s.engineering_stress_mpa[lim.max_force_index]],
      mode: 'markers', name: '最大力点（颈缩起始）',
      marker: { color: '#374151', size: 9, symbol: 'triangle-down' },
    });

    const shapes: any[] = [];
    if (this.idxMin != null && this.idxMax != null) {
      const xs = [this.idxMin, this.idxMax]
        .map((i) => s.engineering_strain[Math.min(i, s.index.length - 1)])
        .filter((v): v is number => v != null);
      shapes.push({
        type: 'rect', xref: 'x', yref: 'paper',
        x0: Math.min(...xs), x1: Math.max(...xs), y0: 0, y1: 1,
        fillcolor: '#f59e0b', opacity: 0.08, line: { width: 0 },
      });
    }

    this.curveTraces = traces;
    this.curveLayout = {
      title: '应力-应变曲线（工程 / 真实；真曲线颈缩后无效不显示）',
      xaxis: { title: '应变（无量纲；×100 = %）', zeroline: true },
      yaxis: { title: '应力 [MPa]' },
      legend: { orientation: 'h', y: -0.18 },
      hovermode: 'x unified',
      shapes,
    };

    // 残差图
    if (fit.available && fit.residual_mpa.length) {
      this.residualTraces = [{
        x: fit.used_indices,
        y: fit.residual_mpa,
        mode: 'markers',
        name: '拟合残差',
        marker: { color: '#7c3aed', size: 8 },
      }, {
        x: [fit.used_indices[0], fit.used_indices[fit.used_indices.length - 1]],
        y: [0, 0], mode: 'lines', showlegend: false,
        line: { color: '#9ca3af', dash: 'dot' },
      }];
      this.residualLayout = {
        title: `弹性拟合逐点残差 [MPa]，RMSE=${(fit.rmse_mpa ?? 0).toFixed(3)}，`
             + `R²=${(fit.r2 ?? 0).toFixed(5)}`,
        xaxis: { title: '数据点索引' },
        yaxis: { title: '残差 [MPa]' },
      };
    } else {
      this.residualTraces = [];
      this.residualLayout = {
        title: fit.reason_if_unavailable ?? '无弹性拟合结果',
        annotations: [{ text: '拟合不可用', showarrow: false }],
      };
    }
  }

  private fittedIntercept(): number {
    const r = this.report?.results.find((x) => x.key === 'E');
    return Number(r?.diagnostics?.['intercept_mpa'] ?? 0);
  }

  get resultRows() {
    return this.report?.results ?? [];
  }

  get influence() {
    return this.report?.elastic_fit.interval_influence;
  }

  downloadReport(): void {
    if (!this.savedAnalysisId) return;
    window.open(this.api.reportUrl(this.savedAnalysisId), '_blank');
  }

  fmt(v: number | null, nd = 4): string {
    return v == null ? '—' : Number(v).toPrecision(nd);
  }
}
