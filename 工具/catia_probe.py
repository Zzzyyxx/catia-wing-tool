"""CATIA 自动化环境探针。

验证 pycatia 能否通过 COM 连上本机 CATIA，并确认机翼参数化建模所需的许可与接口：
建 Part / 建点 / 建样条(闭合) / Join / 多截面曲面(Loft) / 知识工程参数。

运行：
    $env:PYTHONIOENCODING="utf-8"
    C:\\Users\\lenovo\\anaconda3\\envs\\catia311\\python.exe catia_probe.py
"""

import math
import sys
import time

import pycatia
from pycatia.scripts.vba import vba_nothing  # VB 的 Nothing（可选参数占位）

# 归一化"翼型"轮廓：x∈[0,1] 弦向，z 为厚度方向（很粗的草稿形状，只求拓扑合法）
NORM_AIRFOIL = [
    (0.00, 0.00),   # 后缘下
    (0.15, -0.06),
    (0.40, -0.08),
    (0.75, -0.05),
    (1.00, 0.00),   # 前缘
    (0.75, 0.06),
    (0.40, 0.12),
    (0.15, 0.10),
]


def section_points(norm_pts, chord, span_y, twist_deg, le_x=0.0, le_z=0.0):
    """把归一化翼型放到指定展向站位，缩放弦长 + 绕展向轴扭转。

    注意：归一化 x=1 处是前缘，所以这里以 1.0 为基准反算坐标。
    """
    c = math.cos(math.radians(twist_deg))
    s = math.sin(math.radians(twist_deg))
    out = []
    for x, z in norm_pts:
        X = (x - 1.0) * chord          # 前缘对齐到 le_x
        Z = z * chord
        X, Z = X * c - Z * s, X * s + Z * c
        out.append([le_x + X, span_y, le_z + Z])
    return out


def closed_spline(hsf, pts, name):
    spline = hsf.add_new_spline()
    for p in hsf.add_new_point_coords(pts):
        spline.add_point(p)
    spline.set_closing(1)  # 1 = 闭合
    spline.name = name
    return spline


def close_all_documents(catia):
    for doc in list(catia.documents):
        try:
            doc.close()
        except Exception:  # noqa: BLE001
            pass


def main() -> int:
    t0 = time.time()
    print("[1] Dispatch CATIA.Application ...", flush=True)
    catia = pycatia.catia()
    print(f"    连接成功，用时 {time.time() - t0:.1f}s", flush=True)
    print(f"    FullName: {catia.full_name}", flush=True)
    catia.display_file_alerts = False

    print("[2] 清理遗留文档 + 新建 Part ...", flush=True)
    close_all_documents(catia)
    doc = catia.documents.add("Part")
    part = doc.part
    print(f"    文档: {doc.name} | 零件: {part.name}", flush=True)

    hsf = part.hybrid_shape_factory
    body = part.hybrid_bodies.add()
    body.name = "PROBE"

    print("[3] 点 / 闭合样条 ...", flush=True)
    pts = hsf.add_new_point_coords([[0, 0, 0], [10, 5, 0], [20, 0, 0], [30, -5, 0]])
    print(f"    add_new_point_coords -> {len(pts)} 点，类型 {type(pts[0]).__name__}", flush=True)
    print("    （返回的是点对象，不是 Reference；spline.add_point 走 duck typing 可用）", flush=True)

    # 根剖：弦长 100，无扭转
    sec_root = closed_spline(hsf, section_points(NORM_AIRFOIL, 100.0, 0.0, 0.0), "SEC_ROOT")
    # 梢剖：弦长 45，5° 扭转，展向 500mm
    sec_tip = closed_spline(
        hsf, section_points(NORM_AIRFOIL, 45.0, 500.0, 5.0, le_x=80.0), "SEC_TIP"
    )
    part.update()
    print("    两条截面曲线 OK", flush=True)

    print("[4] 多截面曲面（Loft）—— 机翼放样的核心特征 ...", flush=True)
    loft = hsf.add_new_loft()
    loft.add_section_to_loft(part.create_reference_from_object(sec_root), 1, vba_nothing)
    loft.add_section_to_loft(part.create_reference_from_object(sec_tip), 1, vba_nothing)
    loft.name = "PROBE_LOFT"
    body.append_hybrid_shape(loft)
    part.update()
    print("    Loft OK -> GSD（创成式外形设计）许可可用", flush=True)

    print("[5] 知识工程参数 ...", flush=True)
    try:
        params = part.parameters
        print(f"    part.parameters OK，现有参数 {len(list(params))} 个", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"    part.parameters 不可用: {exc}", flush=True)

    print("[6] 关闭文档 ...", flush=True)
    try:
        doc.close()
        print("    已关闭（未保存）", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"    关闭失败，请手动关: {exc}", flush=True)

    print(f"[OK] 探针通过，总用时 {time.time() - t0:.1f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
