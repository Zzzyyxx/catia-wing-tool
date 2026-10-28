"""CATIA 机翼参数化建模 · 启动器

图形界面：导入翼型 .dat → 填写工程参数 → 一键在 CATIA 里生成参数化机翼模型。

运行：
    C:\\Users\\lenovo\\anaconda3\\envs\\catia311\\python.exe launcher.py
或双击 launcher.pyw（如果有）

依赖：Python 3.11 环境 catia311（pycatia 0.10.1 + pywin32）、tkinter（自带）
"""

from __future__ import annotations

import contextlib
import io
import math
import os
import queue
import sys

# 禁止写 .pyc：避免换解释器时出现 Bad magic number in .pyc file
sys.dont_write_bytecode = True
import threading
import time
import traceback
from dataclasses import asdict
from pathlib import Path
from tkinter import BooleanVar, StringVar, Tk, filedialog, messagebox, ttk
import tkinter as tk

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

# ---- 运行环境自检（必须在导入 wing_builder 之前，否则会抛 Bad magic / ModuleNotFound） ----
RUNTIME_OK = True
RUNTIME_MSG = ""
if sys.version_info[:2] != (3, 11):
    RUNTIME_OK = False
    RUNTIME_MSG += (f"当前解释器是 Python {sys.version.split()[0]}（{sys.executable}），"
                    f"本项目需要 Python 3.11 的 catia311 环境。\n")

try:
    from wing_builder import WingBuilder, WingParams, parse_airfoil  # noqa: E402
except Exception as _exc:  # noqa: BLE001
    RUNTIME_OK = False
    RUNTIME_MSG += f"导入建模模块失败：{_exc}\n"
    WingBuilder = WingParams = parse_airfoil = None  # type: ignore[assignment]


# ---------------------------------------------------------------- 版式常量
BG = "#20242c"
PANEL = "#2a2f39"
FG = "#e8eaf0"
MUTED = "#8b93a3"
ACCENT = "#4ea1d3"
CANVAS_BG = "#171a20"
OK_GREEN = "#5fbf8f"
WARN_RED = "#d96b6b"


class ScrollFrame(ttk.Frame):
    """可滚动的垂直容器 —— 保证任何 DPI 下左侧面板都不会被裁掉。"""

    def __init__(self, parent):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, bg=BG, highlightthickness=0, width=372)
        self.vbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vbar.set)
        self.vbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.inner = ttk.Frame(self.canvas)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )
        self.canvas.bind(
            "<Configure>",
            lambda e: self.canvas.itemconfigure(self._win, width=e.width),
        )
        self.canvas.bind("<Enter>", lambda e: self.canvas.focus_set())
        self.canvas.bind("<MouseWheel>", self._on_wheel)

    def _on_wheel(self, event):
        self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")


