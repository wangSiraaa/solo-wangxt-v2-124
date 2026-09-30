"""单位约定与换算。

系统内部统一约定：
- 力:        N
- 长度/尺寸: mm（面积 mm^2；N/mm^2 与 MPa 数值相同，1 N/mm^2 = 1 MPa）
- 应力:      MPa
- 应变:      无量纲（工程应变/真应变，小数表示），UI 层可按 % 展示
- 位移:      mm
"""
from __future__ import annotations

# 力换算到 N
FORCE_TO_N = {
    "N": 1.0,
    "kN": 1000.0,
    "lbf": 4.4482216152605,
}

# 长度换算到 mm
LENGTH_TO_MM = {
    "mm": 1.0,
    "m": 1000.0,
    "in": 25.4,
}

# 应变展示：内部为无量纲小数
STRAIN_STYLE = {
    "ratio": 1.0,        # 0.002
    "percent": 100.0,    # 0.2 %
}

# 0.2% 偏移量（无量纲应变）
OFFSET_0P2 = 0.002


def force_to_newton(value: float, unit: str) -> float:
    try:
        return value * FORCE_TO_N[unit]
    except KeyError as exc:
        raise ValueError(f"不支持的力单位: {unit!r}，支持: {sorted(FORCE_TO_N)}") from exc


def length_to_mm(value: float, unit: str) -> float:
    try:
        return value * LENGTH_TO_MM[unit]
    except KeyError as exc:
        raise ValueError(f"不支持的长度单位: {unit!r}，支持: {sorted(LENGTH_TO_MM)}") from exc
