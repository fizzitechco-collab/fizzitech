@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
title LegendClipper - HP Victus Update + Setup
color 0B

echo ===============================================================
echo  LEGENDCLIPPER - HP VICTUS ONE-CLICK SETUP (LATEST)
echo ===============================================================
echo Folder: %CD%
echo.
echo This updates Python dependencies and checks FFmpeg, Deno and ngrok.
echo This NEVER deletes or overwrites .env, data, videos or accounts.
echo Original recording and video segment workflows are preserved.
echo.
echo IMPORTANT: Stop any old LegendClipper server before installing.
echo.

if not exist "requirements.txt" (
  echo [ERROR] requirements.txt was not found.
  echo Put this BAT file in the LegendClipper project root folder.
  goto :failed
)
if not exist "studio\server.py" (
  echo [ERROR] studio\server.py was not found.
  goto :failed
)
if not exist "studio\source_quality.py" (
  echo [ERROR] This is an OLD LegendClipper source checkout.
  echo First update the GitHub feature branch using PowerShell:
  echo   git fetch origin
  echo   git switch legend/facecam-preview-audio-repair
  echo   git pull --ff-only origin legend/facecam-preview-audio-repair
  echo Then run this BAT again. Your .env and data stay unchanged.
  goto :failed
)
if exist ".git" (
  echo [1/8] Git repository found.
  git branch --show-current
  echo Installer will NOT change Git branches or overwrite local edits.
  echo.
) else (
  echo [1/8] No .git folder: a copied project was detected.
  echo [NOTE] Future updates require a Git clone of the same repository.
  echo.
)

echo [2/8] Locating Python 3.11...
call :findpython
if not defined PY311 (
  echo Python 3.11 not found. Trying Windows Package Manager...
  call :checkwinget
  if errorlevel 1 goto :failed
  winget install --exact --id Python.Python.3.11 --source winget --accept-package-agreements --accept-source-agreements
  if errorlevel 1 echo [WARNING] Python installation may need approval or a restart.
  call :findpython
)
if not defined PY311 (
  echo [ERROR] Python 3.11 is still unavailable. Restart Windows and run this BAT again.
  goto :failed
)
echo Python executable: %PY311%

echo [3/8] Creating or reusing virtual environment...
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -c "import sys; assert sys.version_info[:2] == (3,11)" >nul 2>&1
  if errorlevel 1 (
    echo [ERROR] Existing .venv is NOT Python 3.11.
    echo Rename it to .venv-old yourself, then rerun; your existing environment was untouched.
    goto :failed
  )
) else (
  "%PY311%" -m venv ".venv"
  if errorlevel 1 goto :failed
)

echo [4/8] Updating only the packages required by this checkout...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :failed
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :failed
".venv\Scripts\python.exe" -c "import fastapi, sqlalchemy, uvicorn, numpy, yt_dlp, sherpa_onnx; print('Python packages: OK')"
if errorlevel 1 goto :failed

echo [5/8] Checking FFmpeg and FFprobe...
where ffmpeg >nul 2>&1
if errorlevel 1 (
  call :checkwinget
  if errorlevel 1 goto :failed
  winget install --exact --id Gyan.FFmpeg --source winget --accept-package-agreements --accept-source-agreements
)
where ffmpeg >nul 2>&1
if errorlevel 1 (
  echo [ERROR] FFmpeg not on PATH. Restart Windows and run this BAT again.
  goto :failed
)
where ffprobe >nul 2>&1
if errorlevel 1 (
  echo [ERROR] FFprobe not on PATH. Check your FFmpeg installation.
  goto :failed
)
ffmpeg -hide_banner -version | findstr /C:"ffmpeg version"
ffmpeg -hide_banner -encoders 2>nul | findstr /C:"h264_nvenc" >nul
if errorlevel 1 (
  echo [NOTE] FFmpeg did not advertise h264_nvenc. CPU encoding remains available.
) else (
  echo NVIDIA NVENC codec reported by FFmpeg.
)

