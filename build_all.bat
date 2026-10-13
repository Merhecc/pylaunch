@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title 批量编译 Python 为 EXE

echo ============================================================
echo             批量编译 Python 程序为 EXE
echo ============================================================
echo.

REM ---- 检查 Python ----
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装并添加到 PATH
    pause
    exit /b 1
)

REM ---- 检查 PyInstaller ----
python -c "import PyInstaller" >nul 2>&1
if errorlevel 1 (
    echo [提示] 正在安装 PyInstaller...
    python -m pip install pyinstaller
    if errorlevel 1 (
        echo [错误] PyInstaller 安装失败
        pause
        exit /b 1
    )
)

REM ---- 清理旧产物 ----
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
del /q *.spec >nul 2>&1

REM ---- 逐个编译 .py 文件 ----
set SUCCESS=0
set FAIL=0

for %%F in (*.py) do (
    REM 跳过本脚本自身（如有）
    if /i not "%%F"=="build_all.py" (
        echo.
        echo ------------------------------------------------------------
        echo [编译] %%F
        echo ------------------------------------------------------------
        python -m PyInstaller --onefile --noconsole --noconfirm --clean "%%F"
        if errorlevel 1 (
            echo [失败] %%F
            set /a FAIL+=1
        ) else (
            echo [成功] %%F
            set /a SUCCESS+=1
        )
    )
)

echo.
echo ============================================================
echo                    编译结果汇总
echo ============================================================
echo   成功: %SUCCESS% 个
echo   失败: %FAIL% 个
echo   输出目录: %cd%\dist
echo ============================================================
echo.

REM ---- 打开输出目录 ----
if exist dist start "" "%cd%\dist"

pause