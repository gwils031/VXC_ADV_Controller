"""PyInstaller entry point for VXC/ADV Visualizer.

This file exists solely to give PyInstaller a root-level script to analyse.
Running from the workspace root means 'vxc_adv_visualizer' is resolvable as
a package (same as `python -m vxc_adv_visualizer.main` in development).

Do NOT move this file into the vxc_adv_visualizer/ sub-folder — the whole
point is that it lives outside the package so the project root is on sys.path
when PyInstaller bundles it.
"""

import sys
from vxc_adv_visualizer.main import main

if __name__ == "__main__":
    sys.exit(main())
