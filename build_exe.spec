# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for VXC/ADV Visualizer
Build command: pyinstaller build_exe.spec
"""

import sys
from pathlib import Path

block_cipher = None

# Get the base directory
base_dir = Path('.').resolve()

# Data files to include
added_files = [
    ('config', 'config'),  # Include config directory
    ('vxc_adv_visualizer/config', 'vxc_adv_visualizer/config'),  # Include package config
]

# Hidden imports that PyInstaller might miss
hidden_imports = [
    'PyQt5.QtCore',
    'PyQt5.QtGui',
    'PyQt5.QtWidgets',
    'pyqtgraph',
    'numpy',
    'yaml',
    'serial',
    'scipy',
    'pandas',
    'matplotlib',
    'h5py',
]

a = Analysis(
    ['vxc_adv_visualizer/main.py'],
    pathex=[],
    binaries=[],
    datas=added_files,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',  # Exclude tkinter if not used
        'test',
        'unittest',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyd = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyd,
    a.scripts,
    [],
    exclude_binaries=True,
    name='VXC_ADV_Visualizer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # Set to False for GUI app (no console window)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # Add .ico file path here if you have an icon
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='VXC_ADV_Visualizer',
)
