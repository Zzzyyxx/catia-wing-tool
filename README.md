# CATIA Wing Tool · CATIA 机翼参数化建模

> Generate a parametric aircraft wing inside **CATIA V5** from a handful of engineering
> parameters — via a small desktop GUI or a Python/pycatia script.
> 用一组工程参数在 CATIA V5 里自动生成参数化机翼。

Input an airfoil `.dat` plus root chord, span, quarter-chord sweep, taper ratio, incidence and
geometric twist → get a closed design tree with `Parameters / Relations / Airfoil library /
Construction / Wing / Ribs / Pose`, optionally sliced rib sections, symmetry, and XYZ
rotation/translation that stay editable (formula-driven) inside CATIA.

![wing](output/wing_CH10.jpg)

---

## 快速开始（30 秒）

```text
1. 解压到纯英文路径（如 D:\CATIA_Wing_Tool）   ※ CATIA 的 SaveAs 不支持中文路径
2. 双击 启动器.bat
3. 点「导入 .dat」→ 选 airfoils\CH10.dat
4. 参数保持默认：弦长 100 / 展长 500 / 后掠 30° / 梢根比 0.45 / 安装角 10° / 扭转 10° / 截面 7
5. 点「⚡ 生成机翼模型」→ 切到 CATIA 看设计树
```

命令行也支持：

```bat
python wing_builder.py --config configs\example_basic.json
python wing_builder.py --config configs\example_basic.json --dry-run
```

---

## 环境要求

| 项 | 值 |
|---|---|
| Python | **3.11**（推荐 conda 环境，名字随意，下文以 `catia311` 为例） |
| 依赖 | `pycatia`（0.10.x）、`pywin32` |
| CAD | CATIA V5（已注册 COM：`CATIA.Application`） |
| 系统 | Windows（COM 自动化 + tkinter 界面） |

```powershell
conda create -n catia311 python=3.11 -y
conda activate catia311
python -m pip install pycatia
```

自检：双击 `工具\环境检查.bat`，会依次检查解释器、`pycatia` 导入、以及建 Part / 建点 /
建多截面曲面 / 知识工程参数等接口是否可用。

> 不需要手动先开 CATIA —— 程序通过 COM 拉起（冷启动约 15 秒）。

`启动器.bat` 的 Python 查找顺序：环境变量 `CATIA_PY` → 本机已装的 `catia311` 路径 →
PATH 上的 `python`。换机器时最省事的做法是设一个 `CATIA_PY`。

---

## 目录结构

| 路径 | 说明 |
|---|---|
| `启动器.bat` | 双击启动（自动寻找 Python 3.11 + pycatia） |
| `launcher.py` | 图形界面：导入翼型 → 填参数 → 生成 → 实时日志 / 俯视预览 |
| `wing_builder.py` | 建模核心：参数与公式、翼型解析、截面、多截面曲面、翼肋、对称与姿态 |
| `使用说明.md` | 详细说明书（界面、数据格式、报错对照、JSON 字段、限制） |
| `airfoils/` | 翼型库：`CH10.dat`（XFLR5 三列格式示例）、`NACA0018.dat` |
| `configs/` | 示例配置：`example_basic` / `example_with_ribs` / `example_pose` |
| `output/` | 生成的 `.CATPart` 与截图（含示例成品） |
| `文档/` | 技术文档：接口实测与可行性分析、参考视频的建模流程笔记 |
| `工具/` | 环境检查脚本 + 两个 CATIA 自动化探针 |
| `logs/` | 运行日志（每次生成自动写入，已 gitignore） |

---

## 设计树长什么样

```
参数      翼型选择器 / 翼根弦长 / 翼展展长 / 后掠角 / 几何扭转 / 梢根比 / 展弦比 / 安装角
          + 对称开关 / 绕X·Y·Z旋转 / 平移X·Y·Z
关系      展弦比公式、翼型缩放公式、姿态类公式…
翼型库    以文件名命名的草图 + 缩放（比率由 翼根弦长 驱动）
实现过程  截面_01…NN（多截面路线）/ 前缘·后缘引导线 + 脊线（扫掠路线）
机翼      多截面曲面（或扫掠）
翼肋      顺气流截面 + 镜像（可选）
姿态与定位 对称 / X·Y·Z 轴 / 旋转Z·Y·X / 平移X·Y·Z
```

姿态与对称是**公式驱动**的：在 CATIA 里改 `绕Z旋转`、`平移X` 等参数，`Update` 后几何立即跟随。
弦长/展长/梢根比等截面尺寸目前需要重跑脚本（详见 `使用说明.md` §五之二 的升级路线）。

---

## 支持的翼型文件格式

- 两列 `x y`（Tab / 空格 / 逗号 / 分号分隔）
- **XFLR5 三列 `x  0  z`**（真实厚度在第 3 列，自动识别）
- 带表头 / 注释行（自动跳过）
- 坐标带单位（弦长 > 1.5 自动归一化）
- 首尾重复点、连续重复点（自动去重）
- "蝴蝶结"点序（上表面走完再下表面，自动重排成单环）

---

## 常见问题

| 现象 | 处理 |
|---|---|
| `Bad magic number in .pyc file` | 用错了 Python 版本；删 `__pycache__`，双击 `launcher.py` 会自动切到 3.11 |
| 弹窗「环境不对」 | 解释器不是 3.11 且找不到 conda 环境，改用 `启动器.bat` 或设 `CATIA_PY` |
| 弹窗「阶段「xxx」失败」 | 看弹窗里的提示 + 参数快照；完整日志在 `logs\build_*.log` |
| `方法 SaveAs 失败` | 路径含中文/特殊字符 → 挪到英文路径（工具也有临时文件中转兜底） |
| 生成很慢 | 截面数或翼肋太多（每点一次 COM 调用）：截面 7~11、翼肋间距 ≥ 20 mm |
| 翼肋"位置看着不对" | 那几片薄片是**翼肋平面**（切片基准面），翼肋是贴合翼面的曲线 |

---

## 已知限制

- 只输出**曲面**，不含实体；曲面质量检查（斑马线 / 曲率梳）需人工在 CATIA 里做；
- 改弦长 / 展长 / 梢根比 / 扭转 / 截面数 需要重跑脚本（公式驱动项除外）；
- 依赖 CATIA V5 的 COM 自动化，无法在无 CATIA 的机器上运行；
- 高 DPI 下俯视预览的图形位置可能略偏（观感问题，不影响生成）。

---

## 文档

1. `README.md` —— 本文件
2. `使用说明.md` —— 主说明书
3. `文档/机翼参数化建模_可行性分析.md` —— 技术分析、接口实测数据、踩坑记录、升级路线
4. `文档/NPU-WishYu_建模流程笔记.md` —— 参考视频六集的建模流程提炼与对照

---

## 免责声明

本项目只调用 CATIA 公开的自动化接口，不包含、不修改任何 Dassault Systèmes 组件。
CATIA、pycatia 各自遵循其原始许可。

*本地工具，无遥测；几何全部生成在你自己的 CATIA 里。*
