@echo off
echo ========================================
echo AI Lightning Node - Build Script
echo ========================================
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found!
    echo Install Python from https://www.python.org/
    pause
    exit /b 1
)

REM Create virtual environment
if not exist "venv" (
    echo Creating virtual environment...
    python -m venv venv
)

REM Activate venv
call venv\Scripts\activate.bat

REM Install dependencies
echo.
echo Installing dependencies...
pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller

REM Read version from version.py
for /f "tokens=2 delims== " %%a in ('findstr /C:"VERSION = " version.py') do set VERSION=%%~a

REM Build exe
echo.
echo Building executable (version %VERSION%)...
pyinstaller --clean build.spec

echo.
echo ========================================
if exist "dist\LightPhon-Node.exe" (
    echo BUILD COMPLETED!
    echo The executable is located at: dist\LightPhon-Node.exe
    
    REM Copy to releases folder with version name
    if not exist "..\server\static\releases" mkdir "..\server\static\releases"
    copy /Y "dist\LightPhon-Node.exe" "..\server\static\releases\LightPhon-Node-%VERSION%.exe"
    echo.
    echo Copied to: server\static\releases\LightPhon-Node-%VERSION%.exe
)
echo ========================================
pause
