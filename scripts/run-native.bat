@echo off
rem 双击即可启动原生界面（开发/源码版）。发布包直接双击 starforge.exe，不需要这个文件。
cd /d "%~dp0.."
python -m starforge app
if errorlevel 1 pause
