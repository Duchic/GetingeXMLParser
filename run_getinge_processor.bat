@echo off
setlocal

rem Nastaveni produkcnich cest
set "APP_DIR=%~dp0"
set "PYTHON=python"
set "ROOT=D:\TDOC_Export"
set "LOG_DIR=%ROOT%\processor_logs"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

cd /d "%APP_DIR%"
"%PYTHON%" "%APP_DIR%xml_report_processor.py" --root "%ROOT%" --interval-seconds 600 --log-file "%LOG_DIR%\processor.log"

endlocal
