@echo off
rem 安全模式：软件 OpenGL，用于排查显卡驱动/远程桌面导致的启动崩溃。
cd /d "%~dp0.."
set STARFORGE_SAFE=1
set QT_OPENGL=software
python -m starforge app --safe
if errorlevel 1 pause
