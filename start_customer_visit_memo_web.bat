@echo off
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py customer_visit_memo_web.py
) else (
  python customer_visit_memo_web.py
)
pause
