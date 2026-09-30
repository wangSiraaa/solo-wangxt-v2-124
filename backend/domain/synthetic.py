"""合成试验数据：用于核对分析管线。

案例 A：理想线弹性段 + 明确屈服（0.2% 偏移可验证）+ 幂硬化 + 最大力后软化。
案例 B：连续硬化、无清晰屈服平台（偏移交点仍可能存在，但上/下屈服应判不可得）。
"""
from __future__ import annotations

import numpy as np

from .models import (
    DeviceParams,
    SignalChannels,
    SpecimenGeometry,
    SpecimenShape,
    StrainSource,
)

E_TRUE_MPA = 200_000.0
SY_TRUE_MPA = 300.0
S0_MM2 = 78.53981633974483  # d0=10 mm
L0_MM = 50.0
LE_MM = 50.0


def round_bar_specimen(d0: float = 10.0, l0: float = 50.0,
                       lu: float | None = None,
                       du: float | None = None) -> SpecimenGeometry:
    return SpecimenGeometry(
        specimen_id="SYN-001", shape=SpecimenShape.ROUND,
        diameter_mm=d0, gauge_length_mm=l0,
        final_gauge_length_mm=lu, final_diameter_mm=du)


def default_device() -> DeviceParams:
    return DeviceParams(
        machine_id="UTM-01", load_cell_id="LC-100kN",
        load_cell_capacity_n=100_000.0, load_cell_class="0.5",
        extensometer_id="EXT-50", extensometer_gauge_length_mm=LE_MM,
        extensometer_class="1", sampling_rate_hz=100.0,
        crosshead_compliance_mm_per_n=0.0)


def _channels_from_stress_strain(eps: np.ndarray, sig: np.ndarray,
                                 remove_ext_at: int | None = None
                                 ) -> SignalChannels:
    force = sig * S0_MM2
    disp_ext = eps * LE_MM
    disp_cross = eps * L0_MM  # 合成数据两通道一致，真实情况不会
    ext_list: list[float | None] = disp_ext.tolist()
    if remove_ext_at is not None:
        for i in range(remove_ext_at + 1, len(ext_list)):
            ext_list[i] = None
    t = np.arange(len(eps)) / 100.0
    return SignalChannels(
        time_s=t.tolist(),
        force_n=force.tolist(),
        crosshead_displacement_mm=disp_cross.tolist(),
        extensometer_displacement_mm=ext_list,
        extensometer_removed_at_index=remove_ext_at)


def synthetic_clear_yield(n: int = 600, noise_mpa: float = 0.0
                          ) -> tuple[SignalChannels, np.ndarray, np.ndarray]:
    """弹性段斜率 E（至 300 MPa）；随后 0.5% 屈服平台；再幂硬化；
    最大力（约 ε=0.05）后软化模拟颈缩，末端载荷跌落。"""
    eps = np.linspace(0.0, 0.08, n)
    ey = SY_TRUE_MPA / E_TRUE_MPA          # 0.0015
    plateau_end = ey + 0.005               # 0.0065
    ep = np.maximum(eps - plateau_end, 0.0)  # 平台后塑性应变
    sig = np.where(
        eps <= ey,
        E_TRUE_MPA * eps,
        np.where(
            eps <= plateau_end,
            SY_TRUE_MPA,
            SY_TRUE_MPA + 600.0 * (1.0 - np.exp(-120.0 * ep)),
        ),
    )
    neck_start = int(0.62 * n)
    tail = np.linspace(0.0, 1.0, n - neck_start)
    sig[neck_start:] = sig[neck_start] * (1.0 - 0.35 * tail)
    sig[-5:] *= np.linspace(0.9, 0.02, 5)
    if noise_mpa:
        sig = sig + np.random.default_rng(0).normal(0, noise_mpa, n)
    return _channels_from_stress_strain(eps, sig), eps, sig


def synthetic_no_clear_yield(n: int = 600) -> tuple[SignalChannels, np.ndarray, np.ndarray]:
    """连续硬化、无屈服平台：初始 0.2% 严格线弹性（E=200 GPa），
    其后光滑过渡到硬化，没有载荷下降/平直段；最大力后软化。"""
    eps = np.linspace(0.0, 0.08, n)
    eps1 = 0.002                      # 线性段终点，σ1 = 400 MPa
    sig1 = E_TRUE_MPA * eps1
    b = 350.0                         # 硬化渐近增量
    tau = b / E_TRUE_MPA              # 保证过渡点导数 = E
    sig = np.where(
        eps <= eps1,
        E_TRUE_MPA * eps,
        sig1 + b * (1.0 - np.exp(-(eps - eps1) / tau)),
    )
    neck_start = int(0.8 * n)
    tail = np.linspace(0.0, 1.0, n - neck_start)
    sig[neck_start:] = sig[neck_start] * (1.0 - 0.3 * tail)
    sig[-5:] *= np.linspace(0.9, 0.02, 5)
    return _channels_from_stress_strain(eps, sig), eps, sig
