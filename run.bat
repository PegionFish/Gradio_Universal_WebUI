@echo off
chcp 65001 >nul
title Gradio Universal WebUI

echo ============================================
echo   Gradio Universal AI WebUI
echo ============================================
echo.

:: 检查 Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 Python。请安装 Python 3.10+ 并添加到 PATH。
    pause
    exit /b 1
)

:: 检查核心依赖（快速导入测试）
python -c "import gradio, yaml, aiohttp" >nul 2>&1
if %errorlevel% neq 0 (
    echo [提示] 正在安装依赖...
    pip install -q gradio pyyaml aiohttp nvidia-ml-py psutil
    if %errorlevel% neq 0 (
        echo [错误] 依赖安装失败，请手动执行: pip install -r requirements.txt
        pause
        exit /b 1
    )
    echo [完成] 依赖已安装。
)

echo [启动] 正在启动 WebUI...
echo         http://127.0.0.1:7860
echo         按 Ctrl+C 停止
echo.

:: 3 秒后自动打开浏览器
start "" /b cmd /c "timeout /t 3 /nobreak >nul && start http://127.0.0.1:7860"

:: 绕过本地代理（避免 HTTP_PROXY 干扰 localhost 连接）
set NO_PROXY=127.0.0.1,localhost
set no_proxy=127.0.0.1,localhost

:: 启动 WebUI
python main.py --host 127.0.0.1 --port 7860

pause
