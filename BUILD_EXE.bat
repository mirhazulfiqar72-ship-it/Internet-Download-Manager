@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Internet Download Manager 1.4.9 - Fast Startup Builder

echo ==========================================
echo Internet Download Manager 1.4.9 FAST STARTUP
echo Robust Python environment + ONEDIR build
echo ==========================================

set "PIP_OPTS=--disable-pip-version-check --timeout 180 --retries 10"

rem Remove a broken/incomplete virtual environment automatically.
if exist "%LOCALAPPDATA%\IDMBuildEnv\Scripts\python.exe" (
  "%LOCALAPPDATA%\IDMBuildEnv\Scripts\python.exe" -c "import sys; print(sys.executable)" >nul 2>&1
  if errorlevel 1 (
    echo Repairing broken .venv...
    rmdir /s /q "%LOCALAPPDATA%\IDMBuildEnv"
  )
)

rem Find a working system Python. Prefer py launcher, then python.
set "SYS_PY="
where py >nul 2>&1
if not errorlevel 1 set "SYS_PY=py"
if not defined SYS_PY (
  where python >nul 2>&1
  if not errorlevel 1 set "SYS_PY=python"
)
if not defined SYS_PY (
  echo ERROR: Python 3.10+ was not found.
  echo Install Python from https://www.python.org/downloads/windows/
  echo Make sure "Add python.exe to PATH" is enabled.
  goto :fail
)

if not exist "%LOCALAPPDATA%\IDMBuildEnv\Scripts\python.exe" (
  echo Creating clean virtual environment...
  %SYS_PY% -m venv "%LOCALAPPDATA%\IDMBuildEnv"
  if errorlevel 1 goto :venvfail
)

set "PY=%LOCALAPPDATA%\IDMBuildEnv\Scripts\python.exe"
"%PY%" -c "import sys; assert sys.version_info >= (3,10); print('Using Python', sys.version)" || goto :venvfail

echo Installing/updating build requirements...
"%PY%" -m pip install %PIP_OPTS% --upgrade pip setuptools wheel || goto :fail
"%PY%" -m pip install %PIP_OPTS% --prefer-binary "requests>=2.32,<3" "pyinstaller>=6.0,<7" "PySide6>=6.8,<7" "yt-dlp[default]>=2026.8.19,<2027" "imageio-ffmpeg>=0.6,<1" || goto :fail

"%PY%" VERIFY_SOURCE.py || goto :fail

if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo Building FAST STARTUP folder...
"%PY%" -m PyInstaller --noconfirm --clean --onedir --windowed --name InternetDownloadManager --icon assets\app_icon.ico --add-data "assets\app_icon.png;assets" ^
 --hidden-import PySide6.QtCore --hidden-import PySide6.QtGui --hidden-import PySide6.QtWidgets ^
 --hidden-import idm.media --hidden-import idm.update --collect-submodules yt_dlp --collect-data yt_dlp --collect-all yt_dlp_ejs --collect-data imageio_ffmpeg ^
 --exclude-module PySide6.Qt3DAnimation --exclude-module PySide6.Qt3DCore --exclude-module PySide6.Qt3DExtras --exclude-module PySide6.Qt3DInput --exclude-module PySide6.Qt3DLogic --exclude-module PySide6.Qt3DRender ^
 --exclude-module PySide6.QtBluetooth --exclude-module PySide6.QtCharts --exclude-module PySide6.QtDataVisualization --exclude-module PySide6.QtDesigner --exclude-module PySide6.QtGraphs --exclude-module PySide6.QtLocation ^
 --exclude-module PySide6.QtMultimedia --exclude-module PySide6.QtMultimediaWidgets --exclude-module PySide6.QtNfc --exclude-module PySide6.QtNetworkAuth --exclude-module PySide6.QtOpenGL --exclude-module PySide6.QtOpenGLWidgets --exclude-module PySide6.QtPdf --exclude-module PySide6.QtPdfWidgets --exclude-module PySide6.QtPositioning --exclude-module PySide6.QtPrintSupport --exclude-module PySide6.QtQuick --exclude-module PySide6.QtQuickControls2 --exclude-module PySide6.QtQuickWidgets --exclude-module PySide6.QtQml --exclude-module PySide6.QtRemoteObjects --exclude-module PySide6.QtScxml --exclude-module PySide6.QtSensors --exclude-module PySide6.QtSerialBus --exclude-module PySide6.QtSerialPort --exclude-module PySide6.QtSpatialAudio --exclude-module PySide6.QtSql --exclude-module PySide6.QtStateMachine --exclude-module PySide6.QtSvg --exclude-module PySide6.QtSvgWidgets --exclude-module PySide6.QtTest --exclude-module PySide6.QtTextToSpeech --exclude-module PySide6.QtUiTools --exclude-module PySide6.QtWebChannel --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtWebEngineWidgets --exclude-module PySide6.QtWebView --exclude-module PySide6.QtXml main.py || goto :fail

if not exist "dist\InternetDownloadManager\InternetDownloadManager.exe" goto :fail
if exist build rmdir /s /q build

echo.
echo ==========================================
echo BUILD SUCCESSFUL
echo ==========================================
echo Run:
echo dist\InternetDownloadManager\InternetDownloadManager.exe
echo.
echo IMPORTANT: Keep the complete InternetDownloadManager folder together.
exit /b 0

:venvfail
echo.
echo ERROR: Python virtual environment could not be created or is broken.
echo Delete the .venv folder manually and run BUILD_EXE.bat again.
echo If it still fails, repair/reinstall Python and enable the Python launcher/PATH.
goto :fail

:fail
echo.
echo BUILD FAILED
exit /b 1
