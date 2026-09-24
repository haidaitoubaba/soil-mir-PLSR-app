@echo off
setlocal
set "ROOT=%~dp0"
cd /d "%ROOT%"

echo.
echo Soil MIR PLSR launcher
echo Platform: Windows
echo.

if defined PYTHON_BIN goto custom_python

where py >nul 2>&1
if not errorlevel 1 goto try_py

goto try_python

:try_py
py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if errorlevel 1 goto try_python
py -3 "%ROOT%scripts\launch_app.py"
set "EXIT_CODE=%ERRORLEVEL%"
goto finish

:try_python
where python >nul 2>&1
if errorlevel 1 goto missing_python
python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if errorlevel 1 goto unsupported_python
python "%ROOT%scripts\launch_app.py"
set "EXIT_CODE=%ERRORLEVEL%"
goto finish

:custom_python
"%PYTHON_BIN%" "%ROOT%scripts\launch_app.py"
set "EXIT_CODE=%ERRORLEVEL%"
goto finish

:missing_python
echo Python 3 was not found.
echo Install Python 3.10 or newer, then reopen run_app.bat.
pause
exit /b 1

:unsupported_python
echo Python was found, but Soil MIR requires Python 3.10 or newer.
echo Install a supported Python version, then reopen run_app.bat.
pause
exit /b 1

:finish
if not "%EXIT_CODE%"=="0" (
  echo.
  echo Soil MIR could not start. Exit code: %EXIT_CODE%
  echo You can copy this window output when reporting the problem.
  pause
)
exit /b %EXIT_CODE%
