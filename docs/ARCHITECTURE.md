# 架构说明

## 数据流

```
试验机导出 CSV
   │  time_s, force(kN), crosshead_disp(mm), extensometer_disp(mm)
   ▼
POST /tests/signals（携带原始单位）
   │  repo.convert_signal：kN→N、in→mm；四列独立写入 raw_signal(JSONB)
   ▼
PostgreSQL
   ├── specimens.geometry      试样尺寸（d0/b0/a0/L0；断后 Lu/du…）
   ├── devices.params          量程、准确度等级、引伸计标距 Le、机架柔度 C
   ├── tests.raw_signal        原始信号（永不就地覆盖）
   └── analyses
        ├── plan               弹性区、偏移量、应变来源、阈值
        ├── excluded_points    [{index, reason, author, created_at}]
        └── report             完整带来源的结果 + 曲线序列
   ▲
   │ POST /analyses（方案 + 排除点）
domain/analysis.run_analysis
   ├── signals.build_curve
   │     ├── engineering_stress = F / S0           （S0 缺 → 不可得）
   │     ├── engineering_strain：按来源分通道计算
   │     ├── argmax(F)  → 颈缩起始索引 m
   │     └── true 应力/应变只填 [0, m]，m 后为 null
   ├── elastic.fit_modulus        scipy.stats.linregress
   │     └── 残差/R²/RMSE + interval_influence（端点内缩）
   ├── yield_.offset_yield        σ=E(ε−e_p) 第一个交点 + 线性插值
   ├── yield_.yield_plateau       突降 / 平直平台 + 后续硬化回升判据
   └── strengths                  Rm、σf(诊断)、A、Z
```

## "不假装有效"的边界

| 情形 | 系统行为 |
|---|---|
| 颈缩后求真应力/真应变 | 序列置 null + 告警"需 Bridgman 修正" |
| S0（原始尺寸）缺失 | σ、E、Rp、Rm、σf 全部 unavailable + 原因 |
| Lu / Su 断后尺寸缺失 | A / Z 不可得；明确"不能用力学位移推算" |
| 偏移交点不存在 | Rp 不可得，附搜索区间与可能原因（引伸计早摘除等） |
| 弹性有效点 < 最小值 / R² 过低 | E 不可得或告警，展示实际点数 |
| 只有夹具位移且柔度未知 | 应变可算，但标注未修正、E 仅供参考 |
| 连续硬化无屈服平台 | 上/下屈服不可得，不强行取点 |

## 结果溯源结构（SourcedValue）

```json
{
  "key": "E", "label": "弹性模量 E",
  "value": 200000.0, "unit": "MPa", "available": true,
  "formula": "σ = E·ε + b（最小二乘）",
  "method": "弹性段应力-应变线性拟合（SciPy linregress）",
  "inputs": { "strain_source": "extensometer", "plan": "...",
              "elastic_index_range": [4, 10] },
  "diagnostics": { "r2": 1.0, "rmse_mpa": 2e-14,
                   "residual_mpa": [...],
                   "interval_influence": {...} },
  "warnings": []
}
```

前端结果表每行可展开"输入/诊断/告警"；Markdown 报告同样逐条列出来源。

## 前端交互

- Plotly.js 主图：工程曲线、真曲线（颈缩后断线）、弹性拟合点与拟合线、
  0.2% 偏移线（图例注明 0.002 无量纲应变 = 0.2%）、Rp 交点星标、最大力点。
- 区间用点索引指定（与数据点严格对应，避免应变轴投影歧义），调整即调
  `/analyses/elastic-preview`，残差图与漂移%即时刷新。
- 排除点输入格式 `索引:原因`；无原因的排除请求在 Pydantic 层 422 拒绝。
- 同一试验每次分析独立落库，"方案历史"表对比不同区间的 E/Rp/Rm。

## 测试策略

- 领域纯函数测试：合成理想曲线精确回收已知 E/Rp；
  用突变/平台/光滑硬化三种形态覆盖屈服判据；
  尺寸缺失、颈缩置空、排除点原因约束逐条断言。
- API 测试：内存 SQLite + TestClient，覆盖单位换算、落库、422 校验、报告读取。
