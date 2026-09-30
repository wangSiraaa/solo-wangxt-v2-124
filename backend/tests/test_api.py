"""API 冒烟测试：使用内存 SQLite，不依赖 PostgreSQL 进程。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
os.environ["LAB_DEMO_SQLITE"] = "1"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(scope="module")
def client():
    # 先置环境变量再导入应用，确保引擎选中内存 SQLite
    from backend.db import Base, engine
    from backend.main import app
    Base.metadata.create_all(engine)
    with TestClient(app) as c:
        yield c


def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


def test_synthetic_clear_yield_demo(client):
    r = client.post("/demo/synthetic/clear_yield")
    assert r.status_code == 200, r.text
    body = r.json()
    s = body["summary"]
    assert s["E_mpa"] is not None
    assert abs(s["E_mpa"] - 200_000) / 200_000 < 0.01
    assert abs(s["Rp0.2_mpa"] - 300) < 3
    assert s["Rm_mpa"]
    assert s["A_percent"] == 20.0

    rep = client.get(f"/analyses/{body['analysis_id']}").json()
    # 报告必须有来源
    e = next(x for x in rep["results"] if x["key"] == "E")
    assert e["formula"] and e["diagnostics"]["residual_mpa"]
    # 颈缩后真应力为 null
    m = rep["curve_limits"]["max_force_index"]
    assert all(v is None for v in rep["series"]["true_stress_mpa"][m + 1:])


def test_synthetic_missing_dims_demo(client):
    body = client.post("/demo/synthetic/missing_dims").json()
    assert body["summary"]["E_mpa"] is None
    assert body["summary"]["Rm_mpa"] is None
    assert body["unavailable"]
    rep = client.get(f"/analyses/{body['analysis_id']}").json()
    for item in rep["results"]:
        if item["key"] in ("E", "Rp0.2", "Rm"):
            assert item["available"] is False
            assert item["reason_if_unavailable"]


def test_unit_conversion_on_import(client):
    code = "ROUND-UNIT-1"
    client.post("/specimens", json={
        "specimen_code": code, "shape": "round",
        "diameter_mm": 10, "gauge_length_mm": 50})
    client.post("/devices", json={
        "machine_id": "M1", "load_cell_id": "LC",
        "extensometer_gauge_length_mm": 50})
    r = client.post("/tests/signals", json={
        "test_code": "T-UNIT-1", "specimen_code": code, "device_machine_id": "M1",
        "time_s": [0, 1], "force": [0, 1], "force_unit": "kN",
        "crosshead_displacement": [0, 1], "crosshead_displacement_unit": "mm",
        "extensometer_displacement": [0, 1],
        "extensometer_displacement_unit": "mm"})
    assert r.status_code == 200, r.text
    tid = r.json()["id"]
    # 1 kN → 1000 N
    from backend.db import SessionLocal, TestRecord
    with SessionLocal() as db:
        raw = db.get(TestRecord, tid).raw_signal
        assert raw["force_n"] == [0.0, 1000.0]


def test_exclusion_requires_reason(client):
    body = client.post("/demo/synthetic/clear_yield").json()
    r = client.post("/analyses/elastic-preview", json={
        "test_id": body["test_id"],
        "elastic_index_min": 4, "elastic_index_max": 10,
        "min_elastic_points": 5,
        "excluded_points": [{"index": 6, "reason": ""}]})
    assert r.status_code == 422
