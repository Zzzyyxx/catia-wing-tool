# Installation Guide (English)

CATIA Wing Tool drives **CATIA V5** through COM automation (via `pycatia`), so the
runtime must live on the **same Windows machine** as your CATIA installation.

---

## Requirements

| Item | Requirement | Why |
|---|---|---|
| OS | Windows | COM automation + tkinter GUI |
| CAD | **CATIA V5**, launchable, COM registered as `CATIA.Application` | we drive it over COM |
| Python | **3.11** (64-bit if your CATIA is 64-bit) | `pywin32` has no wheels for 3.13/3.14 yet |
| Packages | `pycatia` (0.10.x, pulls in `pywin32`) | the CATIA wrapper |

Check the COM registration:

```powershell
Get-ItemProperty "Registry::HKEY_CLASSES_ROOT\CATIA.Application\CLSID" | Select-Object '(default)'
```

If that returns a GUID, automation is available. If the path is missing, CATIA is not
installed/registered properly (or it is a build without V5 automation).

---

## Route A — Anaconda / Miniconda (recommended)

```bat
conda create -n catia311 python=3.11 -y
conda activate catia311
python -m pip install pycatia
python -c "import pycatia, win32com; print('OK')"
```

Then point the launcher at that interpreter (only needed if your env is not in the
default Anaconda location):

```powershell
setx CATIA_PY "D:\Miniconda3\envs\catia311\python.exe"
```

`启动器.bat` resolves the interpreter in this order:
`CATIA_PY` → `%USERPROFILE%\anaconda3\envs\catia311` → `%ProgramData%\anaconda3\...` →
`python` on `PATH`.

---

## Route B — python.org + venv (no Anaconda)

1. Install **Python 3.11 (64-bit)** from <https://www.python.org/downloads/release/python-3119/>
   — tick **"Add python.exe to PATH"**.
2. Create a venv and install:

```bat
cd /d D:\CATIA_Wing_Tool
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install pycatia
```

3. Register it:

```powershell
setx CATIA_PY "D:\CATIA_Wing_Tool\.venv\Scripts\python.exe"
```

Open a **new** terminal afterwards (environment variables are read at process start).

---

## Route C — one-click script in this repo

If `conda` is already installed, just double-click:

```
工具\安装环境.bat
```

It will (idempotently): create the `catia311` env → install `pycatia` (via the Tsinghua
mirror) → set `CATIA_PY` → run the self-test. Needs network; ~1–3 min.

---

## Verify the installation

Double-click **`工具\环境检查.bat`**. It checks, in order:

1. the interpreter is Python 3.11
2. `import pycatia` works
3. connecting to `CATIA.Application` works
4. creating a Part / points / a multi-section surface / knowledge parameters works

All green → ready. **The first connection cold-starts CATIA (~15 s)** — do not treat
that as a hang.

You can also run the probe directly:

```bat
"%CATIA_PY%" 工具\catia_probe.py
```

---

## One-time CATIA setting (otherwise you cannot see the parameters)

CATIA hides the **Parameters / Relations** tree nodes by default:

**Tools → Options → Infrastructure → Part Infrastructure → Display** →
tick **Parameters** and **Relations** → OK.

After that the design tree shows `参数` (double-click a row to edit) and `关系`
(the formula list). After editing a parameter press **Ctrl+U** (Update) to rebuild.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `ModuleNotFoundError: No module named 'pycatia'` | installed into another interpreter | `"%CATIA_PY%" -m pip install pycatia` |
| `pip install pywin32` build error | Python 3.13/3.14 | use Python **3.11** |
| `pywintypes.com_error: invalid class string` | CATIA missing / COM not registered / bitness mismatch | verify CATIA launches; match 64-bit Python with 64-bit CATIA |
| `pywintypes.com_error: server execution failed` | CATIA hung (often after being force-killed) | kill `CNEXT.exe` in Task Manager, retry |
| `方法 Update 失败` during build | invalid geometry, **not** an env issue | read the stage name in the dialog and `logs\build_*.log` |
| `方法 SaveAs 失败` | path contains non-ASCII characters | move the project to an ASCII path (the tool also retries via a temp file) |
| pip downloads are very slow | default index is far | `-i https://pypi.tuna.tsinghua.edu.cn/simple` |
| `Bad magic number in .pyc file` | several Python versions mixed up | delete `__pycache__`; launch via `启动器.bat` |

---

## Uninstall / cleanup

```bat
conda env remove -n catia311
:: or
rmdir /s /q D:\CATIA_Wing_Tool\.venv
:: clear the variable
setx CATIA_PY ""
```

The tool writes nothing outside the project folder (except `CATIA_PY` and the generated
`logs\` / `output\` files).
