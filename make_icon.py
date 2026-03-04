"""Convert app_icon.png -> app_icon.ico with all standard Windows icon sizes.

Usage (from any directory):
    python "C:\\App Development\\ADV&VXC Controller\\make_icon.py"

Or just run build.bat — it calls this automatically.

Requires Pillow (already in the venv):  pip install pillow
"""

from pathlib import Path
from PIL import Image

# Resolve paths relative to this script, not the working directory
ROOT = Path(__file__).resolve().parent
SRC = ROOT / "app_icon.png"
DST = ROOT / "app_icon.ico"

# Windows icon sizes: 16, 24, 32, 48, 64, 128, 256
SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]

if not SRC.exists():
    raise FileNotFoundError(
        f"{SRC} not found.\n"
        "Save the app icon image as 'app_icon.png' in the workspace root first."
    )

img = Image.open(SRC).convert("RGBA")
img.save(DST, format="ICO", sizes=SIZES)
print(f"Created {DST}  ({DST.stat().st_size // 1024} KB, {len(SIZES)} sizes)")
