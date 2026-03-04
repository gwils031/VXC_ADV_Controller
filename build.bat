@echo off
REM Build script for VXC/ADV Visualizer executable
REM Creates a standalone Windows application in dist\VXC_ADV_Visualizer\

REM ---- Version number - bump this before each release ----
set VERSION=1.0.0

echo ========================================
echo VXC/ADV Visualizer - Build Executable
echo ========================================
echo.

REM Must run from the workspace root (where run.py lives)
cd /d "%~dp0"

REM Check if PyInstaller is installed
python -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo PyInstaller is not installed. Installing...
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
echo Checking for app icon...
if exist "app_icon.png" (
    if not exist "app_icon.ico" (
        echo Converting app_icon.png to app_icon.ico...
        python make_icon.py
        if errorlevel 1 (
            echo WARNING: Icon conversion failed - building without icon
        )
    ) else (
        echo app_icon.ico already exists, skipping conversion.
    )
) else (
    echo No app_icon.png found - building without icon.
)

echo.
echo Building executable with PyInstaller...
echo This may take 3-5 minutes...
echo.

pyinstaller build_exe.spec

if errorlevel 1 (
    echo.
    echo ========================================
    echo BUILD FAILED
    echo Check the output above for errors.
    echo ========================================
    pause
    exit /b 1
)

REM -----------------------------------------------------------------------
REM Seed the writable config directory beside the exe.
REM
REM The app reads config from ./config/ (CWD-relative) first, falling back
REM to the frozen _internal/ bundle copy. Users can edit the file beside
REM the .exe to change COM port, dwell times, etc. without rebuilding.
REM Boundary saves also write here.
REM -----------------------------------------------------------------------
echo.
echo Seeding writable config directory...
if not exist "dist\VXC_ADV_Visualizer\config" mkdir "dist\VXC_ADV_Visualizer\config"
xcopy /Y /Q "vxc_adv_visualizer\config\*.yaml" "dist\VXC_ADV_Visualizer\config\"

REM Copy icon beside the exe so Windows shortcuts pick it up automatically
if exist "app_icon.ico" (
    copy /Y "app_icon.ico" "dist\VXC_ADV_Visualizer\app_icon.ico" >nul
)

REM -----------------------------------------------------------------------
REM Zip the distribution folder for GitHub Releases upload
REM -----------------------------------------------------------------------
echo.
echo Creating release zip...
set ZIP_NAME=VXC_ADV_Visualizer_v%VERSION%.zip
if exist "dist\%ZIP_NAME%" del /Q "dist\%ZIP_NAME%"
powershell -NoProfile -Command "Compress-Archive -Path 'dist\VXC_ADV_Visualizer' -DestinationPath 'dist\%ZIP_NAME%' -Force"
if errorlevel 1 (
    echo WARNING: Zip creation failed - folder is still distributable manually.
) else (
    echo Created: dist\%ZIP_NAME%
)

echo.
echo ========================================
echo BUILD SUCCESSFUL
echo ========================================
echo.
echo Executable:   dist\VXC_ADV_Visualizer\VXC_ADV_Visualizer.exe
echo Config:       dist\VXC_ADV_Visualizer\config\
echo Release zip:  dist\%ZIP_NAME%
echo.
echo To publish a GitHub Release:
echo   1. Go to https://github.com/gwils031/VXC_ADV_Controller/releases/new
echo   2. Set tag: v%VERSION%
echo   3. Upload: dist\%ZIP_NAME%
echo   4. Publish
echo.
echo Recipients: unzip, edit config\vxc_config.yaml (COM port), run the exe.

pause
