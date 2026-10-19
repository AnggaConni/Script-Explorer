"""Legacy entry point kept for backwards compatibility.

Use:
    python scripts/build_datasets.py --unicode-version latest
or select a fixed release, e.g.:
    python scripts/build_datasets.py --unicode-version 18.0.0
"""
from pathlib import Path
import runpy
import sys

root = Path(__file__).resolve().parent
generator = root / "scripts" / "build_datasets.py"
if not generator.exists():
    raise SystemExit(
        "The shared generator was not found. Run this script from a complete "
        "Script-Explorer checkout."
    )

sys.argv = [str(generator), *sys.argv[1:]]
runpy.run_path(str(generator), run_name="__main__")