echo [6/8] Checking Deno for current YouTube playback challenges...
where deno >nul 2>&1
if errorlevel 1 (
  call :checkwinget
  if errorlevel 1 goto :failed
  winget install --exact --id DenoLand.Deno --source winget --accept-package-agreements --accept-source-agreements
)
where deno >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Deno not on PATH. Restart Windows, then run this BAT again.
  goto :failed
)
deno --version

echo [7/8] Checking ngrok tunnel tool...
if exist "ngrok.exe" goto :ngrok_found
where ngrok >nul 2>&1
if errorlevel 1 (
  call :checkwinget
  if errorlevel 1 goto :failed
  winget install --exact --id Ngrok.Ngrok --source winget --accept-package-agreements --accept-source-agreements
)
:ngrok_found
if exist "ngrok.exe" goto :ngrok_ready
where ngrok >nul 2>&1
if errorlevel 1 (
  echo [ERROR] ngrok not on PATH. Restart Windows or put ngrok.exe in this folder.
  goto :failed
)
:ngrok_ready
echo ngrok: found. Configure its token on this laptop if needed.

echo [8/8] Lightweight source and setup checks...
".venv\Scripts\python.exe" -m compileall -q studio
if errorlevel 1 (
  echo [ERROR] Python compilation failed.
  goto :failed
)
".venv\Scripts\python.exe" tests\test_source_quality.py
if errorlevel 1 (
  echo [ERROR] Auto/4K source quality regression check failed.
  goto :failed
)
".venv\Scripts\python.exe" tests\test_smart_audio.py
if errorlevel 1 (
  echo [ERROR] Smart audio and facecam regression check failed.
  goto :failed
)
where nvidia-smi >nul 2>&1
if not errorlevel 1 nvidia-smi --query-gpu=name,memory.total --format=csv,noheader

if not exist ".env" (
  echo [WARNING] .env missing. Copy your OWN private .env into this project.
)
if not exist "start.bat" (
  echo [WARNING] start.bat not found. Keep/copy your existing LegendClipper launcher.
)

echo.
echo ===============================================================
echo   HP VICTUS SETUP COMPLETED - BASIC CHECKS PASSED
echo ===============================================================
echo - The .env and data folder were not edited.
echo - Full tests are optional: .venv\Scripts\python.exe tests\run.py
echo - Set ngrok token once: ngrok config add-authtoken YOUR_TOKEN
echo - Do not run the SAME ngrok domain from two laptops together.
echo - To move your old recordings/accounts, stop the old server and
echo   copy the old data folder safely before starting the new server.
echo - This installer only prepares the laptop; it DOES NOT start servers.
echo - For automatic 4K matching choose Auto in Export quality.
echo ===============================================================
pause
exit /b 0

:findpython
set "PY311="
where py >nul 2>&1
if not errorlevel 1 (
  py -3.11 -c "import sys; assert sys.version_info[:2] == (3,11)" >nul 2>&1
  if not errorlevel 1 (
    for /f "delims=" %%P in ('py -3.11 -c "import sys; print(sys.executable)" 2^>nul') do set "PY311=%%P"
  )
)
if defined PY311 exit /b 0
for %%P in ("%LOCALAPPDATA%\Programs\Python\Python311\python.exe" "%ProgramFiles%\Python311\python.exe" "%ProgramFiles(x86)%\Python311\python.exe") do (
  if not defined PY311 if exist "%%~P" (
    "%%~P" -c "import sys; assert sys.version_info[:2] == (3,11)" >nul 2>&1
    if not errorlevel 1 set "PY311=%%~P"
  )
)
exit /b 0

:checkwinget
where winget >nul 2>&1
if errorlevel 1 (
  echo [ERROR] winget is missing. Install Microsoft App Installer, then try again.
  echo https://aka.ms/getwinget
  exit /b 1
)
exit /b 0

:failed
echo.
echo [SETUP INCOMPLETE] Fix the error above and run this BAT again.
echo Nothing in your .env or data folder was deleted or reset.
pause
exit /b 1
