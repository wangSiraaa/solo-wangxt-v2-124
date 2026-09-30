"""持久化与领域对象之间的装配函数。"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.domain import units
from backend.domain.models import (
    AnalysisPlan,
    DeviceParams,
    ExcludedPoint,
    SignalChannels,
    SpecimenGeometry,
    SpecimenShape,
)

from .db import AnalysisRecord, DeviceRecord, SpecimenRecord, TestRecord


def spec_to_domain(rec: SpecimenRecord) -> SpecimenGeometry:
    g = rec.geometry
    return SpecimenGeometry(
        specimen_id=rec.specimen_code,
        shape=SpecimenShape(g["shape"]),
        diameter_mm=g.get("diameter_mm"),
        width_mm=g.get("width_mm"),
        thickness_mm=g.get("thickness_mm"),
        gauge_length_mm=g["gauge_length_mm"],
        parallel_length_mm=g.get("parallel_length_mm"),
        final_gauge_length_mm=g.get("final_gauge_length_mm"),
        final_diameter_mm=g.get("final_diameter_mm"),
        final_width_mm=g.get("final_width_mm"),
        final_thickness_mm=g.get("final_thickness_mm"),
    )


def device_to_domain(rec: DeviceRecord) -> DeviceParams:
    p = rec.params
    return DeviceParams(**p)


def signal_to_domain(rec: TestRecord) -> SignalChannels:
    s = rec.raw_signal
    return SignalChannels(
        time_s=s["time_s"],
        force_n=s["force_n"],
        crosshead_displacement_mm=s["crosshead_displacement_mm"],
        extensometer_displacement_mm=s["extensometer_displacement_mm"],
        extensometer_removed_at_index=s.get("extensometer_removed_at_index"),
    )


def convert_signal(payload: dict) -> tuple[dict, dict]:
    """把携带原始单位的入站信号换算为内部单位(N, mm)。

    返回 (raw_signal_internal, channel_units)；夹具位移与引伸计位移
    始终是两个独立键，不允许同列。
    """
    n = len(payload["time_s"])
    for key in ("force", "crosshead_displacement", "extensometer_displacement"):
        if len(payload[key]) != n:
            raise ValueError(f"通道 {key} 长度与 time_s 不一致")

    force_n = [units.force_to_newton(float(v), payload["force_unit"])
               for v in payload["force"]]
    cross_mm = [units.length_to_mm(float(v), payload["crosshead_displacement_unit"])
                for v in payload["crosshead_displacement"]]
    ext_mm: list[float | None] = [
        None if v is None
        else units.length_to_mm(float(v), payload["extensometer_displacement_unit"])
        for v in payload["extensometer_displacement"]]

    raw = {
        "time_s": list(map(float, payload["time_s"])),
        "force_n": force_n,
        "crosshead_displacement_mm": cross_mm,
        "extensometer_displacement_mm": ext_mm,
        "extensometer_removed_at_index": payload.get("extensometer_removed_at_index"),
    }
    units_meta = {
        "time": "s",
        "force_original_unit": payload["force_unit"],
        "force_internal_unit": "N",
        "crosshead_displacement_original_unit": payload["crosshead_displacement_unit"],
        "extensometer_displacement_original_unit": payload["extensometer_displacement_unit"],
        "displacement_internal_unit": "mm",
        "note": "夹具位移与引伸计位移独立成列，禁止混用",
    }
    return raw, units_meta


def plan_from_payload(p: dict) -> AnalysisPlan:
    return AnalysisPlan(**{k: v for k, v in p.items()
                           if k in AnalysisPlan.model_fields})


def exclusions_from_payload(items: list[dict]) -> list[ExcludedPoint]:
    return [ExcludedPoint(**x) for x in items]


# ---- 查询辅助 ----

def get_specimen(db: Session, code: str) -> SpecimenRecord | None:
    return db.scalar(select(SpecimenRecord)
                     .where(SpecimenRecord.specimen_code == code))


def get_device(db: Session, machine_id: str) -> DeviceRecord | None:
    # params 是 JSONB；不同方言写法不同，简单做法是取候选后在 Python 端过滤
    for rec in db.scalars(select(DeviceRecord)).all():
        if rec.params.get("machine_id") == machine_id:
            return rec
    return None


def get_test(db: Session, test_id: str) -> TestRecord | None:
    return db.get(TestRecord, test_id)


def save_analysis(db: Session, test_id: str, plan: AnalysisPlan,
                  exclusions: list[ExcludedPoint], report: dict) -> AnalysisRecord:
    rec = AnalysisRecord(
        test_id=test_id,
        plan=plan.model_dump(mode="json"),
        excluded_points=[{
            "index": e.index, "reason": e.reason, "author": e.author,
            "created_at": e.created_at.isoformat(),
        } for e in exclusions],
        report=report,
        summary=report["summary"],
        author=plan.author,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec
