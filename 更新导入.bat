@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 【1/2】导入新截图/文字/文档（本地，不联网）…
python -m src.run ingest
echo.
echo 【2/2】AI 分类（需已在 secrets.json 填好 DeepSeek key）…
python -m src.run classify
echo.
echo 完成。可运行"启动灵感库.bat"查看。
pause
