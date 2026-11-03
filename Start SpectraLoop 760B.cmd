@echo off
setlocal
set "SPECTRALOOP_ROOT=%~dp0"
set "SPECTRALOOP_PYTHON=%SPECTRALOOP_ROOT%.venv\Scripts\python.exe"
set "SPECTRALOOP_LOCAL_MODE=0"
set "SPECTRALOOP_760B_RUNTIME=%SPECTRALOOP_ROOT%.runtime\chi760b-worker"
if /i "%~1"=="--local" set "SPECTRALOOP_LOCAL_MODE=1"

if exist "%SPECTRALOOP_PYTHON%" goto check_runtime

where py.exe >nul 2>nul
if errorlevel 1 goto python_fallback
set "SPECTRALOOP_PYTHON=py.exe"
set "SPECTRALOOP_PYTHON_ARGS=-3"
goto check_runtime

:python_fallback
where python.exe >nul 2>nul
if errorlevel 1 goto python_missing
set "SPECTRALOOP_PYTHON=python.exe"
set "SPECTRALOOP_PYTHON_ARGS="

:check_runtime
if not exist "%SPECTRALOOP_760B_RUNTIME%\libec760b.dll" goto runtime_missing
if not exist "%SPECTRALOOP_ROOT%.runtime\python-x86\python.exe" goto runtime_missing

:run_bridge
pushd "%SPECTRALOOP_ROOT%CHI760 Potentiostat"
if "%SPECTRALOOP_LOCAL_MODE%"=="1" goto run_local_bridge
"%SPECTRALOOP_PYTHON%" %SPECTRALOOP_PYTHON_ARGS% -B -m chi760.web_bridge --site-dir "%SPECTRALOOP_ROOT%SpectraLoop" --start-page echem --web-url "https://spectraloop.org/echem.html?view=protocol&app=spectraloop-20261103-3" --sdk-dir "%SPECTRALOOP_760B_RUNTIME%" --runtime-dir "%SPECTRALOOP_760B_RUNTIME%" --dll-name "libec760b.dll" --instrument-label "CHI 760B SDK" --enable-chi760b-commissioning
goto bridge_finished

:run_local_bridge
"%SPECTRALOOP_PYTHON%" %SPECTRALOOP_PYTHON_ARGS% -B -m chi760.web_bridge --site-dir "%SPECTRALOOP_ROOT%SpectraLoop" --start-page echem --sdk-dir "%SPECTRALOOP_760B_RUNTIME%" --runtime-dir "%SPECTRALOOP_760B_RUNTIME%" --dll-name "libec760b.dll" --instrument-label "CHI 760B SDK" --enable-chi760b-commissioning

:bridge_finished
set "SPECTRALOOP_EXIT=%ERRORLEVEL%"
popd
if not "%SPECTRALOOP_EXIT%"=="0" pause
exit /b %SPECTRALOOP_EXIT%

:runtime_missing
echo The repository-local CHI 760B worker runtime is incomplete.
echo Expected: %SPECTRALOOP_760B_RUNTIME%\libec760b.dll
echo Run the verified 760B runtime setup before starting this launcher.
pause
exit /b 1

:python_missing
echo Python 3 was not found. Install Python 3, then run this launcher again.
pause
exit /b 1
