# Build and Local Setup

This repository deliberately does **not** commit BAT files, the virtual environment, generated output or downloaded model/dependency files.

The `.gitignore` contains `*.bat`, so the launchers below remain local even after you create them.

## 1. Install prerequisites

Install:

- Windows 10 or 11
- Python 3.12 (64-bit)
- A current NVIDIA driver
- Git/GitHub Desktop if you are cloning the repository from GitHub

During Python installation, enabling the Python Launcher (`py`) is recommended.

## 2. Create `install.bat`

Create a file named `install.bat` in the repository root and paste in the following:

```bat
@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ============================================================
echo Chatterbox Turbo Voice Cloner - Install
echo ============================================================
echo.

REM Prefer the Windows Python Launcher with Python 3.12.
py -3.12 -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)" >nul 2>nul
if not errorlevel 1 (
    set "PYLAUNCH=py -3.12"
    goto python_ok
)

REM Fall back to python.exe if it is already Python 3.12.
python -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)" >nul 2>nul
if errorlevel 1 (
    echo ERROR: Python 3.12 was not found.
    echo Install 64-bit Python 3.12 and try again.
    pause
    exit /b 1
)
set "PYLAUNCH=python"

:python_ok
if not exist ".venv\Scripts\python.exe" (
    echo Creating local virtual environment...
    %PYLAUNCH% -m venv .venv
    if errorlevel 1 goto fail
)

set "PY=.venv\Scripts\python.exe"

echo.
echo Updating pip tooling...
"%PY%" -m pip install --upgrade pip setuptools wheel
if errorlevel 1 goto fail

echo.
echo Installing Chatterbox Turbo and application dependencies...
"%PY%" -m pip install "chatterbox-tts==0.1.7" "sounddevice>=0.5.0" "soundfile>=0.12.1"
if errorlevel 1 goto fail

echo.
echo Installing the tested CUDA 12.8 PyTorch build...
REM Chatterbox currently pins an older torch version upstream. This project
REM replaces it with the CUDA 12.8 build used by the tested Windows setup.
"%PY%" -m pip install --upgrade --force-reinstall torch==2.7.1 torchaudio==2.7.1 --index-url https://download.pytorch.org/whl/cu128
if errorlevel 1 goto fail

echo.
echo Verifying CUDA...
"%PY%" verify_gpu.py
if errorlevel 1 goto fail

echo.
echo ============================================================
echo Install complete.
echo Create/run run.bat to launch the application.
echo ============================================================
pause
exit /b 0

:fail
echo.
echo Installation failed. Review the error above.
pause
exit /b 1
```

### What the installer does

It creates `.venv`, installs the Python packages and verifies that PyTorch can execute a CUDA operation on your NVIDIA GPU. The environment and downloaded dependencies remain local and are ignored by Git.

The first Chatterbox model load can also download model files into the normal model/cache location used by its dependencies. Those files are not stored in this repository.

## 3. Create `run.bat`

Create `run.bat` in the repository root:

```bat
@echo off
cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
    echo Chatterbox Voice Cloner is not installed yet.
    echo Run install.bat first.
    pause
    exit /b 1
)

start "" ".venv\Scripts\pythonw.exe" "voice_cloner.pyw"
```

`pythonw.exe` starts the GUI without leaving a console window open.

## 4. Optional: create `run_console.bat`

If the GUI closes immediately or appears not to launch, create this local troubleshooting launcher:

```bat
@echo off
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Run install.bat first.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" "voice_cloner.pyw"
pause
```

This keeps the console visible so Python/import/CUDA errors can be read directly.

## 5. Launch

Run:

```text
run.bat
```

On first use, model loading can take longer because required model files may need to be downloaded and cached locally.

## Updating dependencies later

Do not commit `.venv` or the model cache. To refresh the local environment, either update packages inside `.venv` or delete `.venv` and run `install.bat` again.

Because the current working setup deliberately overrides Chatterbox's upstream PyTorch pin with PyTorch 2.7.1 + CUDA 12.8, test dependency upgrades before changing the documented versions.

## Git check before publishing

From the repo folder, these should **not** appear as files ready to commit:

```text
install.bat
run.bat
run_console.bat
.venv/
output/
logs/
recordings/
```

The source code, reference voices, documentation and screenshots are the intended Git content.
