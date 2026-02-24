@echo off
REM Build script for VXC/ADV Visualizer executable
REM This creates a standalone Windows application

echo ========================================
echo VXC/ADV Visualizer - Build Executable
echo ========================================
echo.

REM Check if PyInstaller is installed
python -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo PyInstaller is not installed!
    echo Installing PyInstaller...
    pip install pyinstaller
    if errorlevel 1 (
        echo ERROR: Failed to install PyInstaller
        pause
        exit /b 1
    )
)

echo Cleaning previous builds...
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"

echo.
echo Building executable with PyInstaller...
echo This may take a few minutes...
echo.

pyinstaller build_exe.spec

if errorlevel 1 (
    echo.
    echo ========================================
    echo BUILD FAILED!
    echo ========================================
    pause
    exit /b 1
)

echo.
echo ========================================
echo BUILD SUCCESSFUL!
echo ========================================
echo.
echo The executable is located in:
echo   dist\VXC_ADV_Visualizer\
echo.
echo To run: dist\VXC_ADV_Visualizer\VXC_ADV_Visualizer.exe
echo.
echo To distribute: Copy the entire "dist\VXC_ADV_Visualizer" folder
echo.

pause
