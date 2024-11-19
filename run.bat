@echo off
setlocal enabledelayedexpansion

:: PixelLlama info
echo PixelLlama - version 0.95b
echo Launching...

:: Set the name of your virtual environment
set VENV_NAME=.env

:: Check if the virtual environment exists by looking for pyvenv.cfg
if not exist %VENV_NAME%\Scripts\python.exe (
    echo Creating virtual environment...
    python -m venv %VENV_NAME%
)

:: Activate the virtual environment
call %VENV_NAME%\Scripts\activate.bat

:: Check if required packages are installed by comparing installed versions
for %%i in (PyQt6 PyQt6-WebEngine requests) do (
    pip show %%i >nul 2>&1
    if errorlevel 1 (
        set need_install=1
    )
)

:: Check if requirements are installed
set REQUIREMENTS_FILE=requirements.txt

:: Install or upgrade the required packages only if needed
if defined need_install (
    echo Installing/Upgrading required packages...
    pip install -r requirements.txt
)

:: Run the Python script using pythonw
echo Running...
start "" pythonw main.py %*

:: Deactivate the virtual environment
deactivate

:: Exit the batch file (closes the terminal)
exit
