@echo off
cd /d "%~dp0"
echo Cleaning old local build/cache folders only...
if exist build rmdir /s /q build
if exist __pycache__ rmdir /s /q __pycache__
for /d /r %%D in (__pycache__) do @if exist "%%D" rmdir /s /q "%%D"
if exist .venv (
  echo Removing old project-local .venv (new builds use %%LOCALAPPDATA%%\IDMBuildEnv)...
  rmdir /s /q .venv
)
echo Done. dist is preserved.
pause
