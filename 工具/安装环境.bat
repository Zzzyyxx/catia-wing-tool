@echo off
chcp 936 >nul
title 安装 CATIA Wing Tool 运行环境
cd /d "%~dp0.."
setlocal

set "ENVNAME=catia311"
set "PYVER=3.11"
set "MIRROR=https://pypi.tuna.tsinghua.edu.cn/simple"

echo ============================================================
echo   CATIA Wing Tool - 环境安装
echo   需要: Windows + CATIA V5 + 网络
echo ============================================================
echo.

rem ---------- 1. 找 conda ----------
where conda >nul 2>&1
if errorlevel 1 (
    echo [X] 没有找到 conda。
    echo.
    echo     两条路走一条：
    echo       1^) 装 Miniconda: https://docs.conda.io/en/latest/miniconda.html
    echo       2^) 已装官方 Python 3.11 的话，手动执行：
    echo            python -m venv .venv
    echo            .venv\Scripts\activate
    echo            python -m pip install pycatia
    echo            setx CATIA_PY "%%CD%%\.venv\Scripts\python.exe"
    echo.
    echo     详见 文档\环境安装指南.md
    pause
    exit /b 1
)
echo [OK] 找到 conda

rem ---------- 2. 建环境 ----------
echo.
call conda env list | findstr /C:"%ENVNAME% " >nul
if not errorlevel 1 (
    echo [1/3] 环境 %ENVNAME% 已存在，跳过创建
) else (
    echo [1/3] 创建 conda 环境 %ENVNAME% ^(Python %PYVER%^) ... 可能要 1~2 分钟
    call conda create -n %ENVNAME% python=%PYVER% -y
    if errorlevel 1 (
        echo [X] 创建环境失败，请看上面的 conda 输出
        pause
        exit /b 1
    )
)

rem ---------- 3. 定位解释器 ----------
set "PY=%USERPROFILE%\anaconda3\envs\%ENVNAME%\python.exe"
if not exist "%PY%" set "PY=%ProgramData%\anaconda3\envs\%ENVNAME%\python.exe"
if not exist "%PY%" (
    echo [X] 找不到刚建好的环境，请手动设置 CATIA_PY
    pause
    exit /b 1
)
echo [OK] 解释器: %PY%
"%PY%" --version

rem ---------- 4. 装 pycatia ----------
echo.
echo [2/3] 安装 pycatia（用清华镜像加速）...
"%PY%" -m pip install --upgrade pip -i %MIRROR%
"%PY%" -m pip install pycatia -i %MIRROR%
if errorlevel 1 (
    echo [X] pycatia 安装失败，试试去掉镜像参数重装：
    echo     "%PY%" -m pip install pycatia
    pause
    exit /b 1
)
echo [OK] pycatia 已安装

rem ---------- 5. 设 CATIA_PY ----------
echo.
echo [3/3] 设置环境变量 CATIA_PY（供 启动器.bat 使用）...
setx CATIA_PY "%PY%" >nul
echo [OK] CATIA_PY = %PY%
echo      注意：新开终端才生效

rem ---------- 6. 自检 ----------
echo.
echo --- 环境自检（会尝试连接 CATIA，首次约 15~60 秒）---
echo.
"%PY%" "工具\catia_probe.py"

echo.
echo ============================================================
echo   完成。现在可以双击 启动器.bat 使用了。
echo   如果自检里 CATIA 那步失败，见 文档\环境安装指南.md
echo ============================================================
pause