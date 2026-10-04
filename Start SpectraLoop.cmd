@echo off
setlocal
set "SPECTRALOOP_ROOT=%~dp0"
set "SPECTRALOOP_PYTHON=%SPECTRALOOP_ROOT%.venv\Scripts\python.exe"
set "SPECTRALOOP_LOCAL_MODE=0"
if /i "%~1"=="--local" set "SPECTRALOOP_LOCAL_MODE=1"

if exist "%SPECTRALOOP_PYTHON%" goto run_bridge

where py.exe >nul 2>nul
if errorlevel 1 goto python_fallback
set "SPECTRALOOP_PYTHON=py.exe"
set "SPECTRALOOP_PYTHON_ARGS=-3"
goto run_bridge

:python_fallback
where python.exe >nul 2>nul
if errorlevel 1 goto python_missing
set "SPECTRALOOP_PYTHON=python.exe"
set "SPECTRALOOP_PYTHON_ARGS="

:run_bridge
pushd "%SPECTRALOOP_ROOT%CHI760 Potentiostat"
if "%SPECTRALOOP_LOCAL_MODE%"=="1" goto run_local_bridge
"%SPECTRALOOP_PYTHON%" %SPECTRALOOP_PYTHON_ARGS% -B -m chi760.web_bridge --site-dir "%SPECTRALOOP_ROOT%SpectraLoop" --start-page echem --web-url "https://spectraloop.org/echem.html?view=protocol"
goto bridge_finished

:run_local_bridge
"%SPECTRALOOP_PYTHON%" %SPECTRALOOP_PYTHON_ARGS% -B -m chi760.web_bridge --site-dir "%SPECTRALOOP_ROOT%SpectraLoop" --start-page echem

:bridge_finished
set "SPECTRALOOP_EXIT=%ERRORLEVEL%"
popd
if not "%SPECTRALOOP_EXIT%"=="0" pause
exit /b %SPECTRALOOP_EXIT%

:python_missing
echo Python 3 was not found. Install Python 3, then run this launcher again.
pause
exit /b 1
