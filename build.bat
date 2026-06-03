@echo off
setlocal enabledelayedexpansion

set "APP_NAME=Koji Report Pet Next"
set "PYI_NAME=KojiReportPetNext"
set "PORTABLE_DIR=dist\KojiReportPetNext_Portable"
set "PYI_DIST=dist\%PYI_NAME%"

echo [Koji] Installing requirements...
python -m pip install -r requirements.txt || exit /b 1

echo [Koji] Running PyInstaller...
python -m PyInstaller --noconfirm --windowed --name "%PYI_NAME%" --add-data "data;data" --add-data "assets;assets" main.py || exit /b 1

echo [Koji] Preparing portable directory...
if exist "%PORTABLE_DIR%" rmdir /s /q "%PORTABLE_DIR%"
mkdir "%PORTABLE_DIR%" || exit /b 1

if exist "%PYI_DIST%\%PYI_NAME%.exe" (
  copy /y "%PYI_DIST%\%PYI_NAME%.exe" "%PORTABLE_DIR%\%APP_NAME%.exe" >nul || exit /b 1
  for /d %%D in ("%PYI_DIST%\*") do xcopy /e /i /y "%%~fD" "%PORTABLE_DIR%\%%~nxD" >nul
  for %%F in ("%PYI_DIST%\*") do if not "%%~nxF"=="%PYI_NAME%.exe" copy /y "%%~fF" "%PORTABLE_DIR%\" >nul
) else if exist "dist\%PYI_NAME%.exe" (
  copy /y "dist\%PYI_NAME%.exe" "%PORTABLE_DIR%\%APP_NAME%.exe" >nul || exit /b 1
) else (
  echo [Koji] PyInstaller output exe not found.
  exit /b 1
)

echo [Koji] Copying assets and data...
if exist assets xcopy /e /i /y assets "%PORTABLE_DIR%\assets" >nul
mkdir "%PORTABLE_DIR%\data" 2>nul
if exist data\koji-dialogues.json copy /y data\koji-dialogues.json "%PORTABLE_DIR%\data\koji-dialogues.json" >nul

echo [Koji] Preparing ai-runtime...
mkdir "%PORTABLE_DIR%\ai-runtime" 2>nul
if exist ai-runtime\.gitkeep copy /y ai-runtime\.gitkeep "%PORTABLE_DIR%\ai-runtime\.gitkeep" >nul
if exist ai-runtime\README_AI_RUNTIME.txt copy /y ai-runtime\README_AI_RUNTIME.txt "%PORTABLE_DIR%\ai-runtime\README_AI_RUNTIME.txt" >nul

if exist ai-runtime\llama-server.exe (
  copy /y ai-runtime\llama-server.exe "%PORTABLE_DIR%\ai-runtime\llama-server.exe" >nul
) else (
  echo [Koji] Missing ai-runtime\llama-server.exe. Add it manually before publishing AI package.
)

if exist ai-runtime\models (
  mkdir "%PORTABLE_DIR%\ai-runtime\models" 2>nul
  xcopy /e /i /y ai-runtime\models "%PORTABLE_DIR%\ai-runtime\models" >nul
) else (
  mkdir "%PORTABLE_DIR%\ai-runtime\models" 2>nul
)

if exist ai-runtime\model_config.json (
  copy /y ai-runtime\model_config.json "%PORTABLE_DIR%\ai-runtime\model_config.json" >nul
)

if exist ai-runtime\model.gguf (
  copy /y ai-runtime\model.gguf "%PORTABLE_DIR%\ai-runtime\model.gguf" >nul
) else (
  if not exist ai-runtime\models\*.gguf echo [Koji] Missing local GGUF model. Add ai-runtime\model.gguf or ai-runtime\models\*.gguf before publishing AI package.
)

if exist README_本地AI版说明.md copy /y README_本地AI版说明.md "%PORTABLE_DIR%\README_本地AI版说明.md" >nul

> "%PORTABLE_DIR%\启动 Koji.bat" echo @echo off
>> "%PORTABLE_DIR%\启动 Koji.bat" echo cd /d "%%~dp0"
>> "%PORTABLE_DIR%\启动 Koji.bat" echo start "" "%APP_NAME%.exe"

echo [Koji] Portable package ready: %PORTABLE_DIR%
endlocal
