@echo off
title CATIA 自动化环境检查
cd /d "%~dp0.."

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

echo ============================================================
echo   CATIA 自动化环境检查
echo ============================================================
echo.

if not defined PY (
    echo [X] 找不到 Python，请安装 Python 3.11 或设置环境变量 CATIA_PY
    goto :end
)
echo [OK] 解释器: %PY%
"%PY%" --version

"%PY%" -c "import pycatia" >nul 2>&1
if errorlevel 1 (
    echo [X] pycatia 未安装
    echo     请执行: "%PY%" -m pip install pycatia
    goto :end
)
echo [OK] pycatia 已安装

echo.
echo --- 连接 CATIA 并验证建模能力（首次会冷启动 CATIA，约 15~60 秒）---
echo.
"%PY%" "工具\catia_probe2.py"

:end
echo.
pause
