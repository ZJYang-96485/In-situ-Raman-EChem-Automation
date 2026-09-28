"""Expose each local package when pytest is launched from the repository root."""

from pathlib import Path
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parent
for relative_path in (
    "CHI760 Potentiostat",
    "Raman Spectroscopy",
    "Machine Learning Platform",
):
    package_root = str(REPOSITORY_ROOT / relative_path)
    if package_root not in sys.path:
        sys.path.insert(0, package_root)
