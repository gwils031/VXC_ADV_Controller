# Building Distributable Executable

This guide explains how to create a standalone executable of the VXC/ADV Visualizer application that can be run on other Windows computers without requiring Python installation.

## Quick Start

### Option 1: Using the Build Script (Easiest)

1. **Double-click `build.bat`**
2. Wait for the build to complete (~2-5 minutes)
3. Find your application in `dist\VXC_ADV_Visualizer\`

### Option 2: Manual Build

1. **Install PyInstaller** (if not already installed):
   ```bash
   pip install pyinstaller
   ```

2. **Run the build command**:
   ```bash
   pyinstaller build_exe.spec
   ```

3. **Find the output** in `dist\VXC_ADV_Visualizer\`

## Distributing the Application

### What to Share

Copy the **entire folder** `dist\VXC_ADV_Visualizer\` which contains:
- `VXC_ADV_Visualizer.exe` - The main executable
- All required DLL files and dependencies
- `config\` folder with default configuration
- Other necessary runtime files

### Packaging for Distribution

**Option A: ZIP File** (Recommended)
1. Right-click the `dist\VXC_ADV_Visualizer` folder
2. Select "Send to" → "Compressed (zipped) folder"
3. Share the resulting `.zip` file

**Option B: Installer** (Advanced)
Use tools like:
- **Inno Setup** (free): https://jrsoftware.org/isinfo.php
- **NSIS** (free): https://nsis.sourceforge.io/
- **Advanced Installer** (paid): https://www.advancedinstaller.com/

### Folder Structure After Build

```
dist\VXC_ADV_Visualizer\
├── VXC_ADV_Visualizer.exe  ← Main executable
├── config\                  ← Configuration files
│   ├── adv_config.yaml
│   ├── experiment_config.yaml
│   └── vxc_config.yaml
├── PyQt5\                   ← PyQt5 libraries
├── numpy\                   ← Numpy libraries
├── *.dll                    ← Required DLLs
└── ... (other dependencies)
```

## Running on Another Computer

### System Requirements
- **OS**: Windows 10 or later (64-bit)
- **RAM**: Minimum 4GB, 8GB recommended
- **Disk Space**: ~200MB for application + space for data
- **Ports**: USB ports for VXC controller and ADV sensor
- **Drivers**: USB serial drivers (usually automatic)

### Installation Steps for End Users

1. **Extract the ZIP file** to any location (e.g., `C:\Program Files\VXC_ADV_Visualizer\`)

2. **Run the executable**:
   - Navigate to the extracted folder
   - Double-click `VXC_ADV_Visualizer.exe`
   - Windows may show a security warning (click "More info" → "Run anyway")

3. **First-time setup**:
   - The application creates necessary folders on first run:
     - `Data_Output\` - For merged data
     - `VXC_Positions\` - For VXC position logs
     - `ADV_Data\` - For ADV exports
     - `vxc_adv_system.log` - Application log file

### Windows Security Warning

When users first run the `.exe`, Windows SmartScreen may display a warning:
- Click "More info"
- Click "Run anyway"

**To avoid this** (optional):
- Sign the executable with a code signing certificate
- Build reputation over time with Microsoft SmartScreen

## Troubleshooting Build Issues

### Issue: "Module not found" errors

**Solution**: Add missing module to `hiddenimports` in `build_exe.spec`:
```python
hidden_imports = [
    'PyQt5.QtCore',
    'your_missing_module',  # Add here
]
```

### Issue: Config files not included

**Solution**: Update `added_files` in `build_exe.spec`:
```python
added_files = [
    ('config', 'config'),
    ('your_folder', 'your_folder'),  # Add here
]
```

### Issue: Executable too large

**Solution**: 
1. Use `--onefile` for single executable (slower startup)
2. Enable UPX compression (already enabled in spec file)
3. Exclude unused modules in spec file

### Issue: Antivirus false positive

**Solution**:
- Add exception in antivirus software
- Sign the executable with code signing certificate
- Submit to antivirus vendors as false positive

## Advanced Options

### Single-File Executable

To create a single `.exe` file instead of a folder, modify `build_exe.spec`:

```python
exe = EXE(
    pyd,
    a.scripts,
    a.binaries,      # Add this
    a.zipfiles,      # Add this
    a.datas,         # Add this
    [],
    name='VXC_ADV_Visualizer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    # Remove these:
    # exclude_binaries=True,
)

# Remove COLLECT block
```

**Note**: Single-file mode:
- ✅ Easier to distribute (one file)
- ❌ Slower startup (extracts to temp folder)
- ❌ Larger file size

### Adding an Icon

1. Create or find a `.ico` file
2. Place it in the project root (e.g., `app_icon.ico`)
3. Update `build_exe.spec`:
   ```python
   exe = EXE(
       ...
       icon='app_icon.ico',
   )
   ```

### Build Size Optimization

Typical build size: **150-250 MB**

To reduce size:
1. Remove unused dependencies from `requirements.txt`
2. Use virtual environment with minimal packages
3. Exclude test/development dependencies
4. Enable UPX compression (already enabled)

## Continuous Deployment

### Automated Builds

Create a GitHub Actions workflow or use:
```bash
# Build and package in one command
build.bat && cd dist && tar -a -c -f VXC_ADV_Visualizer.zip VXC_ADV_Visualizer
```

### Version Management

Add version info to `build_exe.spec`:
```python
exe = EXE(
    ...
    name='VXC_ADV_Visualizer_v1.0.0',
)
```

## Support

For build issues:
- Check the build log in `build\` folder
- Review `vxc_adv_system.log` for runtime errors
- Test the executable on the build machine first

## License & Distribution

Before distributing:
- Ensure compliance with all dependency licenses
- PyQt5 is GPL licensed - ensure compliance
- Consider using PySide6 (LGPL) for commercial use
