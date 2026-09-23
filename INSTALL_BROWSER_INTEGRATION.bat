@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "EXE=%~dp0InternetDownloadManager.exe"
set "HOST_NAME=com.originaldownloadmanager.integration"
set "EXT_ID=degijjganjjjdkgibkndbdemjfnndmne"
set "HOST_DIR=%LOCALAPPDATA%\InternetDownloadManager\BrowserIntegration"
set "HOST_MANIFEST=%HOST_DIR%\%HOST_NAME%.json"

if not exist "%EXE%" (
 exit /b 1
)

if not exist "%HOST_DIR%" mkdir "%HOST_DIR%" >nul 2>&1
set "EXE_JSON=%EXE:\=\\%"

>"%HOST_MANIFEST%" echo {
>>"%HOST_MANIFEST%" echo   "name": "%HOST_NAME%",
>>"%HOST_MANIFEST%" echo   "description": "Internet Download Manager browser integration",
>>"%HOST_MANIFEST%" echo   "path": "%EXE_JSON%",
>>"%HOST_MANIFEST%" echo   "type": "stdio",
>>"%HOST_MANIFEST%" echo   "allowed_origins": ["chrome-extension://%EXT_ID%/"]
>>"%HOST_MANIFEST%" echo }

reg add "HKCU\Software\Google\Chrome\NativeMessagingHosts\%HOST_NAME%" /ve /d "%HOST_MANIFEST%" /f >nul
reg add "HKCU\Software\Microsoft\Edge\NativeMessagingHosts\%HOST_NAME%" /ve /d "%HOST_MANIFEST%" /f >nul

REM Keep the idm:// protocol registered for backwards compatibility/manual use.
set "REG=%TEMP%\idm_protocol_install.reg"
>"%REG%" echo Windows Registry Editor Version 5.00
>>"%REG%" echo.
>>"%REG%" echo [HKEY_CURRENT_USER\Software\Classes\idm]
>>"%REG%" echo @="URL:Internet Download Manager Protocol"
>>"%REG%" echo "URL Protocol"=""
>>"%REG%" echo.
>>"%REG%" echo [HKEY_CURRENT_USER\Software\Classes\idm\shell\open\command]
>>"%REG%" echo @="\"%EXE:\=\\%\" \"%%1\""
reg import "%REG%" >nul
del "%REG%" >nul 2>&1

exit /b 0
