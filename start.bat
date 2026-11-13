@echo off
chcp 65001 >nul
cd /d "%~dp0"
where python >nul 2>nul
if %errorlevel%==0 (set "PY=python") else (set "PY=py -3")
echo 正在启动 我的豆瓣 ...
start "" http://127.0.0.1:8601/
%PY% app.py --port 8601
pause
