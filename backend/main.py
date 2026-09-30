"""FastAPI 入口。

端点：
POST /specimens                 录入试样尺寸（缺失允许，但相关指标会标不可得）
POST /devices                   录入设备参数
POST /tests/signals             导入原始信号（原始单位→N/mm，分列保留）
POST /analyses                  选定方案运行分析，落库完整带来源的报告
GET  /analyses/{id}             读取报告
GET  /analyses/by-test/{test_id} 某试验的所有分析（方案对比）
POST /analyses/elastic-preview  仅算模量拟合/残差/区间影响（拖选区间实时调用）
GET  /demo/synthetic/{case}     内置合成案例：clear_yield / no_clear_yield / missing_dims
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.domain.analysis import run_analysis
from backend.domain.models import StrainSource
from backend.domain.report import render_markdown
from backend.domain.synthetic import (
    default_device,
    round_bar_specimen,
    synthetic_clear_yield,
    synthetic_no_clear_yield,
)

from . import repo
from .api.schemas import AnalyzeIn, DeviceIn, ElasticPreviewIn, GeometryIn, SignalIn
from .db import AnalysisRecord, DeviceRecord, SessionLocal, SpecimenRecord, TestRecord, init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="材料实验室拉伸试验分析服务", version="0.1.0",
              lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200", "http://127.0.0.1:4200"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def db_session() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/specimens")
def create_specimen(body: GeometryIn, db: Session = Depends(db_session)):
    if repo.get_specimen(db, body.specimen_code):
        raise HTTPException(409, f"试样编号已存在: {body.specimen_code}")
    rec = SpecimenRecord(
        specimen_code=body.specimen_code,
        shape=body.shape,
        material=body.material,
        geometry=body.model_dump(exclude={"specimen_code", "material", "shape"}),
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return {"id": rec.id, "specimen_code": rec.specimen_code}


@app.post("/devices")
def create_device(body: DeviceIn, db: Session = Depends(db_session)):
    if repo.get_device(db, body.machine_id):
        raise HTTPException(409, f"设备已存在: {body.machine_id}")
    rec = DeviceRecord(params=body.model_dump())
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return {"id": rec.id}


@app.post("/tests/signals")
def import_signal(body: SignalIn, db: Session = Depends(db_session)):
    specimen = repo.get_specimen(db, body.specimen_code)
    if specimen is None:
        raise HTTPException(404, f"试样不存在: {body.specimen_code}")
    device = repo.get_device(db, body.device_machine_id)
    if device is None:
        raise HTTPException(404, f"设备不存在: {body.device_machine_id}")
    if db.scalar(select(TestRecord).where(TestRecord.test_code == body.test_code)):
        raise HTTPException(409, f"试验编号已存在: {body.test_code}")

    try:
        raw, units_meta = repo.convert_signal(body.model_dump())
    except ValueError as e:
        raise HTTPException(422, str(e))

    rec = TestRecord(
        test_code=body.test_code,
        specimen_id=specimen.id,
        device_id=device.id,
        test_standard=body.test_standard,
        raw_signal=raw,
        channel_units=units_meta,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return {"id": rec.id, "test_code": rec.test_code,
            "points": len(raw["time_s"]), "units": units_meta}


def _assemble(db: Session, body: AnalyzeIn):
    test = repo.get_test(db, body.test_id)
    if test is None:
        raise HTTPException(404, "试验不存在")
    specimen = repo.spec_to_domain(test.specimen)
    device = repo.device_to_domain(test.device)
    channels = repo.signal_to_domain(test)
    plan = repo.plan_from_payload(body.model_dump())
    exclusions = repo.exclusions_from_payload(
        [e.model_dump() for e in body.excluded_points])
    return test, specimen, device, channels, plan, exclusions


@app.post("/analyses/elastic-preview")
def elastic_preview(body: ElasticPreviewIn, db: Session = Depends(db_session)):
    test, specimen, device, channels, plan, exclusions = _assemble(db, body)
    report = run_analysis(channels, specimen, device, plan, exclusions)
    return {
        "elastic_fit": report["elastic_fit"],
        "warnings": report["warnings"],
        "curve_limits": report["curve_limits"],
        "offset_yield": report["offset_yield"],
    }


@app.post("/analyses")
def analyze(body: AnalyzeIn, db: Session = Depends(db_session)):
    test, specimen, device, channels, plan, exclusions = _assemble(db, body)
    report = run_analysis(channels, specimen, device, plan, exclusions)
    rec = repo.save_analysis(db, test.id, plan, exclusions, report)
    report["report_id"] = rec.id
    return {"id": rec.id, "summary": report["summary"],
            "unavailable": [r["label"] for r in report["results"] if not r["available"]],
            "warnings": report["warnings"]}


@app.get("/analyses/{analysis_id}")
def get_analysis(analysis_id: str, db: Session = Depends(db_session)):
    rec = db.get(AnalysisRecord, analysis_id)
    if rec is None:
        raise HTTPException(404, "分析报告不存在")
    rec.report["report_id"] = rec.id
    return rec.report


@app.get("/analyses/{analysis_id}/report")
def get_analysis_report(analysis_id: str, db: Session = Depends(db_session)):
    from fastapi.responses import PlainTextResponse

    rec = db.get(AnalysisRecord, analysis_id)
    if rec is None:
        raise HTTPException(404, "分析报告不存在")
    rec.report["report_id"] = rec.id
    md = render_markdown(rec.report)
    return PlainTextResponse(
        md, media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition":
                 f'attachment; filename="report-{analysis_id}.md"'})


@app.get("/analyses/by-test/{test_id}")
def list_by_test(test_id: str, db: Session = Depends(db_session)):
    rows = db.scalars(
        select(AnalysisRecord)
        .where(AnalysisRecord.test_id == test_id)
        .order_by(AnalysisRecord.created_at)).all()
    return [{"id": r.id, "summary": r.summary, "author": r.author,
             "created_at": r.created_at.isoformat(),
             "plan": r.plan, "excluded_points": r.excluded_points} for r in rows]


@app.get("/tests")
def list_tests(db: Session = Depends(db_session)):
    rows = db.scalars(select(TestRecord)).all()
    return [{"id": t.id, "test_code": t.test_code,
             "specimen_code": t.specimen.specimen_code} for t in rows]


@app.post("/demo/synthetic/{case}")
def demo_case(case: str, db: Session = Depends(db_session)):
    """直接在内存域上跑合成案例并落库，方便前端联调与核对。"""
    if case == "clear_yield":
        ch, _, _ = synthetic_clear_yield()
        spec = round_bar_specimen(lu=60.0, du=6.0)
    elif case == "no_clear_yield":
        ch, _, _ = synthetic_no_clear_yield()
        spec = round_bar_specimen(lu=61.0, du=7.0)
    elif case == "missing_dims":
        ch, _, _ = synthetic_clear_yield()
        spec = round_bar_specimen()
        spec.diameter_mm = None  # 尺寸缺失
    else:
        raise HTTPException(404, "未知合成案例")

    dev = default_device()
    # 落库（演示用：唯一编号带时间戳后缀）
    import time
    suffix = str(int(time.time() * 1000))[-8:]
    spec_r = SpecimenRecord(
        specimen_code=f"SYN-{case}-{suffix}", shape=spec.shape.value,
        geometry={"shape": spec.shape.value,
                  **{k: getattr(spec, k) for k in (
                      "diameter_mm", "width_mm", "thickness_mm", "gauge_length_mm",
                      "parallel_length_mm", "final_gauge_length_mm", "final_diameter_mm",
                      "final_width_mm", "final_thickness_mm")}})
    dev_r = DeviceRecord(params=dev.model_dump())
    db.add_all([spec_r, dev_r])
    db.flush()
    test_r = TestRecord(
        test_code=f"T-{case}-{suffix}", specimen_id=spec_r.id, device_id=dev_r.id,
        raw_signal={
            "time_s": list(ch.time_s), "force_n": list(ch.force_n),
            "crosshead_displacement_mm": list(ch.crosshead_displacement_mm),
            "extensometer_displacement_mm": [
                None if v is None else float(v)
                for v in ch.extensometer_displacement_mm],
            "extensometer_removed_at_index": ch.extensometer_removed_at_index,
        },
        channel_units={"force_internal_unit": "N",
                       "displacement_internal_unit": "mm"})
    db.add(test_r)
    db.flush()

    from backend.domain.models import AnalysisPlan
    plan = AnalysisPlan(
        name=f"demo-{case}",
        strain_source=StrainSource.EXTENSOMETER,
        elastic_index_min=4, elastic_index_max=10,
        min_elastic_points=5)
    report = run_analysis(ch, spec, dev, plan)
    rec = repo.save_analysis(db, test_r.id, plan, [], report)
    return {"test_id": test_r.id, "analysis_id": rec.id,
            "summary": report["summary"],
            "unavailable": [r["label"] for r in report["results"]
                            if not r["available"]],
            "warnings": report["warnings"]}
