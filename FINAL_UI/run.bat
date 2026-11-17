@echo off
rem Double-click launcher (Windows). Pass -Repo C:\path\to\repo to choose the pipeline repo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1" %*
pause
