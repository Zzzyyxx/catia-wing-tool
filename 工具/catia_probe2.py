"""CATIA 参数化机翼 —— 架构级探针（只验证接口通达性，不追求几何美观）。

验证目标（对应你截图里的设计树）：
  1. 参数：LENGTH / ANGLE / REAL / STRING 四种参数能否用代码创建
  2. 关系：展弦比的公式能否用代码写进去（引用其他参数名）
  3. 翼型库：几何图形集里放翼型闭合曲线
  4. 机翼：扫掠（Explicit Sweep）+ 对称
  5. 全部 update 通过

运行：
    $env:PYTHONIOENCODING="utf-8"
    C:\\Users\\lenovo\\anaconda3\\envs\\catia311\\python.exe catia_probe2.py
"""

import math
import sys
import time

import pycatia


def naca4(naca: str, n: int = 21):
    """生成 NACA 4 位翼型的归一化坐标（x: 0=后缘 … 1=前缘）。"""
    m = int(naca[0]) / 100.0
    p = int(naca[1]) / 10.0
    t = int(naca[2:]) / 100.0

    def yt(x):
        return 5 * t * (0.2969 * math.sqrt(x) - 0.1260 * x - 0.3516 * x**2
                        + 0.2843 * x**3 - 0.1015 * x**4)

    def yc(x):
        if x < p:
            return m / p**2 * (2 * p * x - x * x)
        return m / (1 - p) ** 2 * ((1 - 2 * p) + 2 * p * x - x * x)

    def dyc(x):
        if x < p:
            return 2 * m / p**2 * (p - x)
        return 2 * m / (1 - p) ** 2 * (p - x)

    xs = [0.5 * (1 - math.cos(math.pi * i / (n - 1))) for i in range(n)]
    upper, lower = [], []
    for x in xs:
        th = math.atan(dyc(x))
        xu, yu = x - yt(x) * math.sin(th), yc(x) + yt(x) * math.cos(th)
        xl, yl = x + yt(x) * math.sin(th), yc(x) - yt(x) * math.cos(th)
        upper.append((xu, yu))
        lower.append((xl, yl))
    # 顺序：后缘上 → 前缘 → 后缘下（一条闭合环）
    loop = list(reversed(upper)) + list(reversed(lower))[1:]
    return loop


def main() -> int:
    t0 = time.time()
    catia = pycatia.catia()
    catia.display_file_alerts = False
    doc = catia.documents.add("Part")
    part = doc.part
    print(f"[0] 新文档 {doc.name}", flush=True)

    # ---------- 1. 参数 ----------
    print("\n[1] 创建参数 ...", flush=True)
    params = part.parameters
    c_root = params.create_dimension("翼根弦长", "LENGTH", 100.0)
    b_span = params.create_dimension("翼展展长", "LENGTH", 500.0)
    sweep_ang = params.create_dimension("后掠角", "ANGLE", 30.0)
    twist = params.create_dimension("几何扭转", "ANGLE", 10.0)
    incidence = params.create_dimension("安装角", "ANGLE", 10.0)
    taper = params.create_real("梢根比", 0.45)
    ar = params.create_real("展弦比", 0.0)
    airfoil_name = params.create_string("翼型选择器", "NACA0018")

    for p in (c_root, b_span, sweep_ang, twist, incidence, taper, ar, airfoil_name):
        print(f"    {p.name:<10} = {p.value_as_string}", flush=True)

    # ---------- 2. 公式：展弦比 ----------
    print("\n[2] 写公式：展弦比 = b²/S（S 用解析式，不依赖测量）...", flush=True)
    expr = ("'翼展展长' * '翼展展长' / "
            "('翼根弦长' * '翼展展长' * (1 + '梢根比') / 2)")
    formula = part.relations.create_formula("展弦比公式", "由翼展与梯形面积推导", ar, expr)
    part.update()
    print(f"    展弦比 = {ar.value_as_string}  (解析值应为 {2*500/(100*1.45):.6f})", flush=True)

    # ---------- 3. 翼型库 ----------
    print("\n[3] 建翼型库几何图形集 + 翼型闭合曲线 ...", flush=True)
    lib = part.hybrid_bodies.add()
    lib.name = "翼型库"
    hsf = part.hybrid_shape_factory

    loop = naca4("0018", 21)
    pts = hsf.add_new_point_coords([[x * 100.0, 0.0, z * 100.0] for x, z in loop])
    foil = hsf.add_new_spline()
    for p in pts:
        foil.add_point(p)
    foil.set_closing(1)
    foil.name = "NACA0018"
    lib.append_hybrid_shape(foil)
    part.update()
    print(f"    翼型曲线 NACA0018：{len(pts)} 点，闭合", flush=True)

    # ---------- 4. 扫掠 ----------
    print("\n[4] 建扫掠（Explicit Sweep）：翼型沿后掠引导线 ...", flush=True)
    work = part.hybrid_bodies.add()
    work.name = "实现过程"

    tan_sweep = math.tan(math.radians(30.0))
    guide_pts = hsf.add_new_point_coords([
        [0.0, 0.0, 0.0],
        [tan_sweep * 250.0, 250.0, 0.0],
        [tan_sweep * 500.0, 500.0, 0.0],
    ])
    guide = hsf.add_new_spline()
    for p in guide_pts:
        guide.add_point(p)
    guide.name = "前缘后掠引导线"
    work.append_hybrid_shape(guide)
    part.update()

    foil_ref = part.create_reference_from_object(foil)
    guide_ref = part.create_reference_from_object(guide)
    sw = hsf.add_new_sweep_explicit(foil_ref, guide_ref)
    sw.name = "扫掠"
    work.append_hybrid_shape(sw)
    try:
        part.update()
        print("    扫掠 update 通过 ✔", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"    扫掠 update 失败（预期内，引导线方向需调）: {str(exc)[:120]}", flush=True)

    # ---------- 5. 对称 ----------
    print("\n[5] 建对称 ...", flush=True)
    wing = part.hybrid_bodies.add()
    wing.name = "机翼"
    plane_yz = part.origin_elements.plane_yz
    try:
        sym = hsf.add_new_symmetry(
            part.create_reference_from_object(sw),
            part.create_reference_from_object(plane_yz),
        )
        sym.name = "对称"
        wing.append_hybrid_shape(sym)
        part.update()
        print("    对称 OK ✔", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"    对称失败: {str(exc)[:160]}", flush=True)

    print(f"\n[6] 设计树顶层元素：", flush=True)
    for body in part.hybrid_bodies:
        print(f"    几何图形集: {body.name}", flush=True)
    print(f"    参数总数: {len(list(part.parameters))}", flush=True)
    print(f"    关系总数: {len(list(part.relations))}", flush=True)

    doc.close()
    print(f"\n[DONE] 总用时 {time.time() - t0:.1f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
