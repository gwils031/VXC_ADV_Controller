# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for VXC/ADV Visualizer
Build command:  pyinstaller build_exe.spec

Entry point: run.py  (root-level launcher so the vxc_adv_visualizer package
is importable by its full dotted name inside the frozen bundle).
"""

from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# Workspace root — added to pathex so PyInstaller analysis can resolve
# "import vxc_adv_visualizer..." as a proper package.
base_dir = str(Path('.').resolve())

# ---------------------------------------------------------------------------
# Data files
# ---------------------------------------------------------------------------
# vxc_adv_visualizer/config must land at that same relative path inside the
# bundle so Path(__file__).parents[1]/"config" lookups work when frozen.
added_files = [
    ('vxc_adv_visualizer/config', 'vxc_adv_visualizer/config'),
]

# Matplotlib ships fonts, style-sheets, and backends as data files.
added_files += collect_data_files('matplotlib')

# ---------------------------------------------------------------------------
# Hidden imports (modules PyInstaller's static analysis misses)
# ---------------------------------------------------------------------------
hidden_imports = [
    # PyQt5
    'PyQt5.QtCore',
    'PyQt5.QtGui',
    'PyQt5.QtWidgets',
    'PyQt5.QtPrintSupport',
    'PyQt5.sip',
    # pyqtgraph
    'pyqtgraph',
    'pyqtgraph.graphicsItems',
    'pyqtgraph.widgets',
    # matplotlib — backend used by LiveDataTab
    'matplotlib',
    'matplotlib.backends.backend_qt5agg',
    'matplotlib.backends.backend_agg',
    'matplotlib.figure',
    # scientific / data
    'numpy',
    'scipy',
    'scipy.signal',
    'scipy.spatial',
    'scipy.stats',
    'pandas',
    'pandas._libs.tslibs.base',
    'pandas._libs.tslibs.np_datetime',
    'pandas._libs.tslibs.nattype',
    'h5py',
    # config / serial
    'yaml',
    'serial',
    'serial.tools',
    'serial.tools.list_ports',
    # stdlib modules PyInstaller misses on Python 3.13
    'html',
    'html.parser',
    'html.entities',
    'urllib',
    'urllib.parse',
    'urllib.request',
    'urllib.error',
    'email',
    'email.mime',
    'email.mime.text',
    'logging.handlers',
    'xml.etree.ElementTree',
]

# Collect all pyqtgraph sub-modules (it uses plugin-style dynamic imports)
hidden_imports += collect_submodules('pyqtgraph')

# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------
a = Analysis(
    ['run.py'],          # Root launcher — see run.py
    pathex=[base_dir],   # Makes vxc_adv_visualizer importable as a package
    binaries=[],
    datas=added_files,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'test',
        'unittest',
        'xmlrpc',
        'email',
        'html',
        'http',
        'urllib',
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
    console=False,   # No terminal window for the GUI release
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='app_icon.ico' if Path('app_icon.ico').exists() else None,
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
