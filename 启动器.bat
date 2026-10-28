@echo off
chcp 936 >nul
title CATIA Wing Tool - Launcher
cd /d "%~dp0"

rem ---- 查找 Python 3.11 + pycatia ----
rem 1) 环境变量 CATIA_PY  2) 常见 Anaconda 路径  3) PATH 上的 python
set "PY=%CATIA_PY%"

if not defined PY (
    if exist "%USERPROFILE%\anaconda3\envs\catia311\python.exe" set "PY=%USERPROFILE%\anaconda3\envs\catia311\python.exe"
)
if not defined PY (
    if exist "%ProgramData%\anaconda3\envs\catia311\python.exe" set "PY=%ProgramData%\anaconda3\envs\catia311\python.exe"
)
if not defined PY (
    for /f "delims=" %%i in ('where python 2^>nul') do if not defined PY set "PY=%%i"
)

if not defined PY (
    echo [错误] 找不到 Python，请先安装 Python 3.11 或设置环境变量 CATIA_PY
    pause
    exit /b 1
)

echo 使用解释器: %PY%
"%PY%" -c "import sys; print('Python', sys.version.split()[0])"

"%PY%" -c "import pycatia" >nul 2>&1
if errorlevel 1 (
    echo [错误] 该环境里没有 pycatia，请先执行:
    echo   "%PY%" -m pip install pycatia
    pause
    exit /b 1
)

"%PY%" "%~dp0launcher.py"
if errorlevel 1 pause