class Launcher:
    def __init__(self, root: Tk):
        self.root = root
        self.airfoils: list[Path] = []
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.log_lines: list[str] = []
        self.worker: threading.Thread | None = None

        root.title("CATIA 机翼参数化建模 · 启动器")
        root.configure(bg=BG)

        # DPI 缩放：字号一律用"负值＝像素"指定，避免 150% 缩放下被放大到撑爆屏幕
        try:
            self.s = max(1.0, root.winfo_fpixels("1i") / 96.0)
        except Exception:  # noqa: BLE001
            self.s = 1.0

        self._build_style()
        self._build_layout()
        self._poll_log()
        if os.environ.get("LAUNCHER_DEBUG"):
            self.root.after(3000, self._dump_debug)
        # 等窗口真正完成布局后再画（多次重试，避免画在初始尺寸上）
        self._redraw_job = None
        for delay in (200, 500, 1200, 2500):
            self.root.after(delay, self._schedule_redraw)

    def _font(self, px: int, bold: bool = False, mono: bool = False):
        """按 DPI 缩放后的像素字号（负值＝像素）。"""
        fam = "Consolas" if mono else "Microsoft YaHei UI"
        size = -max(9, int(px * self.s))
        return (fam, size, "bold") if bold else (fam, size)

    def _dump_debug(self):
        """LAUNCHER_DEBUG=1 时把画布真实状态写到 launcher_debug.txt，便于排查。"""
        try:
            c = self.canvas
            lines = [
                f"screen={self.root.winfo_screenwidth()}x{self.root.winfo_screenheight()}",
                f"win={self.root.winfo_width()}x{self.root.winfo_height()}",
                f"dpi_scale={self.s:.3f}",
                f"canvas={c.winfo_width()}x{c.winfo_height()}",
                f"items={len(c.find_all())}",
                f"bbox={c.bbox('all')}",
            ]
            for i in c.find_all()[:4]:
                lines.append(f"  {c.type(i)} {tuple(round(v, 1) for v in c.coords(i)[:4])}")
            Path("launcher_debug.txt").write_text("\n".join(lines), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            Path("launcher_debug.txt").write_text(f"ERR {exc}", encoding="utf-8")

    def _schedule_redraw(self):
        """防抖重绘：尺寸/参数变化后等 120ms 再画。"""
        if self._redraw_job:
            try:
                self.root.after_cancel(self._redraw_job)
            except Exception:  # noqa: BLE001
                pass
        self._redraw_job = self.root.after(120, self._refresh_preview)

    # ------------------------------------------------------------ 样式
    def _build_style(self):
        st = ttk.Style()
        st.theme_use("clam")
        st.configure(".", background=BG, foreground=FG, fieldbackground=PANEL,
                     bordercolor="#3a4150", lightcolor=PANEL, darkcolor=PANEL)
        st.configure("TFrame", background=BG)
        st.configure("Panel.TFrame", background=PANEL)
        st.configure("TLabel", background=BG, foreground=FG)
        st.configure("Panel.TLabel", background=PANEL, foreground=FG)
        st.configure("Muted.TLabel", background=BG, foreground=MUTED)
        st.configure("H1.TLabel", background=BG, foreground=FG, font=self._font(19, bold=True))
        st.configure("H2.TLabel", background=BG, foreground=ACCENT, font=self._font(13, bold=True))
        st.configure("Value.TLabel", background=BG, foreground=OK_GREEN, font=self._font(13, mono=True))
        st.configure("TEntry", insertcolor=FG, padding=3)
        st.configure("TCombobox", padding=2)
        st.configure("TButton", padding=(10, 4), background="#333a47", foreground=FG,
                     font=self._font(13))
        st.map("TButton", background=[("active", "#3e4757")])
        st.configure("Go.TButton", background=ACCENT, foreground="#0d1117",
                     font=self._font(14, bold=True))
        st.map("Go.TButton", background=[("active", "#6ab8e6")])
        st.configure("TNotebook", background=BG, borderwidth=0)
        st.configure("TNotebook.Tab", background="#2a2f39", foreground=MUTED, padding=(14, 6))
        st.map("TNotebook.Tab", background=[("selected", PANEL)], foreground=[("selected", FG)])

    # ------------------------------------------------------------ 布局
    def _build_layout(self):
        # 用 grid 三行布局：标题 / 主区（可伸缩）/ 底部操作条 —— 高度分配确定
        self.root.rowconfigure(1, weight=1)
        self.root.columnconfigure(0, weight=1)

        head = ttk.Frame(self.root, padding=(18, 14, 18, 6))
        head.grid(row=0, column=0, sticky="ew")
        ttk.Label(head, text="CATIA 机翼参数化建模 · 启动器", style="H1.TLabel").pack(side="left")
        ttk.Label(head, text="  翼型 .dat 导入 → 参数 → 生成设计树",
                  style="Muted.TLabel").pack(side="left", pady=(6, 0))

        body = ttk.Frame(self.root, padding=(18, 0, 18, 8))
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=0, minsize=390)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        left = ScrollFrame(body)          # 左侧可滚动，内容再多也不会被裁
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        right = ttk.Frame(body)
        right.grid(row=0, column=1, sticky="nsew")

        self._build_airfoil_panel(left.inner)
        self._build_param_panel(left.inner)
        self._build_pose_panel(left.inner)
        self._build_actions(left.inner)
        self._build_preview(right)
        self._build_log(right)

        # 初始尺寸 + 明确位置（避免窗口被摆到屏幕外导致底部看不到）
        self.root.geometry("1360x930+30+20")
        self.root.minsize(980, 640)

    # 翼型列表 ------------------------------------------------------
    def _build_airfoil_panel(self, parent):
        ttk.Label(parent, text="① 翼型库", style="H2.TLabel").pack(anchor="w", pady=(4, 4))
        box = ttk.Frame(parent, style="Panel.TFrame", padding=8)
        box.pack(fill="x")

        self.listbox = tk.Listbox(
            box, height=3, bg="#1b1f26", fg=FG, selectbackground=ACCENT,
            selectforeground="#0d1117", borderwidth=0, highlightthickness=0,
            font=self._font(12, mono=True), activestyle="none",
        )
        self.listbox.pack(fill="x")
        self.listbox.bind("<<ListboxSelect>>", self._on_pick_airfoil)

        row = ttk.Frame(box, style="Panel.TFrame")
        row.pack(fill="x", pady=(6, 0))
        ttk.Button(row, text="导入 .dat", command=self._add_airfoils).pack(side="left")
        ttk.Button(row, text="移除", command=self._remove_airfoil).pack(side="left", padx=6)
        ttk.Button(row, text="清空", command=self._clear_airfoils).pack(side="left")

        self.airfoil_info = ttk.Label(box, text="（尚未导入翼型文件）",
                                      style="Panel.TLabel", foreground=MUTED,
                                      font=self._font(12))
        self.airfoil_info.pack(anchor="w", pady=(6, 0))

    # 参数 ----------------------------------------------------------
    def _build_param_panel(self, parent):
        ttk.Label(parent, text="② 工程参数", style="H2.TLabel").pack(anchor="w", pady=(12, 4))
        box = ttk.Frame(parent, style="Panel.TFrame", padding=10)
        box.pack(fill="x")
        for col in (1, 3):
            box.columnconfigure(col, weight=0)

        self.vars: dict[str, StringVar] = {}
        fields = [
            ("root_chord", "翼根弦长 [mm]", "100"),
            ("span", "翼展展长 [mm]", "500"),
            ("sweep_quarter", "后掠角 [deg]", "30"),
            ("taper", "梢根比", "0.45"),
            ("incidence", "安装角 [deg]", "10"),
            ("twist", "几何扭转 [deg]", "10"),
            ("stations", "展向截面数", "7"),
        ]
        # 两列布局，省垂直空间
        for idx, (key, label, default) in enumerate(fields):
            r, half = divmod(idx, 2)
            c0 = half * 2
            ttk.Label(box, text=label, style="Panel.TLabel").grid(
                row=r, column=c0, sticky="w", pady=3, padx=(0, 8))
            var = StringVar(value=default)
            var.trace_add("write", lambda *_: self._refresh_preview())
            ttk.Entry(box, textvariable=var, width=8).grid(
                row=r, column=c0 + 1, sticky="w", pady=3, padx=(0, 14))
            self.vars[key] = var

        r = (len(fields) + 1) // 2
        ttk.Label(box, text="建模方式", style="Panel.TLabel").grid(
            row=r, column=0, sticky="w", pady=(8, 3), padx=(0, 8))
        self.method = StringVar(value="loft（多截面·可扭转·仿真推荐）")
        cb = ttk.Combobox(box, textvariable=self.method, state="readonly",
                          values=("loft（多截面·可扭转·仿真推荐）",
                                  "sweep（扫掠·无扭转）"))
        cb.grid(row=r, column=1, columnspan=3, sticky="ew", pady=(8, 3))
        cb.bind("<<ComboboxSelected>>", lambda *_: self._refresh_preview())

        self.derived_label = ttk.Label(box, text="", style="Value.TLabel", justify="left")
        self.derived_label.grid(row=r + 1, column=0, columnspan=4, sticky="w", pady=(8, 0))

        # 翼肋（对齐 UP 主第 3 集：等间距平面阵列 ∩ 翼面）
        self.ribs_var = BooleanVar(value=False)
        ttk.Checkbutton(box, text="生成翼肋", variable=self.ribs_var).grid(
            row=r + 2, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Label(box, text="间距[mm]", style="Panel.TLabel").grid(
            row=r + 2, column=2, sticky="w", pady=(8, 0))
        self.rib_spacing_var = StringVar(value="40")
        ttk.Entry(box, textvariable=self.rib_spacing_var, width=7).grid(
            row=r + 2, column=3, sticky="w", pady=(8, 0))

    # 对称与姿态（OpenVSP 风格：公式驱动，进 CATIA 后仍可改） ----------
    def _build_pose_panel(self, parent):
        ttk.Label(parent, text="④ 对称与姿态").pack(anchor="w", pady=(4, 0))
        ttk.Label(parent, text="这些参数在 CATIA 里改也会自动更新几何",
                  style="Muted.TLabel", font=self._font(11)).pack(anchor="w", pady=(0, 4))
        box = ttk.Frame(parent, style="Panel.TFrame", padding=10)
        box.pack(fill="x")
        for col in (1, 3):
            box.columnconfigure(col, weight=0)

        self.pose_vars: dict[str, StringVar] = {}
        self.sym_var = BooleanVar(value=True)
        ttk.Checkbutton(box, text="对称（镜像半翼）", variable=self.sym_var).grid(
            row=0, column=0, columnspan=4, sticky="w", pady=(0, 6))

        rows = [
            ("rot_x", "绕X旋转[deg]", "0", "trans_x", "平移X[mm]", "0"),
            ("rot_y", "绕Y旋转[deg]", "0", "trans_y", "平移Y[mm]", "0"),
            ("rot_z", "绕Z旋转[deg]", "0", "trans_z", "平移Z[mm]", "0"),
        ]
        for i, (k1, l1, d1, k2, l2, d2) in enumerate(rows, start=1):
            for col, key, label, default in (
                (0, k1, l1, d1), (2, k2, l2, d2),
            ):
                ttk.Label(box, text=label, style="Panel.TLabel").grid(
                    row=i, column=col, sticky="w", pady=2, padx=(0, 6))
                v = StringVar(value=default)
                ttk.Entry(box, textvariable=v, width=7).grid(
                    row=i, column=col + 1, sticky="w", pady=2, padx=(0, 12))
                self.pose_vars[key] = v

        self.pose_hint = ttk.Label(box, text="", style="Value.TLabel")
        self.pose_hint.grid(row=4, column=0, columnspan=4, sticky="w", pady=(6, 0))

    # 操作区 --------------------------------------------------------
    def _build_actions(self, parent, standalone: bool = False):
        if not standalone:
            ttk.Label(parent, text="③ 输出与生成", style="H2.TLabel").pack(anchor="w", pady=(12, 4))
        box = ttk.Frame(parent, style="Panel.TFrame", padding=(12, 10))
        box.pack(fill="x")

        row0 = ttk.Frame(box, style="Panel.TFrame")
        row0.pack(fill="x")
        ttk.Label(row0, text="保存为", style="Panel.TLabel").pack(side="left")
        self.save_var = StringVar(value="")
        ttk.Entry(row0, textvariable=self.save_var).pack(
            side="left", fill="x", expand=True, padx=(8, 6))
        ttk.Button(row0, text="浏览…", command=self._pick_save).pack(side="left")

        row2 = ttk.Frame(box, style="Panel.TFrame")
        row2.pack(fill="x", pady=(10, 0))
        self.btn_build = ttk.Button(row2, text="⚡ 生成机翼模型", style="Go.TButton",
                                    command=self._start_build)
        self.btn_build.pack(side="left")
        self.btn_dry = ttk.Button(row2, text="仅计算校验", command=self._dry_run)
        self.btn_dry.pack(side="left", padx=8)
        self.btn_shot = ttk.Button(row2, text="截图", command=self._capture)
        self.btn_shot.pack(side="left")

        self.status = ttk.Label(box, text="就绪", style="Panel.TLabel", foreground=MUTED)
        self.status.pack(anchor="w", pady=(8, 0))

    # 预览 ----------------------------------------------------------
    def _build_preview(self, parent):
        ttk.Label(parent, text="俯视预览（参数驱动）", style="H2.TLabel").pack(anchor="w", pady=(4, 4))
        self.canvas = tk.Canvas(parent, bg=CANVAS_BG, highlightthickness=0, height=250)
        self.canvas.pack(fill="x")     # 固定高度，不参与伸缩
        # 直接用事件给的尺寸画，避免拿到布局前的旧尺寸
        self.canvas.bind("<Configure>",
                         lambda e: self._refresh_preview(e.width, e.height))

    # 日志 ----------------------------------------------------------
    def _build_log(self, parent):
        ttk.Label(parent, text="运行日志", style="H2.TLabel").pack(anchor="w", pady=(14, 4))
        frame = ttk.Frame(parent, style="Panel.TFrame")
        frame.pack(fill="both", expand=True)
        self.log = tk.Text(frame, bg="#1b1f26", fg="#cfd6e4", insertbackground=FG,
                           borderwidth=0, highlightthickness=0, wrap="word",
                           font=self._font(12, mono=True))
        sb = ttk.Scrollbar(frame, command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)
        self.log.configure(state="disabled")

    # ------------------------------------------------------------ 翼型
    def _add_airfoils(self):
        paths = filedialog.askopenfilenames(
            title="选择翼型 .dat 文件",
            filetypes=[("翼型数据", "*.dat"), ("文本", "*.txt"), ("全部", "*.*")],
        )
        added = 0
        for p in paths:
            path = Path(p)
            if path in self.airfoils:
                continue
            try:
                pts = parse_airfoil(path)
            except Exception as exc:  # noqa: BLE001
                self._log(f"✗ {path.name}: {exc}")
                continue
            self.airfoils.append(path)
            self.listbox.insert("end", f"{path.name:<22} {len(pts):>4} 点")
            added += 1
        if added:
            self._log(f"已导入 {added} 个翼型文件")
        self._on_pick_airfoil()

    def _remove_airfoil(self):
        idx = self.listbox.curselection()
        if not idx:
            return
        i = idx[0]
        self.listbox.delete(i)
        self.airfoils.pop(i)
        self._on_pick_airfoil()

    def _clear_airfoils(self):
        self.listbox.delete(0, "end")
        self.airfoils.clear()
        self._on_pick_airfoil()

    def _on_pick_airfoil(self, _event=None):
        if not self.airfoils:
            self.airfoil_info.configure(text="（尚未导入翼型文件）")
            self._refresh_preview()
            return
        idx = self.listbox.curselection()
        i = idx[0] if idx else 0
        path = self.airfoils[i]
        try:
            pts = parse_airfoil(path)
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            thick = (max(ys) - min(ys)) if ys else 0
            self.airfoil_info.configure(
                text=f"当前：{path.stem} | {len(pts)} 点 | 最大厚度比 ≈ {thick:.3f}c")
            self.listbox.selection_clear(0, "end")
            self.listbox.selection_set(i)
        except Exception as exc:  # noqa: BLE001
            self.airfoil_info.configure(text=f"读取失败：{exc}")
        self._refresh_preview()

    # ------------------------------------------------------------ 预览绘制
    def _current_params(self, require_airfoil: bool = False) -> WingParams:
        vals = {k: float(v.get()) for k, v in self.vars.items() if k != "stations"}
        vals["stations"] = int(float(self.vars["stations"].get()))
        airfoil = str(self.airfoils[0]) if self.airfoils else ""
        if require_airfoil and not airfoil:
            raise ValueError("请先导入翼型 .dat 文件")
        m = "sweep" if self.method.get().startswith("sweep") else "loft"
        try:
            rib_spacing = float(self.rib_spacing_var.get())
        except (TypeError, ValueError):
            rib_spacing = 40.0
        pose = {}
        for k, v in self.pose_vars.items():
            try:
                pose[k] = float(v.get() or 0)
            except (TypeError, ValueError):
                pose[k] = 0.0
        return WingParams(
            airfoil_file=airfoil,
            save_path=self.save_var.get().strip(),
            method=m,
            ribs=bool(self.ribs_var.get()),
            rib_spacing=rib_spacing,
            symmetric=bool(self.sym_var.get()),
            **pose,
            **vals,
        )

    def _refresh_preview(self, w: int | None = None, h: int | None = None):
        try:
            self._draw_preview(w, h)
        except Exception:  # noqa: BLE001
            traceback.print_exc()

    def _draw_preview(self, w: int | None = None, h: int | None = None):
        p = self._current_params()
        d = p.derived()
        c = self.canvas
        w = w or c.winfo_width()
        h = h or c.winfo_height()
        if w < 80 or h < 80:      # 还没完成布局
            return
        c.delete("all")

        x_extent = max(d["x_te_tip"], d["x_te_root"]) * 1.12 or 1
        y_extent = d["half_span"] * 2.1 or 1        # 含镜像半翼
        pad = 26
        scale = min((w - 2 * pad) / x_extent, (h - 2 * pad) / y_extent)
        # 让图形在画布中居中
        off_x = pad + ((w - 2 * pad) - x_extent * scale) / 2
        off_y = pad + ((h - 2 * pad) - y_extent * scale) / 2

        def P(x, y):
            # 俯视：x 向右；y=0 在中线，正 y 向上（半翼），负 y 向下（镜像）
            cy = y_extent * scale / 2
            return off_x + x * scale, off_y + cy - y * scale

        n = p.stations
        left, right = [], []
        for i in range(n):
            y = p.station_y(i)
            ch, x_le, _ = p.at_station(y)
            left.append(P(x_le, y))
            right.append(P(x_le + ch, y))

        outline = left + list(reversed(right))

        # 镜像半翼（y 取负）
        m_left, m_right = [], []
        for i in range(n):
            y = p.station_y(i)
            ch, x_le, _ = p.at_station(y)
            m_left.append(P(x_le, -y))
            m_right.append(P(x_le + ch, -y))
        mirror = list(reversed(m_left)) + m_right

        c.create_polygon(*[v for pt in outline for v in pt],
                         fill="#2f5d78", outline=ACCENT, width=2)
        c.create_polygon(*[v for pt in mirror for v in pt],
                         fill="#26323d", outline="#3d5568", width=1, dash=(4, 3))

        # 截面线
        for i in range(n):
            y = p.station_y(i)
            ch, x_le, _ = p.at_station(y)
            a, b = P(x_le, y), P(x_le + ch, y)
            c.create_line(*a, *b, fill="#e8eaf0", width=2 if i in (0, n - 1) else 1)

        # 1/4 弦线
        q = [P(0.25 * p.root_chord + p.station_y(i) * math.tan(
            math.radians(p.sweep_quarter)), p.station_y(i)) for i in range(n)]
        c.create_line(*[v for pt in q for v in pt], fill="#e0b25a", width=1, dash=(6, 4))

        c.create_text(pad, 14, anchor="w", fill=MUTED,
                      text=f"俯视  |  半展 {d['half_span']:.1f}  根弦 {p.root_chord:.1f}  "
                           f"梢弦 {d['c_tip']:.1f}  半翼面积 {d['s_half']:.0f} mm²",
                      font=self._font(12, mono=True))

        # 兜底：万一绘制用的尺寸和实际画布不一致（DPI/布局竞态），
        # 把图形整体挪回可视区域，保证永远看得见。
        try:
            bbox = c.bbox("all")
            if bbox:
                shift_x = 0.0
                shift_y = 0.0
                if bbox[2] > w - 4:
                    shift_x = (w - 4) - bbox[2]
                if bbox[3] > h - 4:
                    shift_y = (h - 4) - bbox[3]
                if shift_x or shift_y:
                    c.move("all", shift_x, shift_y)
        except Exception:  # noqa: BLE001
            pass
        self.derived_label.configure(
            text=(f"梢弦 {d['c_tip']:.2f} mm   展弦比 {d['aspect_ratio']:.4f}\n"
                  f"半翼面积 {d['s_half']:.0f} mm²   梢部前缘 x {d['x_le_tip']:.1f} mm"))

    # ------------------------------------------------------------ 动作
    def _pick_save(self):
        path = filedialog.asksaveasfilename(
            title="保存 CATPart", defaultextension=".CATPart",
            filetypes=[("CATIA 零件", "*.CATPart")],
        )
        if path:
            self.save_var.set(path)

    def _log(self, text: str):
        self.log_queue.put(text)
        self.log_lines.append(str(text))
        if len(self.log_lines) > 4000:
            del self.log_lines[:2000]

    def _dump_build_log(self) -> Path | None:
        """把本次运行的完整日志落盘，方便失败时排查。"""
        try:
            d = HERE / "logs"
            d.mkdir(exist_ok=True)
            p = d / f"build_{time.strftime('%Y%m%d_%H%M%S')}.log"
            p.write_text("\n".join(self.log_lines), encoding="utf-8")
            return p
        except Exception:  # noqa: BLE001
            return None

    def _poll_log(self):
        try:
            while True:
                line = self.log_queue.get_nowait()
                self.log.configure(state="normal")
                self.log.insert("end", line.rstrip() + "\n")
                self.log.see("end")
                self.log.configure(state="disabled")
        except queue.Empty:
            pass
        self.root.after(80, self._poll_log)

    def _set_busy(self, busy: bool, msg: str = ""):
        state = "disabled" if busy else "normal"
        self.btn_build.configure(state=state)
        self.btn_dry.configure(state=state)
        self.status.configure(text=msg or ("工作中…" if busy else "就绪"),
                              foreground=ACCENT if busy else MUTED)

    def _dry_run(self):
        try:
            p = self._current_params(require_airfoil=True)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("参数有误", str(exc))
            return
        d = p.derived()
        self._log("— 参数校验 —")
        for k, v in asdict(p).items():
            self._log(f"  {k:<14} = {v}")
        self._log(f"  梢弦 = {d['c_tip']:.3f} mm")
        self._log(f"  半翼面积 = {d['s_half']:.1f} mm²   展弦比 = {d['aspect_ratio']:.4f}")
        self._log("  校验通过。")

    def _start_build(self):
        if self.worker and self.worker.is_alive():
            return
        try:
            p = self._current_params(require_airfoil=True)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("参数有误", str(exc))
            return
        self._set_busy(True, "正在连接 CATIA 并建模…")
        self._log("=" * 56)
        self._log(f"开始生成：{Path(p.airfoil_file).name}  method={p.method}")
        self.worker = threading.Thread(target=self._build_worker, args=(p,), daemon=True)
        self.worker.start()

    def _build_worker(self, p: WingParams):
        t0 = time.time()

        class _QWriter(io.TextIOBase):
            """把 wing_builder 的 print 输出实时送进日志区。"""

            def __init__(self, put):
                self._put = put
                self._buf = ""

            def write(self, s):
                self._buf += s
                while "\n" in self._buf:
                    line, self._buf = self._buf.split("\n", 1)
                    self._put(line)
                return len(s)

            def flush(self):
                if self._buf:
                    self._put(self._buf)
                    self._buf = ""

        try:
            builder = WingBuilder(p)
            with contextlib.redirect_stdout(_QWriter(self._log)):
                builder.build()
            _QWriter(self._log).flush()
            self._log(f"✔ 完成，用时 {time.time() - t0:.1f}s")
            logp = self._dump_build_log()
            if logp:
                self._log(f"日志已保存：{logp}")
            self.root.after(0, lambda: self._set_busy(False, "完成 ✔ 请查看 CATIA"))
        except Exception as exc:  # noqa: BLE001
            self._log("✗ 失败：")
            self._log(str(exc))
            self._log(traceback.format_exc(limit=4))
            logp = self._dump_build_log()
            if logp:
                self._log(f"日志已保存：{logp}")
            err = str(exc)
            tip = f"\n\n日志：{logp}" if logp else ""
            self.root.after(0, lambda: self._set_busy(False, "失败 ✗"))
            self.root.after(0, lambda: messagebox.showerror("生成失败", err + tip))

    def _capture(self):
        def job():
            try:
                import time as _t
                import pycatia
                from pycatia import CatCaptureFormat
                catia = pycatia.catia()
                v = catia.active_window.active_viewer
                v.reframe()
                _t.sleep(1.0)
                out = HERE / "output" / f"shot_{_t.strftime('%H%M%S')}.jpg"
                out.parent.mkdir(parents=True, exist_ok=True)
                v.capture_to_file(int(CatCaptureFormat.catCaptureFormatJPEG), str(out))
                self._log(f"截图已保存：{out}")
            except Exception as exc:  # noqa: BLE001
                self._log(f"截图失败：{exc}")
        threading.Thread(target=job, daemon=True).start()


def _enable_dpi_awareness():
    """让 Tk 使用物理像素，否则在 125%/150% 缩放下界面会被裁切。"""
    try:
        from ctypes import windll
        try:
            windll.shcore.SetProcessDpiAwareness(1)   # system DPI aware（Tk 最稳）
        except Exception:  # noqa: BLE001
            windll.user32.SetProcessDPIAware()
    except Exception:  # noqa: BLE001
        pass


def _fit_to_screen(root: Tk):
    """按控件实际需求 + 屏幕可用区域决定窗口大小，避免被裁。"""
    root.update_idletasks()
    need_w = root.winfo_reqwidth()
    need_h = root.winfo_reqheight()
    scr_w = root.winfo_screenwidth()
    scr_h = root.winfo_screenheight()
    w = min(need_w, scr_w - 60)
    h = min(need_h, scr_h - 120)
    root.geometry(f"{w}x{h}+30+30")


def _check_runtime() -> bool:
    """检查解释器与依赖；不对就给出人能看懂的提示，而不是 Bad magic number。"""
    ok = True
    if sys.version_info[:2] != (3, 11):
        print("=" * 62)
        print(f"[环境不对] 当前 Python {sys.version.split()[0]}：{sys.executable}")
        print("本项目需要 Anaconda 的 catia311 环境（Python 3.11 + pycatia）。")
        print("请双击同目录的「启动器.bat」，或在命令行执行：")
        print(r'  python launcher.py        （在 CATIA_PY 指向的 3.11 环境里）')
        print("=" * 62)
        ok = False
    try:
        import pycatia  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        print(f"[依赖缺失] 导入 pycatia 失败：{exc}")
        print(r'请安装: python -m pip install pycatia（在 Python 3.11 环境里执行）')
        ok = False
    return ok


def find_python311() -> Path | None:
    """按优先级找一个 python 解释器：CATIA_PY 环境变量 → 常见 conda 路径 → PATH。

    找到就返回路径（不保证是 3.11，调用方会再验证）；找不到返回 None。
    """
    cands: list[Path] = []
    env = os.environ.get("CATIA_PY")
    if env:
        cands.append(Path(env))
    home = Path(os.environ.get("USERPROFILE") or os.path.expanduser("~"))
    for base in (home / "anaconda3", home / "miniconda3",
                 Path("C:/ProgramData/anaconda3"), Path("C:/ProgramData/miniconda3")):
        cands.append(base / "envs" / "catia311" / "python.exe")
    cands.append(Path(sys.executable))
    for p in cands:
        try:
            if p and p.exists():
                return p
        except OSError:
            continue
    return None


def _bootstrap_with_correct_python() -> bool:
    """当前解释器不对时，用正确的 catia311 解释器把自己重新拉起来。

    这样无论用户双击 .py、还是用别的 python 运行，都能自动切到 3.11。
    """
    try:
        me = Path(__file__).resolve()
        target = find_python311()
        if target is None:
            return False
        if Path(sys.executable).resolve() == target.resolve():
            return False
        import subprocess
        subprocess.Popen(
            [str(target), str(me)],
            cwd=str(HERE),
            creationflags=getattr(subprocess, "DETACHED_PROCESS", 0) | 0,
        )
        return True
    except Exception:  # noqa: BLE001
        return False


def main():
    if not RUNTIME_OK:
        if _bootstrap_with_correct_python():
            print("[提示] 已用 catia311（Python 3.11）重新启动。")
            return 0
        print("=" * 62)
        print("[环境不对] 本程序需要 Anaconda 的 catia311 环境（Python 3.11 + pycatia）")
        print(RUNTIME_MSG.strip())
        print("最省事的办法：双击同目录的「启动器.bat」")
        print("=" * 62)
        try:
            from tkinter import Tk as _Tk, messagebox as _mb
            _r = _Tk()
            _r.withdraw()
            _mb.showerror(
                "环境不对",
                "请使用 Anaconda 的 catia311 环境（Python 3.11）运行本程序。\n\n"
                "最省事的办法：双击同目录的「启动器.bat」。\n\n" + RUNTIME_MSG,
            )
            _r.destroy()
        except Exception:  # noqa: BLE001
            pass
        return 1

    # 不做 DPI 感知：让 Windows 统一缩放，Tk 用逻辑像素，配合固定窗口尺寸+可滚动左栏
    root = Tk()
    Launcher(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
