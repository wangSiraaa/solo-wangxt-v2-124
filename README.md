# 材料实验室 · 拉伸试验分析系统

从试验机的**载荷/位移记录**计算弹性模量 E、规定塑性延伸强度 Rp（默认 Rp0.2）、
抗拉强度 Rm、断后伸长率 A、断面收缩率 Z，并对结果做完整溯源。

- 后端：FastAPI + SciPy（`scipy.stats.linregress`）+ SQLAlchemy + PostgreSQL
- 前端：Angular 18（独立组件）+ Plotly.js
- 工程/真实应力应变分别处理；颈缩后真应力/真应变一律置空并告警，不再"假装有效"
- 夹具位移与引伸计读数是两个独立通道与两种应变来源，绝不混入同一列
- 0.2% 偏移量全程带明确单位（无量纲应变 0.002 = 0.2%）
- 人工排除点必须填写原因；原始信号原样保留，排除只作用于分析方案
- 报告中每个数值都带公式、方法、输入溯源与诊断量，不接受"无来源的裸数字"

## 目录

```
backend/
  domain/
    units.py        内部单位约定(N, mm, MPa)与入站单位换算
    models.py       试样尺寸/设备参数/多通道信号/方案/带来源结果
    signals.py      信号 → 工程应力应变；颈缩点检测；真曲线只算到颈缩前
    elastic.py      E 线性拟合、逐点残差、R²/RMSE、区间端点内缩敏感性
    yield_.py       0.2% 偏移法交点(线性插值)；上/下屈服与平台检测
    strengths.py    Rm、断裂工程应力(诊断)、A、Z（尺寸缺失即不可得）
    analysis.py     编排，输出完整报告 JSON
    report.py       报告 JSON → Markdown
    synthetic.py    合成数据（清晰屈服 / 无清晰屈服）
  api/schemas.py    HTTP 入站模式
  db.py             ORM（PostgreSQL JSONB；演示可用内存 SQLite）
  repo.py           入库装配与原始单位换算
  main.py           FastAPI 端点
  tests/            领域核对测试 + API 冒烟测试
frontend/           Angular 18 + Plotly.js
docs/ARCHITECTURE.md
```

## 运行

### 后端

```bash
pip install -r requirements.txt

# PostgreSQL（生产）
createdb materials_lab
export DATABASE_URL="postgresql+psycopg://lab:lab@localhost:5432/materials_lab"
uvicorn backend.main:app --reload --port 8000

# 无 PostgreSQL 时的内存演示（数据不持久）
LAB_DEMO_SQLITE=1 uvicorn backend.main:app --port 8000
```

### 前端

```bash
cd frontend
npm install
npm start          # http://localhost:4200，/api 代理到 8000
```

打开后页面自动加载"线弹性+清晰屈服"合成案例；顶部三个按钮对应三个核对案例。

## 核对案例（合成数据）

| 案例 | 预期 |
|---|---|
| 线弹性+清晰屈服 | E 回收 200 GPa（误差 <0.1%）；Rp0.2 = 300 MPa；A=20%、Z=64% |
| 无清晰屈服 | E 仍为 200 GPa；上/下屈服判**不可得**并说明原因；不崩溃、不伪造点 |
| 尺寸缺失 | S0 缺失 → E/Rp/Rm/σf/A/Z 全部标记不可得并给出原因，不猜测面积 |

```bash
LAB_DEMO_SQLITE=1 python -m pytest backend/tests/ -q
```

## 关键工程约定

1. **应变来源显式声明**：引伸计 ε=ΔLe/Le（推荐）；夹具位移 ε=(δ−C·F)/L0，
   柔度 C 未知时不修正并告警，结果仅供参考。
2. **真应力/真应变**：σ_t=σ(1+ε)、ε_t=ln(1+ε) 只在最大力点（颈缩起始）前输出；
   颈缩后序列为 `null`，需要 Bridgman 修正才能继续，系统不做简单换算。
3. **断后指标只能靠试验后测量**：A 用断后标距 Lu，Z 用缩颈处最小面积 Su；
   不能用力学位移推算，缺测量值就报不可得。
4. **弹性区选择可见诊断**：逐点残差、R²、RMSE，以及端点各内缩一档后 E 的漂移%，
   前端拖选区间时实时预览。
5. **0.2% 偏移法**：偏移线 σ=E(ε−0.002)，取与实测曲线的第一个交点，
   相邻采样点间线性插值；无交点时明确报告，不输出猜测值。

## API 摘要

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/specimens` | 试样尺寸（尺寸可缺，相关指标随后报不可得） |
| POST | `/devices` | 传感器量程/等级、引伸计标距、机架柔度 |
| POST | `/tests/signals` | 导入四列信号（时间/载荷/夹具位移/引伸计位移），携带原始单位 |
| POST | `/analyses/elastic-preview` | 只算 E 拟合+残差+区间影响（拖选时实时调用） |
| POST | `/analyses` | 按方案运行并落库完整报告 |
| GET | `/analyses/{id}` | 报告 JSON（含溯源、诊断、曲线序列） |
| GET | `/analyses/{id}/report` | 报告 Markdown 下载 |
| POST | `/demo/synthetic/{case}` | clear_yield / no_clear_yield / missing_dims |
