"""机翼参数化建模生成器（CATIA V5 + pycatia）。

两种建模方式：

  --method loft  （默认，推荐）沿展向布置 N 个"真实截面"——每个截面
                 独立计算弦长、1/4 弦后掠、安装角、几何扭转，然后用
                 **多截面曲面** 串起来。几何精确，适合下游仿真。

  --method sweep 单个翼型 + 双引导线 + 脊线的显式扫掠（贴近手工做法，
                 但 CATIA 的扫掠无法用接口驱动扭转，见文档）。

生成的设计树：

    参数
      ├ 翼型选择器  (String)          ← 输入文件名
      ├ 翼根弦长 / 翼展展长 (Length)
      ├ 后掠角 / 几何扭转 / 安装角 (Angle，后掠为 1/4 弦线口径)
      ├ 梢根比 (Real)
      └ 展弦比 (Real, 公式 = b²/梯形半翼面积/2)
    关系
      ├ 展弦比公式 / 翼型缩放公式 / 引导线端点坐标公式
    翼型库      ← 以输入文件命名的草图 + 缩放
    实现过程    ← 各展向截面曲线（loft 模式）/ 引导线 + 脊线（sweep 模式）
    机翼        ← 多截面曲面（或扫掠）+ 对称

用法：
    python wing_builder.py                       # 交互输入
    python wing_builder.py --config cfg.json
    python wing_builder.py --dry-run             # 只打印参数
    python wing_builder.py --method sweep        # 换成扫掠方案
单位：CATIA 内部单位 mm / deg。
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from pycatia.scripts.vba import vba_nothing

# ----------------------------------------------------------------------------
# 参数
# ----------------------------------------------------------------------------


@dataclass
class WingParams:
    airfoil_file: str
    root_chord: float = 100.0      # 翼根弦长 mm
    span: float = 500.0            # 翼展展长 mm（全长，含对称）
    sweep_quarter: float = 30.0    # 后掠角 deg（1/4 弦线）
    twist: float = 10.0            # 几何扭转 deg（根→梢）
    taper: float = 0.45            # 梢根比
    incidence: float = 10.0        # 安装角 deg（根部）
    stations: int = 7              # 展向截面数（loft 模式）
    live: bool = True              # True=参数化截面（缩放/旋转/平移全挂公式，CATIA 内改参数即更新）
    method: str = "loft"           # loft | sweep
    ribs: bool = False             # 是否生成翼肋（等间距平面阵列 ∩ 翼面）
    rib_spacing: float = 20.0      # 翼肋间距 mm
    rib_slice: bool = False        # True=用"平面 ∩ 翼面"切片（CAD 原生做法，可能空切失败）
    solid: bool = False            # 是否实体化（封口→接合→封闭曲面；无实体许可则保留水密壳体）
    thickness: float = 2.0         # 加厚厚度 mm（仅当 CATIA 授权「加厚曲面」时用）
    ar_mode: str = "analytic"      # analytic（理论式）| measured（对齐 UP 主的测量式）
    half_wing: bool = True
    # ---- OpenVSP 风格：对称 + XYZ 旋转 + XYZ 平移（均为公式驱动，CATIA 内改即更新）----
    symmetric: bool = True         # 是否生成镜像（半翼建模时用）
    rot_x: float = 0.0             # 绕 X 轴（顺气流）旋转 deg
    rot_y: float = 0.0             # 绕 Y 轴（展向）旋转 deg
    rot_z: float = 0.0             # 绕 Z 轴（竖直）旋转 deg
    trans_x: float = 0.0           # 平移 X mm
    trans_y: float = 0.0           # 平移 Y mm
    trans_z: float = 0.0           # 平移 Z mm
    save_path: str = ""

    def derived(self) -> dict:
        b = self.span
        half = b / 2.0
        c_root = self.root_chord
        lam = self.taper
        c_tip = c_root * lam
        s_half = (c_root + c_tip) / 2.0 * half
        area = 2 * s_half
        ar = b * b / area if area else float("nan")
        tan_sweep = math.tan(math.radians(self.sweep_quarter))
        x_q_root = 0.25 * c_root
        return {
            "c_tip": c_tip,
            "half_span": half,
            "s_half": s_half,
            "area": area,
            "aspect_ratio": ar,
            "x_le_root": 0.0,
            "x_le_tip": x_q_root + half * tan_sweep - 0.25 * c_tip,
            "x_te_root": c_root,
            "x_te_tip": x_q_root + half * tan_sweep + 0.75 * c_tip,
        }

    # 站位的展向位置：0 → half_span
    def as_brief(self) -> str:
        """一句话参数快照，用于错误信息。"""
        return (f"翼型={Path(self.airfoil_file).name}, c_root={self.root_chord}, "
                f"b={self.span}, Λ¼={self.sweep_quarter}°, λ={self.taper}, "
                f"i={self.incidence}°, twist={self.twist}°, "
                f"截面数={self.stations}, method={self.method}, live={self.live}, ribs={self.ribs}, solid={self.solid}, "
                f"sym={self.symmetric}, rot=({self.rot_x},{self.rot_y},{self.rot_z}), "
                f"trans=({self.trans_x},{self.trans_y},{self.trans_z})"
                + (f"/{self.rib_spacing}mm" if self.ribs else ""))

    def station_y(self, i: int) -> float:
        """第 i 个截面的展向位置，0 → 半展长。"""
        half = self.derived()["half_span"]
        if self.stations <= 1:
            return 0.0
        return half * i / (self.stations - 1)

    def at_station(self, y: float) -> tuple[float, float, float]:
        """返回该站位的 (弦长, 前缘 x, 扭转角)。"""
        d = self.derived()
        half = d["half_span"]
        frac = 0.0 if half == 0 else y / half
        c = self.root_chord + (d["c_tip"] - self.root_chord) * frac
        x_q = 0.25 * self.root_chord + y * math.tan(math.radians(self.sweep_quarter))
        x_le = x_q - 0.25 * c
        theta = self.incidence + self.twist * frac
        return c, x_le, theta


# ----------------------------------------------------------------------------
# 错误类型
# ----------------------------------------------------------------------------


class BuildError(RuntimeError):
    """带阶段定位的建模失败。CATIA 的 COMError 不告诉你哪个特征坏了，
    所以我们在每个阶段外面包一层，把阶段名 + 参数快照一起抛出去。"""

    HINTS = {
        "[3] 翼型库（草图）": "翼型文件解析问题：检查 .dat 的列格式（XFLR5 是三列 x/0/z）、"
                             "是否有足够点数、厚度是否为 0。",
        "[4-5] 截面与多截面曲面": "截面几何不合法：截面数太少(建议 ≥3)、"
                                 "后掠/扭转过大导致相邻截面自交，或翼型点序混乱。",
        "[6] 对称与姿态": "旋转轴/平移方向创建失败；把旋转角与平移都设为 0 再试。",
        "[6] 实体化": "封口/接合失败：截面曲线不闭合，或本机无实体许可（会保留水密壳体）。",
        "[7] 翼肋": "翼肋平面偏移方向或间距不合适；可把间距调大再试。",
        "[9] 最终 update": "通常是前面某步留下的坏特征。看日志里最后一次成功的位置。",
        "[2] 参数与公式": "参数/公式创建失败：名称重复或单位不合法。",
    }

    def __init__(self, stage: str, cause: Exception, params: "WingParams"):
        self.stage = stage
        self.cause = cause
        self.params = params
        hint = self.HINTS.get(stage, "查看日志中最后成功的一步。")
        super().__init__(
            f"阶段「{stage}」失败\n"
            f"原因：{cause}\n"
            f"提示：{hint}\n"
            f"参数：{params.as_brief()}"
        )


# ----------------------------------------------------------------------------
# 翼型解析
# ----------------------------------------------------------------------------


def parse_airfoil(path: Path) -> list[tuple[float, float]]:
    """读翼型 .dat → [(xi, eta)]，xi=0 前缘、1 后缘。

    兼容：
      - 分隔符：Tab / 空格 / 逗号 / 分号 / 竖线
      - 表头与注释行（非数字行自动跳过）
      - **XFLR5 三列格式**（``x  0  z``）——真实厚度在第三列，第二列恒为 0
      - 带单位坐标（弦长 > 1.5 自动归一化）
      - 首尾重复点、连续重复点
      - "蝴蝶结"点序（上表面 LE→TE 之后再下表面 LE→TE），自动重排成单环
    """
    rows: list[list[float]] = []
    for line in path.read_text(encoding="utf-8-sig", errors="ignore").splitlines():
        cleaned = line.strip()
        if not cleaned:
            continue
        for sep in ("\t", ",", ";", "|"):
            cleaned = cleaned.replace(sep, " ")
        parts = cleaned.split()
        if len(parts) < 2:
            continue
        nums: list[float] = []
        for tok in parts:
            try:
                nums.append(float(tok))
            except ValueError:
                nums = []          # 该行含文字 → 视为表头
                break
        if len(nums) >= 2:
            rows.append(nums)

    if len(rows) < 4:
        raise ValueError(f"{path.name}: 有效坐标行不足（{len(rows)} 行）")

    # ---- 判断哪两列是 (弦向, 厚度) ----
    ncol = min(len(r) for r in rows)
    if ncol >= 3:
        col1 = [r[1] for r in rows]
        col2 = [r[2] for r in rows]
        span1 = max(col1) - min(col1)
        span2 = max(col2) - min(col2)
        # XFLR5 风格：第二列恒定、第三列有起伏 → 用 (col0, col2)
        if span1 < 1e-9 and span2 > 1e-9:
            pairs = [(r[0], r[2]) for r in rows]
            print(f"    ! 检测到 XFLR5 三列格式（x / 0 / z），已取第 1、3 列")
        else:
            pairs = [(r[0], r[1]) for r in rows]
    else:
        pairs = [(r[0], r[1]) for r in rows]

    # ---- 归一化 ----
    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]
    x_min, x_max = min(xs), max(xs)
    chord_len = x_max - x_min
    if chord_len <= 1e-12:
        raise ValueError(f"{path.name}: 弦向坐标没有跨度，不是翼型文件")

    thick = max(ys) - min(ys)
    if thick <= 1e-9:
        raise ValueError(
            f"{path.name}: 厚度坐标全为 0 —— 可能列选错了（若是 XFLR5 三列格式请检查中间列）"
        )

    scale = 1.0 / chord_len if chord_len > 1.5 else 1.0
    if scale != 1.0:
        print(f"    ! 坐标带单位（弦长 {chord_len:.1f}），已归一化")

    pts = [((x - x_min) * scale, y * scale) for x, y in pairs]

    # ---- 去重 + 重排成单环 ----
    dedup: list[tuple[float, float]] = []
    for p in pts:
        if not dedup or not _close(dedup[-1], p):
            dedup.append(p)
    pts = dedup
    while len(pts) > 4 and _close(pts[0], pts[-1]):
        pts.pop()

    return _order_loop(pts, path.name)


def _order_loop(pts: list[tuple[float, float]], name: str = "") -> list[tuple[float, float]]:
    """把点序整理成"一个环"：从后缘上表面 → 前缘 → 后缘下表面。

    正常文件本来就是单环（x 先单调减到前缘、再单调增回后缘）；
    若是"上表面 LE→TE、下表面 LE→TE"的蝴蝶结写法，则反转前半段。
    """
    if len(pts) < 4:
        return pts
    i_le = min(range(len(pts)), key=lambda i: pts[i][0])
    first, second = pts[: i_le + 1], pts[i_le:]

    def is_desc(seq):
        return all(seq[i][0] >= seq[i + 1][0] - 1e-9 for i in range(len(seq) - 1))

    def is_asc(seq):
        return all(seq[i][0] <= seq[i + 1][0] + 1e-9 for i in range(len(seq) - 1))

    if is_desc(first) and is_asc(second):
        return pts                       # 已经是单环
    if is_asc(first) and is_asc(second):
        if name:
            print(f"    ! {name}: 检测到'蝴蝶结'点序，已重排成单环")
        return list(reversed(first)) + second[1:]
    return pts


def _close(a, b, tol: float = 1e-9) -> bool:
    return abs(a[0] - b[0]) < tol and abs(a[1] - b[1]) < tol


# ----------------------------------------------------------------------------
# 截面几何（纯数学，不依赖 CATIA）
# ----------------------------------------------------------------------------


def section_points(
    norm_pts: list[tuple[float, float]],
    chord: float,
    x_le: float,
    y: float,
    theta_deg: float,
) -> list[list[float]]:
    """归一化翼型 → 指定站位：缩放 → 绕展向轴(Y)旋转 → 平移到 (x_le, y, 0)。"""
    th = math.radians(theta_deg)
    c, s = math.cos(th), math.sin(th)
    out = []
    for xi, eta in norm_pts:
        X = xi * chord        # 弦向（xi=0 前缘 … 1 后缘）
        Z = eta * chord       # 厚度方向
        # 绕 +Y 轴旋转，符号取反 → 正安装角 = 前缘抬升（抬头）
        Xr = X * c + Z * s
        Zr = -X * s + Z * c
        out.append([x_le + Xr, y, Zr])
    return out


# ----------------------------------------------------------------------------
# 交互输入
# ----------------------------------------------------------------------------

PROMPTS = [
    ("airfoil_file", "翼型 .dat 文件路径", None),
    ("root_chord", "翼根弦长 [mm]", 100.0),
    ("span", "翼展展长 [mm]", 500.0),
    ("sweep_quarter", "后掠角 [deg, 1/4 弦线]", 30.0),
    ("twist", "几何扭转 [deg, 根→梢]", 10.0),
    ("taper", "梢根比", 0.45),
    ("incidence", "安装角 [deg]", 10.0),
    ("stations", "展向截面数", 7),
]


def prompt_params() -> WingParams:
    print("=" * 62)
    print(" 机翼参数化建模 —— 回车使用默认值")
    print("=" * 62)
    values: dict = {}
    for key, label, default in PROMPTS:
        while True:
            hint = f" ({default})" if default is not None else ""
            raw = input(f"{label}{hint}: ").strip().strip('"').strip("'")
            if not raw:
                if default is None:
                    print("  ! 必填")
                    continue
                values[key] = default
                break
            if default is None:
                values[key] = raw
                break
            try:
                values[key] = int(raw) if key == "stations" else float(raw)
                break
            except ValueError:
                print("  ! 请输入数字")
    values["save_path"] = input("保存路径（留空不保存）: ").strip().strip('"')
    return WingParams(**values)


# ----------------------------------------------------------------------------
# CATIA
# ----------------------------------------------------------------------------


class WingBuilder:
    def __init__(self, params: WingParams):
        self.p = params
        self.d = params.derived()

    # -- 工具 -----------------------------------------------------------
    def _formula(self, name: str, out_param, body: str) -> None:
        """CATIA 公式要求参数名用反引号，否则静默失效。"""
        self.part.relations.create_formula(name, "", out_param, body)
        print(f"    公式 {name}")

    def _ref(self, obj):
        return self.part.create_reference_from_object(obj)

    def _closed_spline(self, pts, name):
        sp = self.hsf.add_new_spline()
        for p in self.hsf.add_new_point_coords(pts):
            sp.add_point(p)
        sp.set_closing(1)
        sp.name = name
        return sp

    # -- 主流程 ---------------------------------------------------------
    def _stage(self, title: str, fn):
        """执行一个阶段；失败时抛出带阶段名的 BuildError，方便定位。"""
        print(f"\n{title} ...")
        try:
            return fn()
        except BuildError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise BuildError(title, exc, self.p) from exc

    def build(self):
        import pycatia

        p = self.p
        catia = pycatia.catia()
        catia.display_file_alerts = False

        print("\n[1] 新建零件文档 ...")
        self.doc = catia.documents.add("Part")
        self.part = self.doc.part
        self.hsf = self.part.hybrid_shape_factory
        print(f"    {self.doc.name}")

        self._stage("[2] 参数与公式", self._parameters)
        self._stage("[3] 翼型库（草图）", self._airfoil_library)
        if p.method == "loft":
            self._stage("[4-5] 截面与多截面曲面",
                        self._loft_wing_live if p.live else self._loft_wing)
        else:
            self._stage("[4-5] 引导线与扫掠", self._sweep_wing)
        self._stage("[6] 实体化", self._solidify)
        if p.ribs:
            self._stage("[7] 翼肋", self._ribs)
        self._stage("[8] 对称与姿态", self._transforms)
        self._stage("[9] 最终 update", self.part.update)

        print("    OK")
        self._report()

        if p.ar_mode == "measured":
            self._fill_measured_aspect_ratio()

        if p.save_path:
            target = Path(p.save_path).resolve()   # 相对路径按当前工作目录解析
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.suffix.lower() != ".catpart":
                target = target.with_suffix(".CATPart")
            try:
                self.doc.save_as(target, overwrite=True)
            except Exception as exc:  # noqa: BLE001
                # CATIA 的 SaveAs 对中文/特殊字符路径不友好 → 先存临时文件再拷回去
                import shutil
                import tempfile
                tmp = Path(tempfile.gettempdir()) / "_wing_builder_tmp.CATPart"
                print(f"    ! 直接保存失败（{str(exc)[:60]}），改用临时文件中转 …")
                self.doc.save_as(tmp, overwrite=True)
                shutil.copyfile(tmp, target)
            print(f"\n已保存: {target}")

    # -- 参数 -----------------------------------------------------------
    def _parameters(self):
        p, d = self.p, self.d
        print("\n[2] 参数 ...")
        ps = self.part.parameters
        self.q_airfoil = ps.create_string("翼型选择器", Path(p.airfoil_file).stem)
        self.q_chord = ps.create_dimension("翼根弦长", "LENGTH", p.root_chord)
        self.q_span = ps.create_dimension("翼展展长", "LENGTH", p.span)
        self.q_sweep = ps.create_dimension("后掠角", "ANGLE", p.sweep_quarter)
        self.q_twist = ps.create_dimension("几何扭转", "ANGLE", p.twist)
        self.q_taper = ps.create_real("梢根比", p.taper)
        self.q_ar = ps.create_real("展弦比", d["aspect_ratio"])
        self.q_inc = ps.create_dimension("安装角", "ANGLE", p.incidence)

        # ---- OpenVSP 风格：对称 + XYZ 旋转 + XYZ 平移 ----
        self.q_sym = ps.create_boolean("对称开关", bool(p.symmetric))
        self.q_rx = ps.create_dimension("绕X旋转", "ANGLE", p.rot_x)
        self.q_ry = ps.create_dimension("绕Y旋转", "ANGLE", p.rot_y)
        self.q_rz = ps.create_dimension("绕Z旋转", "ANGLE", p.rot_z)
        self.q_tx = ps.create_dimension("平移X", "LENGTH", p.trans_x)
        self.q_ty = ps.create_dimension("平移Y", "LENGTH", p.trans_y)
        self.q_tz = ps.create_dimension("平移Z", "LENGTH", p.trans_z)

        for o in (self.q_airfoil, self.q_chord, self.q_span, self.q_sweep,
                  self.q_twist, self.q_taper, self.q_inc,
                  self.q_rx, self.q_ry, self.q_rz, self.q_tx, self.q_ty, self.q_tz):
            print(f"    {o.name:<12} = {o.value_as_string()}")
        print(f"    {self.q_sym.name:<12} = {bool(self.q_sym.value)}")

        # 展弦比 = b² / (2 · 梯形半翼面积)
        # analytic：解析式（与理论一致，不依赖测量特征）
        # measured：对齐 UP 主的做法（b²/(测量面积×2)），实测面积在建模完成后回填
        if p.ar_mode == "analytic":
            body = ("`翼展展长`*`翼展展长`/"
                    "(2*(`翼根弦长`+`梢根比`*`翼根弦长`)/2*`翼展展长`/2)")
            self._formula("展弦比公式", self.q_ar, body)
            self.part.update()
            print(f"    展弦比 = {self.q_ar.value}  (理论 {d['aspect_ratio']:.6f})")
        else:
            print("    展弦比：measured 模式，建模完成后按实测翼面面积回填")

    # -- 翼型库 ---------------------------------------------------------
    def _airfoil_library(self):
        p = self.p
        print("\n[3] 翼型库（草图）...")
        lib = self.part.hybrid_bodies.add()
        lib.name = "翼型库"

        af = Path(p.airfoil_file)
        self.norm_pts = parse_airfoil(af)
        stem = af.stem
        print(f"    {af.name} → 草图 '{stem}'，{len(self.norm_pts)} 点")

        plane = self.part.origin_elements.plane_zx   # 法向 Y
        sk = lib.hybrid_sketches.add(self._ref(plane))
        sk.name = stem
        f2d = sk.open_edition()
        # plane_zx 局部轴：H→全局 Z（厚度），V→全局 X（弦向）
        poles = [f2d.create_point(eta, xi) for xi, eta in self.norm_pts]
        spline = f2d.create_spline(tuple(poles))
        spline.closed = True
        sk.close_edition()
        self.part.update()

        origin_pt = self.hsf.add_new_point_coords([[0.0, 0.0, 0.0]])[0]
        origin_pt.name = "缩放中心"
        lib.append_hybrid_shape(origin_pt)
        scaling = self.hsf.add_new_hybrid_scaling(
            self._ref(sk), self._ref(origin_pt), float(p.root_chord)
        )
        lib.append_hybrid_shape(scaling)
        scaling.name = f"{stem}_缩放"
        try:
            self._formula("翼型缩放公式", scaling.ratio, "`翼根弦长`/1mm")
        except Exception as exc:  # noqa: BLE001
            print(f"    ! 缩放公式未挂（已按 {p.root_chord}mm 设值）: {str(exc)[:70]}")
        self.part.update()
        print("    缩放 OK（改 翼根弦长 时翼型随之缩放）")

    # -- 方案 A：多截面曲面 ---------------------------------------------
    def _loft_wing(self):
        p = self.p
        print(f"\n[4] 实现过程：{p.stations} 个展向截面（弦长/后掠/扭转逐截面计算）...")
        work = self.part.hybrid_bodies.add()
        work.name = "实现过程"
        self.work = work

        sections = []
        for i in range(p.stations):
            y = p.station_y(i)
            c, x_le, theta = p.at_station(y)
            pts = section_points(self.norm_pts, c, x_le, y, theta)
            sec = self._closed_spline(pts, f"截面_{i + 1:02d}")
            work.append_hybrid_shape(sec)
            sections.append(sec)
            print(f"    截面_{i + 1:02d}: y={y:7.2f}  c={c:6.2f}  "
                  f"x_le={x_le:7.2f}  θ={theta:5.2f}°")
        self.part.update()

        print("\n[5] 机翼：多截面曲面 ...")
        wing = self.part.hybrid_bodies.add()
        wing.name = "机翼"
        loft = self.hsf.add_new_loft()
        for sec in sections:
            loft.add_section_to_loft(self._ref(sec), 1, vba_nothing)
        wing.append_hybrid_shape(loft)
        loft.name = "多截面曲面"
        try:
            self.part.update()
            print("    多截面曲面 update 通过")
        except Exception as exc:  # noqa: BLE001
            print(f"    ! update 失败: {str(exc)[:160]}")
            print("      → 常见原因：截面点数/方向不一致，或相邻截面自交")

        self.wing_body = wing
        self.sections = sections          # 供实体化封口用
        self.main_surface = loft          # 对称/姿态在 _transforms() 里统一处理


    # -- 参数化多截面：截面 = 基准翼型 + 缩放 + 旋转 + 平移（全挂公式）------
    def _loft_wing_live(self):
        """每个截面都由「缩放→旋转→平移」四个特征生成，参数全部写成公式。

        好处：在 CATIA 里改 翼根弦长 / 翼展展长 / 后掠角 / 梢根比 / 安装角 / 几何扭转，
        Update 后整片机翼自动重建，无需重跑脚本。
        """
        p = self.p
        n = max(int(p.stations), 2)
        print(f"\n[4-5] 参数化多截面：{n} 个截面（缩放/旋转/平移均挂公式）...")
        work = self.part.hybrid_bodies.add()
        work.name = "实现过程"
        self.work = work

        # 基准翼型：弦长固定 100mm，前缘在原点（后面用公式缩放到各站弦长）
        base = self.hsf.add_new_spline()
        for xi, eta in self.norm_pts:
            base.add_point(self.hsf.add_new_point_coords([[xi * 100.0, 0.0, eta * 100.0]])[0])
        base.set_closing(1)
        base.name = "基准翼型_100mm"
        work.append_hybrid_shape(base)

        center = self.hsf.add_new_point_coords([[0.0, 0.0, 0.0]])[0]
        center.name = "缩放中心"
        work.append_hybrid_shape(center)

        # 旋转轴：沿展向 Y（长度取半展长，仅作方向用）
        ref_len = max(float(self.d["half_span"]), 100.0)
        a = self.hsf.add_new_point_coords([[0.0, 0.0, 0.0]])[0]
        b = self.hsf.add_new_point_coords([[0.0, ref_len, 0.0]])[0]
        yaxis = self.hsf.add_new_line_pt_pt(self._ref(a), self._ref(b))
        yaxis.name = "展向轴"
        work.append_hybrid_shape(yaxis)
        self.part.update()
        print("    基准翼型、缩放中心、展向轴 OK")

        sections = []
        for i in range(n):
            f = i / (n - 1) if n > 1 else 0.0
            tag = f"{i + 1:02d}"

            # 缩放：弦长 c_i = c_root * (1 + (λ-1)f)  → 比率 = c_i / 100mm
            sc = self.hsf.add_new_hybrid_scaling(self._ref(base), self._ref(center), 1.0)
            sc.name = f"截面{tag}_缩放"
            work.append_hybrid_shape(sc)
            self._formula(
                f"截面{tag}_缩放公式", sc.ratio,
                f"(`翼根弦长`/100mm)*(1+(`梢根比`-1)*{f:.6f})",
            )

            # 旋转：扭转角 θ_i = 安装角 + 几何扭转·f（绕展向轴，前缘为转心）
            rot = self.hsf.add_new_rotate(self._ref(sc), self._ref(yaxis), 0.0)
            rot.name = f"截面{tag}_旋转"
            work.append_hybrid_shape(rot)
            self._formula(f"截面{tag}_旋转公式", rot.angle,
                          f"`安装角`+`几何扭转`*{f:.6f}")

            # 平移 X：x_le_i = 0.25c_root + y_i·tan(Λ) - 0.25·c_i
            dx = self.hsf.add_new_direction_by_coord(1.0, 0.0, 0.0)
            tx = self.hsf.add_new_translate(self._ref(rot), dx, 0.0)
            tx.name = f"截面{tag}_平移X"
            work.append_hybrid_shape(tx)
            self._formula(
                f"截面{tag}_平移X公式", tx.distance,
                f"0.25*`翼根弦长`+(`翼展展长`/2*{f:.6f})*tan(`后掠角`)"
                f"-0.25*(`翼根弦长`*(1+(`梢根比`-1)*{f:.6f}))",
            )

            # 平移 Y：y_i = 半展长 · f
            dy = self.hsf.add_new_direction_by_coord(0.0, 1.0, 0.0)
            ty = self.hsf.add_new_translate(self._ref(tx), dy, 0.0)
            ty.name = f"截面{tag}_平移Y"
            work.append_hybrid_shape(ty)
            self._formula(f"截面{tag}_平移Y公式", ty.distance, f"`翼展展长`/2*{f:.6f}")

            self.part.update()
            sections.append(ty)

        print(f"    {n} 个截面的公式链建立完成")

        wing = self.part.hybrid_bodies.add()
        wing.name = "机翼"
        loft = self.hsf.add_new_loft()
        for sec in sections:
            loft.add_section_to_loft(self._ref(sec), 1, vba_nothing)
        wing.append_hybrid_shape(loft)
        loft.name = "多截面曲面"
        try:
            self.part.update()
            print("    多截面曲面 update 通过")
        except Exception as exc:  # noqa: BLE001
            print(f"    ! update 失败: {str(exc)[:160]}")
            print("      → 若反复失败，把截面数降到 5~7 再试")

        self.wing_body = wing
        self.sections = sections
        self.main_surface = loft


    # -- 方案 B：扫掠（保留） -------------------------------------------
    def _sweep_wing(self):
        p, d = self.p, self.d
        print("\n[4] 实现过程：引导线 + 脊线 ...")
        work = self.part.hybrid_bodies.add()
        work.name = "实现过程"
        self.work = work

        def pt(coords, name, x_f=None, y_f=None):
            o = self.hsf.add_new_point_coords([coords])[0]
            o.name = name
            if x_f:
                self._formula(f"{name}_X", o.x, x_f)
            if y_f:
                self._formula(f"{name}_Y", o.y, y_f)
            return o

        half = d["half_span"]
        le_root = pt([0.0, 0.0, 0.0], "LE_根")
        le_tip = pt([d["x_le_tip"], half, 0.0], "LE_梢",
                    x_f="0.25*`翼根弦长`+(`翼展展长`/2)*tan(`后掠角`)-0.25*`梢根比`*`翼根弦长`",
                    y_f="`翼展展长`/2")
        te_root = pt([d["x_te_root"], 0.0, 0.0], "TE_根", x_f="`翼根弦长`")
        te_tip = pt([d["x_te_tip"], half, 0.0], "TE_梢",
                    x_f="0.25*`翼根弦长`+(`翼展展长`/2)*tan(`后掠角`)+0.75*`梢根比`*`翼根弦长`",
                    y_f="`翼展展长`/2")
        sp_root = pt([0.0, 0.0, 0.0], "脊线_根")
        sp_tip = pt([0.0, half, 0.0], "脊线_梢", y_f="`翼展展长`/2")

        le = self.hsf.add_new_line_pt_pt(self._ref(le_root), self._ref(le_tip))
        te = self.hsf.add_new_line_pt_pt(self._ref(te_root), self._ref(te_tip))
        spine = self.hsf.add_new_line_pt_pt(self._ref(sp_root), self._ref(sp_tip))
        for o in (le, te, spine):
            work.append_hybrid_shape(o)
        le.name, te.name, spine.name = "前缘引导线", "后缘引导线", "脊线"
        self.part.update()

        print("\n[5] 机翼：扫掠 + 对称（此方案不含扭转）...")
        wing = self.part.hybrid_bodies.add()
        wing.name = "机翼"
        profile = None
        for body in self.part.hybrid_bodies:
            if body.name == "翼型库":
                for sh in body.hybrid_shapes:
                    if sh.name.endswith("_缩放"):
                        profile = sh
        sweep = self.hsf.add_new_sweep_explicit(self._ref(profile), self._ref(le))
        sweep.second_guide_crv = self._ref(te)
        sweep.spine = self._ref(spine)
        wing.append_hybrid_shape(sweep)
        sweep.name = "扫掠"
        self.part.update()
        self.wing_body = wing
        self.main_surface = sweep          # 对称/姿态在 _transforms() 里统一处理

    # -- 实体化：两端封口 → 接合 → 尝试封闭曲面 ------------------------
    def _solidify(self):
        """把开口翼面变成封闭结构。

        首尾截面填充封口 → 与翼面接合成水密壳体 → 尝试「封闭曲面」转实体。
        实测本机 CATIA 未授权零件设计的实体命令（连标准圆柱都失败），
        此时保留**水密壳体**并给出提示——壳体本身可直接用于外流场网格。
        """
        p = self.p
        if not p.solid:
            return
        if not getattr(self, "sections", None):
            print("\n[6] 实体化：缺少截面曲线，跳过")
            return

        print("\n[6] 实体化：两端封口 → 接合 → 封闭曲面 ...")
        body = getattr(self, "work", None)
        caps = []
        for i, sec in enumerate((self.sections[0], self.sections[-1])):
            try:
                f = self.hsf.add_new_fill()
                f.name = f"端封_{'根' if i == 0 else '梢'}"
                f.add_bound(self._ref(sec))
                body.append_hybrid_shape(f)
                caps.append(f)
            except Exception as exc:  # noqa: BLE001
                print(f"    ! 端封_{i} 失败: {str(exc)[:80]}")
        if len(caps) != 2:
            print("    ! 封口不完整，跳过实体化")
            return
        self.part.update()

        shell = self.main_surface
        try:
            j = self.hsf.add_new_join(self._ref(shell), self._ref(caps[0]))
            j.name = "接合_端封1"
            body.append_hybrid_shape(j)
            self.part.update()
            j2 = self.hsf.add_new_join(self._ref(j), self._ref(caps[1]))
            j2.name = "水密壳体"
            body.append_hybrid_shape(j2)
            self.part.update()
            shell = j2
            print("    封口 + 接合 OK（水密壳体）")
        except Exception as exc:  # noqa: BLE001
            print(f"    ! 接合失败: {str(exc)[:100]}")
            return

        # ★ 关键：实体特征必须建在「零件几何体」(PartBody) 里。
        #   若当前工作对象是几何图形集，AddNewCloseSurface 会直接失败（而且不提示原因）。
        try:
            from pycatia.mec_mod_interfaces.shape import Shape

            prev_work = None
            try:
                prev_work = self.part.in_work_object
            except Exception:  # noqa: BLE001
                pass
            self.part.in_work_object = self.part.main_body

            raw = self.part.shape_factory.com_object
            raw_solid = raw.AddNewCloseSurface(self._ref(shell).com_object)
            raw_solid.Name = "实体"
            self.part.update()
            solid = Shape(raw_solid)

            try:
                spa = self.doc.spa_workbench()
                vol = spa.get_measurable(self._ref(solid)).volume
                print(f"    ✓ 已封闭为实体，体积 = {vol:.6f} m³")
            except Exception:  # noqa: BLE001
                print("    ✓ 已封闭为实体")

            self.main_surface = solid
            self.solid_created = True
            if prev_work is not None:
                try:
                    self.part.in_work_object = prev_work
                except Exception:  # noqa: BLE001
                    pass
        except Exception as exc:  # noqa: BLE001
            print("    ! 「封闭曲面」失败，已保留水密壳体")
            print(f"      原因：{str(exc)[:110]}")
            print("      → 常见原因：壳体未完全缝合（有漏缝）。水密壳体可直接用于外流场网格；")
            print("        要实体可在 CATIA 里手动点一次『封闭曲面』。")
            self.main_surface = shell

    # -- 对称 + XYZ 旋转 + XYZ 平移（全部公式驱动，CATIA 内改即更新）------
    def _transforms(self):
        p = self.p
        print("\n[6] 对称与姿态（对称 / 绕XYZ旋转 / 平移XYZ）...")
        body = self.part.hybrid_bodies.add()
        body.name = "姿态与定位"
        cur = self.main_surface

        # 1) 对称（关于 XZ 平面，法向 Y）
        if bool(p.symmetric):
            plane = self.part.origin_elements.plane_zx
            sym = self.hsf.add_new_symmetry(self._ref(cur), self._ref(plane))
            sym.name = "对称"
            body.append_hybrid_shape(sym)
            self.part.update()
            cur = sym
            print("    对称：已生成（关于 XZ 平面）")
        else:
            print("    对称：跳过（只保留半翼）")

        # 2) 三条过原点的轴线，供旋转用
        axes = {}
        for name, vec in (("X", (120.0, 0.0, 0.0)), ("Y", (0.0, 120.0, 0.0)),
                          ("Z", (0.0, 0.0, 120.0))):
            o = self.hsf.add_new_point_coords([[0.0, 0.0, 0.0]])[0]
            e = self.hsf.add_new_point_coords([list(vec)])[0]
            ln = self.hsf.add_new_line_pt_pt(self._ref(o), self._ref(e))
            ln.name = f"{name}轴"
            body.append_hybrid_shape(ln)
            axes[name] = ln
        self.part.update()

        # 3) 旋转：Z → Y → X（先偏航，再俯仰，最后滚转）
        for name, q in (("Z", self.q_rz), ("Y", self.q_ry), ("X", self.q_rx)):
            rot = self.hsf.add_new_rotate(self._ref(cur), self._ref(axes[name]), 0.0)
            rot.name = f"旋转{name}"
            body.append_hybrid_shape(rot)
            try:
                self._formula(f"旋转{name}公式", rot.angle, f"`绕{name}旋转`")
                self.part.update()
            except Exception as exc:  # noqa: BLE001
                print(f"    ! 旋转{name} 公式未挂: {str(exc)[:70]}")
            cur = rot
            print(f"    旋转{name}: 已接入参数「绕{name}旋转」")

        # 4) 平移 X → Y → Z
        for name, q, vec in (("X", self.q_tx, (1.0, 0.0, 0.0)),
                             ("Y", self.q_ty, (0.0, 1.0, 0.0)),
                             ("Z", self.q_tz, (0.0, 0.0, 1.0))):
            try:
                d = self.hsf.add_new_direction_by_coord(*vec)
                tr = self.hsf.add_new_translate(self._ref(cur), d, 0.0)
                tr.name = f"平移{name}"
                body.append_hybrid_shape(tr)
                self._formula(f"平移{name}公式", tr.distance, f"`平移{name}`")
                self.part.update()
                cur = tr
                print(f"    平移{name}: 已接入参数「平移{name}」")
            except Exception as exc:  # noqa: BLE001
                print(f"    ! 平移{name} 失败: {str(exc)[:80]}")

        self.main_surface = cur
        print("    提示：在 CATIA 里改「绕X/Y/Z旋转」「平移X/Y/Z」会自动重算几何")

    # -- 翼肋：顺气流截面（默认解析式；可选"平面 ∩ 翼面"切片） ----------
    def _ribs(self):
        p, d = self.p, self.d
        half = d["half_span"]
        spacing = max(float(p.rib_spacing), 1e-6)
        ys = []
        y = spacing
        while y < half - 1e-6:
            ys.append(y)
            y += spacing
        if not ys:
            print(f"\n[6] 翼肋：间距 {spacing}mm 大于半展长，跳过")
            return

        mode = "平面 ∩ 翼面切片" if p.rib_slice else "解析截面"
        print(f"\n[6] 翼肋：{len(ys)} 个顺气流截面（间距 {spacing}mm，方式：{mode}）...")
        plane0 = self.part.origin_elements.plane_zx      # 法向 = 展向 Y
        body = self.part.hybrid_bodies.add()
        body.name = "翼肋"
        surf = self.main_surface
        work = self.work

        for i, y in enumerate(ys, 1):
            if not p.rib_slice:
                # 默认路线：直接算截面（与"平面 ∩ 翼面"等价，永不空切）
                c, x_le, theta = p.at_station(y)
                pts3 = section_points(self.norm_pts, c, x_le, y, theta)
                sec = self._closed_spline(pts3, f"翼肋_{i:02d}")
                body.append_hybrid_shape(sec)
                sym = self.hsf.add_new_symmetry(self._ref(sec), self._ref(plane0))
                sym.name = f"翼肋_镜像_{i:02d}"
                body.append_hybrid_shape(sym)
                self.part.update()
                print(f"    翼肋_{i:02d}: y = {y:.1f} mm")
                continue

            # 可选路线：CAD 原生的"切片"做法（对齐 UP 主第 3 集）
            # 注意 plane_zx 的偏移方向由 orientation 决定，False 才指向 +Y
            ok = False
            for orientation in (False, True):
                try:
                    pl = self.hsf.add_new_plane_offset(self._ref(plane0), y, orientation)
                    pl.name = f"翼肋平面_{i:02d}"
                    work.append_hybrid_shape(pl)
                    self.part.update()
                    inter = self.hsf.add_new_intersection(self._ref(surf), self._ref(pl))
                    inter.name = f"翼肋_{i:02d}"
                    body.append_hybrid_shape(inter)
                    sym = self.hsf.add_new_symmetry(self._ref(inter), self._ref(plane0))
                    sym.name = f"翼肋_镜像_{i:02d}"
                    body.append_hybrid_shape(sym)
                    self.part.update()
                    print(f"    翼肋_{i:02d}: y = {y:.1f} mm（切片）")
                    ok = True
                    break
                except Exception:  # noqa: BLE001
                    try:
                        pl.name = f"翼肋平面_{i:02d}_废弃"
                        self.part.update()
                    except Exception:  # noqa: BLE001
                        pass
            if not ok:
                c, x_le, theta = p.at_station(y)
                pts3 = section_points(self.norm_pts, c, x_le, y, theta)
                sec = self._closed_spline(pts3, f"翼肋_{i:02d}_解析")
                body.append_hybrid_shape(sec)
                sym = self.hsf.add_new_symmetry(self._ref(sec), self._ref(plane0))
                sym.name = f"翼肋_镜像_{i:02d}_解析"
                body.append_hybrid_shape(sym)
                self.part.update()
                print(f"    翼肋_{i:02d}: y = {y:.1f} mm（切片空 → 解析兜底）")

    # -- measured 口径：用实测翼面面积回填展弦比 ------------------------
    def _fill_measured_aspect_ratio(self):
        p, d = self.p, self.d
        try:
            spa = self.doc.spa_workbench()
            area_m2 = spa.get_measurable(self._ref(self.main_surface)).area
            s_half = area_m2 * 1e6 / 2.0        # 闭合曲面双面 → 半翼投影面积
            if s_half <= 0:
                raise ValueError("面积为 0")
            ar = d["area"] / s_half             # b² / 半翼面积
            self.q_ar.value = ar
            self.part.update()
            print(f"\n[measured] 翼面面积={area_m2:.6f} m² → 半翼面积={s_half:.0f} mm²")
            print(f"[measured] 展弦比 = {ar:.6f}（理论 {d['aspect_ratio']:.6f}，"
                  f"差 {(ar / d['aspect_ratio'] - 1) * 100:+.2f}%）")
            print("  注意：measured 模式是回填静态值，不随参数联动")
        except Exception as exc:  # noqa: BLE001
            print(f"\n! measured 展弦比回填失败: {str(exc)[:120]}")

    # -- 报告 -----------------------------------------------------------
    def _report(self):
        p = self.part
        print("\n生成的设计树：")
        print("  参数:")
        for n in ("翼型选择器", "翼根弦长", "翼展展长", "后掠角",
                  "几何扭转", "梢根比", "展弦比", "安装角"):
            try:
                o = p.parameters.get_item_by_name(f"{p.name}\\{n}")
                print(f"    {n:<12} = {o.value_as_string()}")
            except Exception:  # noqa: BLE001
                print(f"    {n:<12} (读取失败)")
        print("  关系:", ", ".join(r.name for r in p.relations))
        for body in p.hybrid_bodies:
            kids = [s.name for s in body.hybrid_shapes]
            shown = ", ".join(kids[:8]) + (" …" if len(kids) > 8 else "")
            print(f"  几何图形集 [{body.name}] {len(kids)} 项: {shown}")


# ----------------------------------------------------------------------------
# 入口
# ----------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="CATIA 机翼参数化建模")
    ap.add_argument("--config", help="参数 JSON 文件")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--method", choices=("loft", "sweep"), help="建模方式")
    ap.add_argument("--ribs", action="store_true", help="同时生成翼肋")
    ap.add_argument("--rib-spacing", type=float, help="翼肋间距 mm")
    ap.add_argument("--ar-mode", choices=("analytic", "measured"), help="展弦比口径")
    args = ap.parse_args(argv)

    if args.config:
        data = json.loads(Path(args.config).read_text(encoding="utf-8-sig"))
        params = WingParams(**data)
    else:
        params = prompt_params()
    if args.method:
        params.method = args.method
    if args.ribs:
        params.ribs = True
    if args.rib_spacing:
        params.rib_spacing = args.rib_spacing
    if args.ar_mode:
        params.ar_mode = args.ar_mode

    d = params.derived()
    print("\n参数：")
    for k, v in asdict(params).items():
        print(f"  {k:<14} = {v}")
    print("推导：")
    for k, v in d.items():
        print(f"  {k:<14} = {v:.4f}" if isinstance(v, float) else f"  {k:<14} = {v}")

    if args.dry_run:
        return 0

    WingBuilder(params).build()
    return 0


if __name__ == "__main__":
    sys.exit(main())
