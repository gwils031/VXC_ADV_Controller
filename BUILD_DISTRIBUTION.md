# Building a Distributable Executable

Creates a standalone Windows `.exe` that runs on any Windows 10/11 machine
without requiring Python, pip, or any packages to be installed.

---

## Quick Build

1. **Double-click `build.bat`** from the workspace root (or run it in a terminal).
2. Wait ~3–5 minutes for PyInstaller to finish.
3. Find the output in `dist\VXC_ADV_Visualizer\`.

That's it. The batch script handles PyInstaller installation, cleaning old
builds, bundling, and seeding the writable config directory.

---

## How the Build Works

### Entry point: `run.py`

PyInstaller is pointed at `run.py` (workspace root), not at
`vxc_adv_visualizer/main.py` directly.

`run.py` is a 5-line shim:

```python
from vxc_adv_visualizer.main import main
import sys
sys.exit(main())
```

This matters because `vxc_adv_visualizer/main.py` uses absolute package
imports (`from vxc_adv_visualizer.gui...`). PyInstaller needs to see the
project root on the path during analysis — `run.py` living outside the package
achieves this. Running `python -m vxc_adv_visualizer.main` in development
works for the same reason.

**Do not move `run.py` into the `vxc_adv_visualizer/` sub-folder.**

### Manual build command

```powershell
pyinstaller build_exe.spec
```

Run from the workspace root (`C:\App Development\ADV&VXC Controller\`).

---

## Output Structure (PyInstaller 6+)

```
dist\VXC_ADV_Visualizer\
├── VXC_ADV_Visualizer.exe      ← Double-click to launch
├── config\                     ← Writable settings (edit these, not _internal)
│   ├── experiment_config.yaml
│   └── vxc_config.yaml
└── _internal\                  ← All bundled Python, DLLs, packages (don't touch)
    ├── vxc_adv_visualizer\
    │   └── config\             ← Read-only fallback copies of config files
    ├── PyQt5\
    ├── matplotlib\
    ├── numpy\
    ├── ...
```

> **PyInstaller 6 note**: All dependency files now live in `_internal\` rather
> than flat next to the exe. The exe itself just bootstraps and hands off to
> `_internal`. This is normal — distribute the whole `VXC_ADV_Visualizer\` folder.

---

## Configuration Files in the Distribution

Two copies of each YAML config exist in the dist:

| Location | Purpose |
|----------|---------|
| `dist\VXC_ADV_Visualizer\config\` | **Writable** — edit this on each machine |
| `dist\VXC_ADV_Visualizer\_internal\vxc_adv_visualizer\config\` | Read-only fallback inside the bundle |

The app always reads from `./config/` (beside the `.exe`) first. If that file
is missing it falls back to the frozen copy. Boundary saves and any config
changes write to `./config/`.

**Each deployment machine should edit `config\vxc_config.yaml` to set the
correct COM port:**

```yaml
port: COM8      # Change to the actual port on this PC
baudrate: 57600
```

---

## Distributing the Application

### What to share

Copy or zip the **entire** `dist\VXC_ADV_Visualizer\` folder. Do not share
just the `.exe` — it will not run without `_internal\`.

### Packaging options

**ZIP (recommended)**
1. Right-click `dist\VXC_ADV_Visualizer` → "Send to" → "Compressed (zipped) folder".
2. Share the `.zip`.

**Installer (optional)**
- [Inno Setup](https://jrsoftware.org/isinfo.php) (free)
- [NSIS](https://nsis.sourceforge.io/) (free)

---

## Running on Another Computer

### System requirements (end-user machine)

- Windows 10 or 11 (64-bit)
- No Python installation needed
- USB serial drivers (usually installed automatically by Windows)
- ~300 MB free disk space

### Steps

1. Extract the ZIP to any location, e.g. `C:\VXC_ADV_Visualizer\`.
2. Edit `config\vxc_config.yaml` and set the correct `port:` for this computer.
3. Double-click `VXC_ADV_Visualizer.exe`.
4. If Windows SmartScreen warns about an unknown publisher:
   - Click **More info** → **Run anyway**.

### First-run folder creation

On first launch the app creates these folders beside the exe if they don't exist:

```
VXC_ADV_Visualizer\
├── ADV_Data\           ← Drop FlowTracker2 CSV exports here
├── VXC_Positions\      ← VXC position logs are written here
├── Data_Output\        ← Merged/averaged session output
└── vxc_adv_system.log  ← Rotating log (5 MB × 3 backups)
```

---

## Troubleshooting Build Issues

### "ModuleNotFoundError" or import error in build output

Add the missing module to `hidden_imports` in `build_exe.spec`:

```python
hidden_imports = [
    ...
    'your.missing.module',
]
```

Then rerun `build.bat`.

### Config files not found at runtime

The spec copies `vxc_adv_visualizer/config` into the bundle automatically.
If a new YAML config was added to a different path, add it to `added_files`
in `build_exe.spec`:

```python
added_files = [
    ('vxc_adv_visualizer/config', 'vxc_adv_visualizer/config'),
    ('your/new/config', 'your/new/config'),
    ...
]
```

### Antivirus false positive

- Add an exception in the antivirus software.
- Or sign the exe with a code-signing certificate.
- Submit to the AV vendor as a false positive.

### Build produces errors about UPX

UPX is optional. If it causes issues, set `upx=False` in both the `EXE` and
`COLLECT` blocks in `build_exe.spec`.

---

## Adding the Application Icon

The icon is embedded in the `.exe` and also shown in the Windows taskbar and
Alt+Tab switcher.

### Steps

1. **Save the icon image** as `app_icon.png` in the workspace root
   (`C:\App Development\ADV&VXC Controller\app_icon.png`).
   The image should be square; 1024×1024 px or 512×512 px is ideal.

2. **Run the conversion script** to produce a multi-size `.ico`:
   ```powershell
   python make_icon.py
   ```
   This creates `app_icon.ico` with sizes 16 × 16 through 256 × 256, which
   Windows uses depending on context (taskbar, Start menu, file Explorer).

3. **Rebuild** — `build.bat` automatically detects `app_icon.png`, generates
   `app_icon.ico` if it is missing, then passes it to PyInstaller.
   You do not need to run `make_icon.py` manually before each build.

`build_exe.spec` picks up the icon automatically:

```python
icon='app_icon.ico' if Path('app_icon.ico').exists() else None,
```

If `app_icon.ico` is absent the build succeeds with the default PyInstaller
icon — no error.

---

## License Note

PyQt5 is GPL-licensed. For commercial distribution, consider switching to
PySide6 (LGPL). All other dependencies use permissive licenses (MIT/BSD).

---

## Last Updated

March 4, 2026
