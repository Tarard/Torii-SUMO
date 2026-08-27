# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "anyio>=4.0",
#   "mcp[cli]>=1.0.0,<2",
#   "numpy>=1.26",
#   "osmium>=4.3,<5",
#   "Pillow>=10.0",
#   "pyproj>=3.6",
#   "pydantic>=2.7",
#   "scipy>=1.11",
#   "sumolib>=1.20",
#   "traci>=1.20",
#   "tzdata>=2024.1; platform_system == 'Windows'",
# ]
# ///

from __future__ import annotations

import sys
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PLUGIN_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from torii_sumo.server import main


if __name__ == "__main__":
    main()
