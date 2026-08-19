@echo off
setlocal

set "APP_DIR=%~dp0"
set "ROOT=D:\TDOC_Export"
set "LOG_DIR=%ROOT%\processor_logs"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

cd /d "%APP_DIR%"
python "%APP_DIR%xml_report_processor.py" --root "%ROOT%" --once --log-file "%LOG_DIR%\test_once.log"

pause
endlocal
