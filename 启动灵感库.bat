@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 正在启动灵感工具箱…
start "" http://127.0.0.1:8756
python -m src.run serve
pause
