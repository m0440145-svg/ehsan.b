@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo تشغيل منصة إدارة المهام ومتابعة القرارات...
".venv\Scripts\python.exe" serve.py
pause
